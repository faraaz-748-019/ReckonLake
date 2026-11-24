"""
RBAC access policies for ReconLake.

Roles and permissions follow the principle of least privilege.
Every data-plane operation is gated through is_allowed().

Roles:
    PIPELINE_WRITER   Spark/Airflow jobs that write to Bronze/Silver/Gold.
    ANALYST           Read-only access to Gold layer and dashboards.
    RECONCILER        Read Silver + write to exception queues.
    SECURITY_ADMIN    Key management, audit log access, role assignment.
    AUDITOR           Read-only access to audit logs and lineage.
    SHREDDER          Can trigger crypto-shredding; cannot read data.

Permissions (resource:action format):
    bronze:write        Append events to the Bronze Delta table.
    silver:write        Write to Silver (deduplicated) tables.
    gold:write          Write to Gold (business-ready) tables.
    bronze:read         Read Bronze tables (raw; contains tokens, never VPAs).
    silver:read         Read Silver tables.
    gold:read           Read Gold / analytical views.
    exception:write     Enqueue / dequeue exception records.
    exception:read      View exception queue.
    audit:read          Read the audit chain log.
    keys:manage         Create / rotate / revoke encryption keys.
    keys:access         Decrypt / re-wrap data keys (triggers audit event).
    roles:assign        Assign or revoke roles for other subjects.
    shred:execute       Execute crypto-shredding for a token_id.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    PIPELINE_WRITER = "pipeline_writer"
    ANALYST = "analyst"
    RECONCILER = "reconciler"
    SECURITY_ADMIN = "security_admin"
    AUDITOR = "auditor"
    SHREDDER = "shredder"


class Permission(str, Enum):
    BRONZE_WRITE = "bronze:write"
    SILVER_WRITE = "silver:write"
    GOLD_WRITE = "gold:write"
    BRONZE_READ = "bronze:read"
    SILVER_READ = "silver:read"
    GOLD_READ = "gold:read"
    EXCEPTION_WRITE = "exception:write"
    EXCEPTION_READ = "exception:read"
    AUDIT_READ = "audit:read"
    KEYS_MANAGE = "keys:manage"
    KEYS_ACCESS = "keys:access"
    ROLES_ASSIGN = "roles:assign"
    SHRED_EXECUTE = "shred:execute"


# ---------------------------------------------------------------------------
# Permission matrix: role -> frozenset of permissions
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PIPELINE_WRITER: frozenset(
        {
            Permission.BRONZE_WRITE,
            Permission.SILVER_WRITE,
            Permission.GOLD_WRITE,
            Permission.BRONZE_READ,
            Permission.SILVER_READ,
        }
    ),
    Role.ANALYST: frozenset(
        {
            Permission.GOLD_READ,
            Permission.SILVER_READ,
        }
    ),
    Role.RECONCILER: frozenset(
        {
            Permission.SILVER_READ,
            Permission.GOLD_READ,
            Permission.EXCEPTION_WRITE,
            Permission.EXCEPTION_READ,
        }
    ),
    Role.SECURITY_ADMIN: frozenset(
        {
            Permission.KEYS_MANAGE,
            Permission.KEYS_ACCESS,
            Permission.ROLES_ASSIGN,
            Permission.AUDIT_READ,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.AUDIT_READ,
        }
    ),
    Role.SHREDDER: frozenset(
        {
            Permission.SHRED_EXECUTE,
        }
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_allowed(role: Role, permission: Permission) -> bool:
    """
    Return True if *role* is granted *permission*.

    Args:
        role:       The subject's assigned role.
        permission: The action being requested.

    Returns:
        bool — True if the role has the permission, False otherwise.

    Example:
        >>> is_allowed(Role.ANALYST, Permission.GOLD_READ)
        True
        >>> is_allowed(Role.ANALYST, Permission.BRONZE_WRITE)
        False
    """
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for(role: Role) -> frozenset[Permission]:
    """Return the full set of permissions granted to *role*."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def roles_with_permission(permission: Permission) -> list[Role]:
    """Return all roles that have *permission* (useful for audit queries)."""
    return [
        role
        for role, perms in ROLE_PERMISSIONS.items()
        if permission in perms
    ]
