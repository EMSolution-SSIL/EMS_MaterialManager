"""Externally configurable canonical property catalog."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from .errors import (
    ManagerConfigurationError,
    ModelValidationError,
    UnitConversionError,
)
from .units import unit_dimension


PropertyKind = Literal["scalar", "curve"]


@dataclass(frozen=True, slots=True)
class PropertyCategory:
    key: str
    label: str
    color: str


@dataclass(frozen=True, slots=True)
class PropertySubcategory:
    key: str
    label: str
    category: str
    color: str


@dataclass(frozen=True, slots=True)
class PropertyDefinition:
    path: str
    label: str
    category: str
    kind: PropertyKind
    unit: str = ""
    description: str = ""
    required_profiles: tuple[str, ...] = ()
    x_name: str = "X"
    x_unit: str = "1"
    y_name: str = "Y"
    y_unit: str = "1"
    aliases: tuple[str, ...] = ()
    subcategory: str | None = None
    applicable_families: tuple[str, ...] = ()
    minimum: float | None = None
    exclusive_minimum: bool = False
    maximum: float | None = None
    exclusive_maximum: bool = False
    note_recommended: bool = False
    note_guidance: str = ""


@dataclass(frozen=True, slots=True)
class PropertyCatalog:
    schema_version: str
    categories: tuple[PropertyCategory, ...]
    subcategories: tuple[PropertySubcategory, ...]
    definitions: tuple[PropertyDefinition, ...]

    def property_definition(self, path: str) -> PropertyDefinition | None:
        requested = path.casefold()
        for definition in self.definitions:
            candidates = (definition.path, *definition.aliases)
            if requested in {candidate.casefold() for candidate in candidates}:
                return definition
        return None

    def category_definition(self, key: str) -> PropertyCategory | None:
        return next((item for item in self.categories if item.key == key), None)

    def applies_to_family(self, definition: PropertyDefinition, family: str) -> bool:
        if not definition.applicable_families:
            return True
        requested = family.casefold()
        return requested in {item.casefold() for item in definition.applicable_families}

    def validate_property(self, path: str, prop: object) -> None:
        definition = self.property_definition(path)
        if definition is None:
            return
        prop_type = getattr(prop, "type", None)
        if prop_type != definition.kind:
            raise ModelValidationError(
                f"{definition.path} must be a {definition.kind} property"
            )
        if definition.kind == "scalar":
            unit = getattr(prop, "unit", "")
            try:
                actual_dimension = unit_dimension(unit)
                expected_dimension = unit_dimension(definition.unit)
            except UnitConversionError as error:
                raise ModelValidationError(str(error)) from error
            if actual_dimension != expected_dimension:
                raise ModelValidationError(
                    f"{definition.path} requires a {expected_dimension} unit, "
                    f"not {unit!r}"
                )
            value = getattr(prop, "value")
            if definition.minimum is not None:
                invalid = (
                    value <= definition.minimum
                    if definition.exclusive_minimum
                    else value < definition.minimum
                )
                if invalid:
                    operator = ">" if definition.exclusive_minimum else ">="
                    raise ModelValidationError(
                        f"{definition.path} must be {operator} {definition.minimum:g}"
                    )
            if definition.maximum is not None:
                invalid = (
                    value >= definition.maximum
                    if definition.exclusive_maximum
                    else value > definition.maximum
                )
                if invalid:
                    operator = "<" if definition.exclusive_maximum else "<="
                    raise ModelValidationError(
                        f"{definition.path} must be {operator} {definition.maximum:g}"
                    )
            return

        x = getattr(prop, "x")
        y = getattr(prop, "y")
        try:
            x_matches = unit_dimension(x.unit) == unit_dimension(definition.x_unit)
            y_matches = unit_dimension(y.unit) == unit_dimension(definition.y_unit)
        except UnitConversionError as error:
            raise ModelValidationError(str(error)) from error
        if not x_matches:
            raise ModelValidationError(
                f"{definition.path} X axis requires a unit compatible with "
                f"{definition.x_unit}"
            )
        if not y_matches:
            raise ModelValidationError(
                f"{definition.path} Y axis requires a unit compatible with "
                f"{definition.y_unit}"
            )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagerConfigurationError(f"{label} must be an object")
    return value


def _check_keys(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ManagerConfigurationError(
            f"Unknown {label} field {sorted(unknown)[0]!r}"
        )


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ManagerConfigurationError(f"{label} must be true or false")
    return value


def _string(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManagerConfigurationError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _strings(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManagerConfigurationError(f"{label} must be an array of strings")
    return tuple(item.strip() for item in value if item.strip())


def _number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManagerConfigurationError(f"{label} must be a number or null")
    return float(value)


def load_property_catalog(path: str | Path) -> PropertyCatalog:
    """Load and validate a versioned property catalog JSON file."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManagerConfigurationError(
            f"Cannot read property catalog {source}: {error}"
        ) from error
    root = _object(data, "property catalog")
    _check_keys(
        root,
        {"schema", "schema_version", "categories", "subcategories", "properties"},
        "property catalog",
    )
    if root.get("schema") != "ems_property_catalog":
        raise ManagerConfigurationError(f"Invalid property catalog schema: {source}")
    if root.get("schema_version") != "1.0":
        raise ManagerConfigurationError(f"Unsupported property catalog version: {source}")

    category_rows = root.get("categories")
    definition_rows = root.get("properties")
    if not isinstance(category_rows, list) or not isinstance(definition_rows, list):
        raise ManagerConfigurationError(
            f"categories and properties must be arrays: {source}"
        )
    categories: list[PropertyCategory] = []
    for index, item in enumerate(category_rows):
        row = _object(item, f"categories[{index}]")
        _check_keys(row, {"key", "label", "color"}, f"categories[{index}]")
        categories.append(
            PropertyCategory(
                _string(row, "key", "category"),
                _string(row, "label", "category"),
                _string(row, "color", "category"),
            )
        )
    category_keys = {item.key for item in categories}

    subcategory_rows = root.get("subcategories", [])
    if not isinstance(subcategory_rows, list):
        raise ManagerConfigurationError(f"subcategories must be an array: {source}")
    subcategories: list[PropertySubcategory] = []
    for index, item in enumerate(subcategory_rows):
        row = _object(item, f"subcategories[{index}]")
        _check_keys(
            row,
            {"key", "label", "category", "color"},
            f"subcategories[{index}]",
        )
        subcategory = PropertySubcategory(
            _string(row, "key", "subcategory"),
            _string(row, "label", "subcategory"),
            _string(row, "category", "subcategory"),
            _string(row, "color", "subcategory"),
        )
        if subcategory.category not in category_keys:
            raise ManagerConfigurationError(
                f"Unknown category {subcategory.category!r} in {source}"
            )
        subcategories.append(subcategory)
    subcategory_keys = {(item.category, item.key) for item in subcategories}

    definitions: list[PropertyDefinition] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(definition_rows):
        row = _object(item, f"properties[{index}]")
        _check_keys(
            row,
            {
                "path", "label", "category", "subcategory", "kind", "unit",
                "description", "required_profiles", "x_name", "x_unit",
                "y_name", "y_unit", "aliases", "applicable_families",
                "minimum", "exclusive_minimum", "maximum", "exclusive_maximum",
                "note_recommended", "note_guidance",
            },
            f"properties[{index}]",
        )
        kind = _string(row, "kind", "property")
        if kind not in ("scalar", "curve"):
            raise ManagerConfigurationError(f"Unsupported property kind {kind!r}")
        category = _string(row, "category", "property")
        if category not in category_keys:
            raise ManagerConfigurationError(f"Unknown category {category!r} in {source}")
        subcategory = row.get("subcategory")
        if subcategory is not None and (
            not isinstance(subcategory, str)
            or (category, subcategory) not in subcategory_keys
        ):
            raise ManagerConfigurationError(
                f"Invalid subcategory for properties[{index}] in {source}"
            )
        path_value = _string(row, "path", "property")
        folded = path_value.casefold()
        if folded in seen_paths:
            raise ManagerConfigurationError(f"Duplicate property path {path_value!r}")
        seen_paths.add(folded)
        definition = PropertyDefinition(
            path=path_value,
            label=_string(row, "label", "property"),
            category=category,
            kind=kind,  # type: ignore[arg-type]
            unit=str(row.get("unit", "")),
            description=str(row.get("description", "")),
            required_profiles=_strings(row.get("required_profiles"), "required_profiles"),
            x_name=str(row.get("x_name", "X")),
            x_unit=str(row.get("x_unit", "1")),
            y_name=str(row.get("y_name", "Y")),
            y_unit=str(row.get("y_unit", "1")),
            aliases=_strings(row.get("aliases"), "aliases"),
            subcategory=subcategory,
            applicable_families=_strings(
                row.get("applicable_families"), "applicable_families"
            ),
            minimum=_number(row.get("minimum"), "minimum"),
            exclusive_minimum=_boolean(
                row.get("exclusive_minimum", False), "exclusive_minimum"
            ),
            maximum=_number(row.get("maximum"), "maximum"),
            exclusive_maximum=_boolean(
                row.get("exclusive_maximum", False), "exclusive_maximum"
            ),
            note_recommended=_boolean(
                row.get("note_recommended", False), "note_recommended"
            ),
            note_guidance=str(row.get("note_guidance", "")),
        )
        try:
            if kind == "scalar":
                unit_dimension(definition.unit)
            else:
                unit_dimension(definition.x_unit)
                unit_dimension(definition.y_unit)
        except UnitConversionError as error:
            raise ManagerConfigurationError(
                f"Invalid unit in property {definition.path}: {error}"
            ) from error
        definitions.append(definition)
    return PropertyCatalog(
        schema_version="1.0",
        categories=tuple(categories),
        subcategories=tuple(subcategories),
        definitions=tuple(definitions),
    )


DEFAULT_PROPERTY_CATALOG_PATH = (
    Path(__file__).with_name("catalog_defaults") / "property_definitions.v1.json"
)
DEFAULT_PROPERTY_CATALOG = load_property_catalog(DEFAULT_PROPERTY_CATALOG_PATH)
PROPERTY_CATEGORIES = DEFAULT_PROPERTY_CATALOG.categories
PROPERTY_SUBCATEGORIES = DEFAULT_PROPERTY_CATALOG.subcategories
PROPERTY_DEFINITIONS = DEFAULT_PROPERTY_CATALOG.definitions


def property_definition(path: str) -> PropertyDefinition | None:
    return DEFAULT_PROPERTY_CATALOG.property_definition(path)


def category_definition(key: str) -> PropertyCategory | None:
    return DEFAULT_PROPERTY_CATALOG.category_definition(key)


def property_applies_to_family(definition: PropertyDefinition, family: str) -> bool:
    return DEFAULT_PROPERTY_CATALOG.applies_to_family(definition, family)


def validate_catalog_property(path: str, prop: object) -> None:
    DEFAULT_PROPERTY_CATALOG.validate_property(path, prop)
