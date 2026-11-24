# Contributing to ReconLake

Thank you for your interest in contributing! This document outlines the process for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)

---

## Code of Conduct

All contributors are expected to uphold a respectful and inclusive environment.
Harassment, discrimination, and disruptive behaviour will not be tolerated.

---

## Getting Started

### Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| Docker + Compose | ≥ 24 / ≥ 2.20 |
| GNU Make | any recent |
| pre-commit | ≥ 3.6 |

### Local setup

```bash
git clone https://github.com/example/reconlake.git
cd reconlake

# Install Python deps in a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,test,security]"

# Install pre-commit hooks
pre-commit install

# Spin up the core infrastructure
make up PROFILE=core

# Verify everything is green
make test
```

---

## Development Workflow

1. **Create a branch** from `main` using the naming convention below.
2. **Make small, focused commits** (one logical change per commit).
3. **Run checks locally** before pushing:
   ```bash
   make lint typecheck test security
   ```
4. **Open a pull request** against `main` with a clear description.
5. **Respond to review feedback** promptly.

### Branch naming

```
feat/<short-description>
fix/<short-description>
chore/<short-description>
docs/<short-description>
refactor/<short-description>
test/<short-description>
```

---

## Commit Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

```
<type>(<optional scope>): <imperative summary>

[optional body]

[optional footer(s)]
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only changes |
| `style` | Formatting, whitespace — no logic change |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or correcting tests |
| `chore` | Build process, tooling, dependency updates |
| `ci` | CI/CD pipeline changes |
| `perf` | Performance improvements |
| `revert` | Reverts a previous commit |

### Examples

```
feat(ingestion): add Kafka consumer for UPI settlement events

fix(recon): handle duplicate transaction IDs in Bronze→Silver merge

docs(readme): update quickstart with SeaweedFS bucket creation step

chore(deps): bump pyspark from 3.5.2 to 3.5.3
```

### Breaking changes

Append `!` after the type/scope and add a `BREAKING CHANGE:` footer:

```
feat(api)!: rename /recon/status endpoint to /recon/state

BREAKING CHANGE: clients must update URL references from /recon/status to /recon/state.
```

---

## Pull Request Process

1. Ensure all CI checks pass before requesting review.
2. Keep PRs focused — one feature or fix per PR.
3. Update `CHANGELOG.md` under `[Unreleased]` for every user-facing change.
4. Add or update tests to cover your changes (aim for ≥ 80 % line coverage on new code).
5. Update relevant documentation (README, docstrings, dbt model descriptions).
6. PRs require **at least one approving review** before merge.
7. Use **Squash and merge** unless a linear history is explicitly needed.

---

## Coding Standards

### Python

- Formatter & linter: **Ruff** (`make lint`)
- Type annotations required on all public functions; checked by **mypy** (`make typecheck`)
- Docstrings: [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- Max line length: **120** characters

### SQL / dbt

- Linter: **SQLFluff** (dialect: `sparksql` for Spark models, `postgres` for PostgreSQL seeds)
- All dbt models must have a `.yml` description and at least one `not_null` / `unique` test

### Docker

- Linter: **hadolint** (runs in pre-commit)
- Images must be pinned to a specific digest or tag — no `latest`
- Never embed secrets in images; use mounted secrets or OpenBao agent

### Secrets

- **Never commit credentials, keys, or tokens.**
- Use `make generate-secrets` to create local dev secrets (written to `secrets/`, which is gitignored).
- Rotate secrets with `infra/scripts/rotate-secrets.sh`.

---

## Testing Requirements

| Layer | Framework | Location |
|-------|-----------|----------|
| Unit | pytest | `tests/unit/` |
| Integration | pytest + Docker Compose | `tests/integration/` |
| Data quality | Great Expectations | `tests/data_quality/` |
| dbt | dbt test | `dbt/` |

Run all tests:

```bash
make test
```

Run a specific subset:

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v -m "not slow"
```

Coverage must not drop below **70 %** overall; CI will fail if it does.

---

## Questions?

Open a [GitHub Discussion](https://github.com/example/reconlake/discussions) or file an issue with the `question` label.
