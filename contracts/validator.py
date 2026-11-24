"""
Data Contract loader, Pydantic + JSONSchema validator, and quarantine reason-code classifier.
Usable by PySpark ingestion jobs, local pipelines, and CI checks.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import BaseModel, Field

CONTRACTS_DIR = Path(__file__).resolve().parent
TOKEN_HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
RAW_PII_VPA_RE = re.compile(r"^[a-zA-Z0-9._-]+@[a-zA-Z0-9]+$")


class ContractField(BaseModel):
    name: str
    type: str
    nullable: bool = False
    description: str = ""
    enum: list[Any] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    pattern: str | None = None
    format: str | None = None


class DataContract(BaseModel):
    version: str
    owner: str
    source: str
    compatibility: str = "backward"
    freshness_sla_minutes: int = Field(ge=1)
    dq_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    description: str = ""
    schema_fields: list[ContractField] = Field(alias="schema")
    semantic_rules: list[dict[str, str]] = Field(default_factory=list)


def load_contract(source: str, contracts_dir: Path | None = None) -> dict[str, Any]:
    """Load and validate a YAML contract file by source name (psp, payer_bank, switch)."""
    base = contracts_dir or CONTRACTS_DIR
    clean_name = source.replace("_ledger", "")
    path = base / f"{clean_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Contract not found for source '{source}': {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Validate contract structure itself via Pydantic
    DataContract.model_validate(raw)
    return dict(raw)


def contract_to_jsonschema(contract: dict[str, Any]) -> dict[str, Any]:
    """Convert a ReconLake YAML contract into a strict JSON Schema."""
    type_map = {
        "string": "string",
        "long": "integer",
        "integer": "integer",
        "double": "number",
        "boolean": "boolean",
    }
    properties: dict[str, Any] = {}
    required: list[str] = []

    for col in contract["schema"]:
        name = col["name"]
        json_type = type_map.get(col["type"], "string")
        prop: dict[str, Any] = {
            "type": [json_type, "null"] if col.get("nullable", False) else json_type
        }
        if "enum" in col:
            prop["enum"] = col["enum"]
        if "minimum" in col:
            prop["minimum"] = col["minimum"]
        if "maximum" in col:
            prop["maximum"] = col["maximum"]
        if "pattern" in col:
            prop["pattern"] = col["pattern"]
        properties[name] = prop
        if not col.get("nullable", False):
            required.append(name)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def validate_event(event: dict[str, Any], contract: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate a single ledger event against its data contract.

    Returns:
        (is_valid, list_of_reason_codes)
    """
    reasons: list[str] = []
    schema_fields = {f["name"]: f for f in contract["schema"]}

    # 1. Check for unexpected/drifted fields (schema drift)
    for key in event:
        if key not in schema_fields and key != "extra":
            reasons.append(f"SCHEMA_DRIFT:unexpected_field:{key}")

    # 2. Check required / non-nullable fields and types
    for fname, fspec in schema_fields.items():
        val = event.get(fname)
        if val is None:
            if not fspec.get("nullable", False):
                reasons.append(f"NULL_KEY:missing_or_null:{fname}")
            continue

        expected_type = fspec["type"]
        if expected_type == "string" and not isinstance(val, str):
            reasons.append(f"WRONG_TYPE:{fname}:expected_string")
            continue
        if expected_type in ("long", "integer") and (isinstance(val, bool) or not isinstance(val, int)):
            reasons.append(f"WRONG_TYPE:{fname}:expected_int")
            continue

        if "enum" in fspec and val not in fspec["enum"]:
            reasons.append(f"SEMANTIC_ENUM:{fname}:{val}")

        if "minimum" in fspec and isinstance(val, int | float) and val < fspec["minimum"]:
            reasons.append(f"SEMANTIC_RANGE:{fname}:below_min")

        if "maximum" in fspec and isinstance(val, int | float) and val > fspec["maximum"]:
            reasons.append(f"SEMANTIC_RANGE:{fname}:above_max")

        if "pattern" in fspec and isinstance(val, str) and not re.match(fspec["pattern"], val):
            if fname.endswith("_token") and RAW_PII_VPA_RE.match(val):
                reasons.append(f"PII_EXPOSURE:{fname}:raw_vpa_detected")
            else:
                reasons.append(f"SEMANTIC_PATTERN:{fname}")

        if fspec.get("format") == "date-time" and isinstance(val, str):
            if val.startswith("LATE#"):
                reasons.append("LATE_MARKER:unparsed_late_timestamp")
            else:
                try:
                    datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    reasons.append(f"WRONG_TYPE:{fname}:invalid_iso8601")

    # 3. Also validate against strict JSONSchema when no custom drift/null issues blocked
    if not reasons:
        jschema = contract_to_jsonschema(contract)
        clean_ev = {k: v for k, v in event.items() if k != "extra"}
        validator = jsonschema.Draft202012Validator(jschema)
        for err in validator.iter_errors(clean_ev):
            reasons.append(f"JSONSCHEMA:{err.message[:80]}")

    return len(reasons) == 0, reasons
