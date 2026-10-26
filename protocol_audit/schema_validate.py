"""Validate against JSON Schema files in product dir."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {
    "report": ROOT / "audit-report.v0.2.schema.json",
    "request": ROOT / "audit-request.v0.2.schema.json",
    "preview": ROOT / "parse-preview.v0.2.schema.json",
}


def load_schema(kind: str) -> dict[str, Any]:
    path = SCHEMAS[kind]
    return json.loads(path.read_text(encoding="utf-8"))


def validate(kind: str, doc: dict[str, Any]) -> list[str]:
    """Return list of error messages; empty = ok."""
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["jsonschema not installed"]

    schema = load_schema(kind)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    out = []
    for e in errors:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        out.append(f"{path}: {e.message}")
    return out


def assert_valid(kind: str, doc: dict[str, Any]) -> None:
    errs = validate(kind, doc)
    if errs:
        raise AssertionError(f"schema {kind} errors:\n" + "\n".join(errs[:30]))
