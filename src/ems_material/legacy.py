"""Import adapters for standalone eMotorSolution material JSON.

This module understands legacy wire formats but imports no eMotorSolution code.
It rejects expressions that cannot be reduced to numeric literals, avoiding the
legacy product's use of ``eval`` in the shared Core.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .errors import LegacyImportError
from .model import (
    Axis,
    CurveProperty,
    Material,
    MaterialIdentity,
    MaterialProperty,
    Provenance,
    ScalarProperty,
    VersionMetadata,
)


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    material: Material
    source_format: str
    warnings: tuple[str, ...] = ()


def _value(data: dict[str, Any], public: str, private: str | None = None) -> Any:
    if public in data:
        return data[public]
    private = private or f"_{public}"
    if private in data:
        return data[private]
    raise LegacyImportError(f"Legacy field {public!r} is missing")


def _optional_value(
    data: dict[str, Any], public: str, private: str | None = None, default: Any = None
) -> Any:
    if public in data:
        return data[public]
    private = private or f"_{public}"
    return data.get(private, default)


def _numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise LegacyImportError(f"{field_name} must be numeric, not boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise LegacyImportError(f"{field_name} is not numeric")
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError) as error:
        raise LegacyImportError(
            f"{field_name} contains a product expression and needs adapter context: {value!r}"
        ) from error
    if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
        raise LegacyImportError(f"{field_name} is not a numeric literal: {value!r}")
    return float(parsed)


def _curve(
    permeability: dict[str, Any],
    data_name: str,
    *,
    property_name: str,
) -> tuple[str, CurveProperty]:
    rows = _value(permeability, data_name)
    if not isinstance(rows, list):
        raise LegacyImportError(f"Legacy {data_name} must be a list")
    try:
        h_values = tuple(_numeric(row[0], f"{data_name}[{index}].H") for index, row in enumerate(rows))
        b_values = tuple(_numeric(row[1], f"{data_name}[{index}].B") for index, row in enumerate(rows))
    except (IndexError, TypeError) as error:
        raise LegacyImportError(f"Legacy {data_name} rows must contain [H, B]") from error
    return (
        property_name,
        CurveProperty(
            x=Axis("H", _value(permeability, "h_unit"), h_values),
            y=Axis("B", _value(permeability, "b_unit"), b_values),
            display={"x_scale": "linear", "y_scale": "linear"},
        ),
    )


def _non_magnet_properties(
    data: dict[str, Any], warnings: list[str]
) -> dict[str, dict[str, MaterialProperty]]:
    electromagnetic: dict[str, MaterialProperty] = {
        "electrical_conductivity": ScalarProperty(
            _numeric(_value(data, "conductivity_expression"), "conductivity_expression"),
            _value(data, "conductivity_unit"),
        )
    }
    permeability = data.get("permeability")
    if not isinstance(permeability, dict):
        raise LegacyImportError("Legacy permeability must be an object")
    permeability_type = data.get("permeability_type")
    if permeability_type == "linear":
        electromagnetic["relative_permeability"] = ScalarProperty(
            _numeric(
                _value(permeability, "relative_permeability_expression"),
                "relative_permeability_expression",
            ),
            "1",
        )
    elif permeability_type == "nonlinear":
        name, value = _curve(permeability, "data", property_name="BH_curve")
        electromagnetic[name] = value
    elif permeability_type == "anisotropic nonlinear":
        for data_name, property_name in (
            ("x_data", "BH_curve_x"),
            ("y_data", "BH_curve_y"),
        ):
            name, value = _curve(permeability, data_name, property_name=property_name)
            electromagnetic[name] = value
    elif isinstance(permeability_type, str) and permeability_type.startswith("encrypted"):
        raise LegacyImportError("Protected/encrypted material import is outside the PoC scope")
    else:
        raise LegacyImportError(f"Unsupported legacy permeability_type: {permeability_type!r}")

    iron_loss = data.get("iron_loss")
    if isinstance(iron_loss, dict):
        loss_type = iron_loss.get("type")
        if loss_type == "yamazaki":
            electromagnetic["iron_loss_ke"] = ScalarProperty(
                _numeric(_value(iron_loss, "ke_expression"), "iron_loss.ke"),
                _optional_value(iron_loss, "ke_unit", default="W/kg/T^2/Hz^2"),
            )
            electromagnetic["iron_loss_kh"] = ScalarProperty(
                _numeric(_value(iron_loss, "kh_expression"), "iron_loss.kh"),
                _optional_value(iron_loss, "kh_unit", default="W/kg/T^2/Hz"),
            )
        elif loss_type == "anisotropic_yamazaki":
            for direction in ("x", "y"):
                electromagnetic[f"iron_loss_ke_{direction}"] = ScalarProperty(
                    _numeric(
                        _value(iron_loss, f"ke_{direction}_expression"),
                        f"iron_loss.ke_{direction}",
                    ),
                    _optional_value(
                        iron_loss,
                        f"ke_{direction}_unit",
                        default="W/kg/T^2/Hz^2",
                    ),
                )
            for direction in ("x", "y", "z"):
                electromagnetic[f"iron_loss_kh_{direction}"] = ScalarProperty(
                    _numeric(
                        _value(iron_loss, f"kh_{direction}_expression"),
                        f"iron_loss.kh_{direction}",
                    ),
                    _optional_value(
                        iron_loss,
                        f"kh_{direction}_unit",
                        default="W/kg/T^2/Hz",
                    ),
                )
        elif loss_type is not None:
            warnings.append(f"Unsupported iron loss model {loss_type!r} was not imported")
    return {"electromagnetic": electromagnetic}


def _magnet_properties(data: dict[str, Any]) -> dict[str, dict[str, MaterialProperty]]:
    return {
        "electromagnetic": {
            "remanence_radial": ScalarProperty(
                _numeric(_value(data, "radial_expression"), "radial_expression"),
                _value(data, "radial_unit"),
            ),
            "remanence_tangential": ScalarProperty(
                _numeric(_value(data, "tangential_expression"), "tangential_expression"),
                _value(data, "tangential_unit"),
            ),
            "electrical_conductivity": ScalarProperty(
                _numeric(
                    _value(data, "conductivity_expression"), "conductivity_expression"
                ),
                _value(data, "conductivity_unit"),
            ),
            "relative_permeability": ScalarProperty(
                _numeric(
                    _value(data, "relative_permeability_expression"),
                    "relative_permeability_expression",
                ),
                "1",
            ),
        }
    }


def _add_density(
    data: dict[str, Any],
    properties: dict[str, dict[str, MaterialProperty]],
    warnings: list[str],
) -> None:
    manufacturing = data.get("manufacturing")
    expression = None
    unit = "kg/m^3"
    if isinstance(manufacturing, dict):
        expression = _optional_value(manufacturing, "mass_density_expression")
        unit = _optional_value(manufacturing, "mass_density_unit", default=unit)
    if expression in (None, ""):
        iron_loss = data.get("iron_loss")
        if isinstance(iron_loss, dict):
            expression = _optional_value(iron_loss, "mass_density_expression")
            unit = _optional_value(iron_loss, "mass_density_unit", default=unit)
            if expression not in (None, ""):
                warnings.append("Density was migrated from the legacy iron-loss model")
    if expression not in (None, ""):
        properties.setdefault("general", {})["density"] = ScalarProperty(
            _numeric(expression, "mass_density_expression"), unit
        )


def import_legacy_material_document(
    data: dict[str, Any],
    *,
    material_id: str,
    family: str,
    author: str,
    updated_at: str | None = None,
    source_reference: str | None = None,
    source_type: str = "UNKNOWN",
) -> LegacyImportResult:
    """Translate an eMotorSolution standalone/project material record."""

    if not isinstance(data, dict):
        raise LegacyImportError("Legacy material must be a JSON object")
    warnings: list[str] = []
    material_type = data.get("type")
    if material_type == "non_magnet":
        properties = _non_magnet_properties(data, warnings)
    elif material_type == "magnet":
        properties = _magnet_properties(data)
    else:
        raise LegacyImportError(f"Unsupported legacy material type: {material_type!r}")
    _add_density(data, properties, warnings)

    manufacturing = data.get("manufacturing")
    manufacturer = (
        _optional_value(manufacturing, "manufacturer")
        if isinstance(manufacturing, dict)
        else None
    ) or None
    grade = (
        _optional_value(manufacturing, "grade")
        if isinstance(manufacturing, dict)
        else None
    ) or None
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    material = Material(
        material_id=material_id,
        material_version="1.0.0",
        identity=MaterialIdentity(
            name=str(data.get("name") or "Unnamed legacy material"),
            family=family,
            manufacturer=manufacturer,
            grade=grade,
        ),
        properties=properties,
        provenance=Provenance(
            source_type=source_type,
            reference=source_reference,
            notes="Imported from eMotorSolution legacy material JSON",
        ),
        version_metadata=VersionMetadata(
            author=author,
            updated_at=timestamp,
            change_note="Initial migration from eMotorSolution legacy format",
        ),
    )
    key_style = "public" if any(
        key in data.get("permeability", {}) for key in ("data", "b_unit", "h_unit")
    ) else "private"
    return LegacyImportResult(
        material=material,
        source_format=f"emotorsolution_material_{key_style}_keys",
        warnings=tuple(warnings),
    )


def load_legacy_material(
    path: str | Path,
    **metadata: Any,
) -> LegacyImportResult:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LegacyImportError(f"Cannot read legacy material {source}: {error}") from error
    metadata.setdefault("source_reference", str(source))
    return import_legacy_material_document(data, **metadata)
