"""Schema validation and JSON persistence for canonical material records."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import MaterialParseError, SchemaValidationError
from .model import Material


def schema_document() -> dict[str, Any]:
    schema_path = files("ems_material.schemas").joinpath("material-v1.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


_VALIDATOR = Draft202012Validator(schema_document(), format_checker=FormatChecker())


def validate_document(data: dict[str, Any]) -> None:
    """Validate a decoded document against Canonical JSON v1."""

    issues: list[str] = []
    for error in sorted(_VALIDATOR.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        issues.append(f"{location}: {error.message}")
    if issues:
        raise SchemaValidationError(issues)


def material_from_dict(data: dict[str, Any]) -> Material:
    validate_document(data)
    return Material.from_dict(data)


def material_from_json(text: str) -> Material:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise MaterialParseError(
            f"Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    if not isinstance(data, dict):
        raise SchemaValidationError(("$: material document must be a JSON object",))
    return material_from_dict(data)


def material_to_json(material: Material) -> str:
    data = material.to_dict()
    validate_document(data)
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def load_material(path: str | os.PathLike[str]) -> Material:
    return material_from_json(Path(path).read_text(encoding="utf-8"))


def save_material(material: Material, path: str | os.PathLike[str]) -> None:
    """Save a material using same-directory atomic replacement."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = material_to_json(material)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise
