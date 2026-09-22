"""Material type registry and sparse creation-template support."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from .errors import ManagerConfigurationError
from .model import CurveProperty, MaterialProperty, ScalarProperty
from .property_catalog import (
    DEFAULT_PROPERTY_CATALOG,
    DEFAULT_PROPERTY_CATALOG_PATH,
    PropertyCatalog,
    load_property_catalog,
)


RequirementLevel = Literal["required", "recommended", "optional"]


@dataclass(frozen=True, slots=True)
class TemplateProperty:
    path: str
    requirement: RequirementLevel = "optional"
    profiles: tuple[str, ...] = ()
    default: dict[str, Any] | None = None

    def default_property(self) -> MaterialProperty | None:
        if self.default is None:
            return None
        kind = self.default.get("type")
        if kind == "scalar":
            return ScalarProperty.from_dict(self.default)
        if kind == "curve":
            return CurveProperty.from_dict(self.default)
        raise ManagerConfigurationError(
            f"Template default for {self.path} has unsupported type {kind!r}"
        )


@dataclass(frozen=True, slots=True)
class MaterialTemplate:
    family: str
    description: str
    properties: tuple[TemplateProperty, ...]

    def property(self, path: str) -> TemplateProperty | None:
        folded = path.casefold()
        return next((item for item in self.properties if item.path.casefold() == folded), None)

    def default_properties(self) -> dict[str, dict[str, MaterialProperty]]:
        result: dict[str, dict[str, MaterialProperty]] = {}
        for item in self.properties:
            value = item.default_property()
            if value is None:
                continue
            domain, name = item.path.split(".", 1)
            result.setdefault(domain, {})[name] = value
        return result


@dataclass(frozen=True, slots=True)
class MaterialTypeDefinition:
    family: str
    label: str
    description: str
    aliases: tuple[str, ...]
    template_file: str


@dataclass(frozen=True, slots=True)
class MaterialTypeCatalog:
    schema_version: str
    types: tuple[MaterialTypeDefinition, ...]
    templates: tuple[MaterialTemplate, ...]
    allow_custom_family: bool = True

    def resolve_family(self, family: str) -> str:
        requested = family.strip().casefold()
        for item in self.types:
            if requested in {item.family.casefold(), *(alias.casefold() for alias in item.aliases)}:
                return item.family
        return family.strip()

    def material_type(self, family: str) -> MaterialTypeDefinition | None:
        canonical = self.resolve_family(family).casefold()
        return next((item for item in self.types if item.family.casefold() == canonical), None)

    def template_for(self, family: str) -> MaterialTemplate | None:
        material_type = self.material_type(family)
        if material_type is None:
            return None
        return next(
            (item for item in self.templates if item.family == material_type.family),
            None,
        )

    def template_property(self, family: str, path: str) -> TemplateProperty | None:
        template = self.template_for(family)
        return template.property(path) if template else None


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManagerConfigurationError(f"Cannot read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManagerConfigurationError(f"{label} must be a JSON object: {path}")
    return value


def _required_string(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManagerConfigurationError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _check_keys(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ManagerConfigurationError(
            f"Unknown {label} field {sorted(unknown)[0]!r}"
        )


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManagerConfigurationError(f"{label} must be an array of strings")
    return tuple(item.strip() for item in value if item.strip())


def _load_template(
    path: Path,
    *,
    expected_family: str,
    property_catalog: PropertyCatalog,
) -> MaterialTemplate:
    data = _read_json(path, "material template")
    _check_keys(
        data,
        {"schema", "schema_version", "family", "description", "properties"},
        "material template",
    )
    if data.get("schema") != "ems_material_template" or data.get("schema_version") != "1.0":
        raise ManagerConfigurationError(f"Unsupported material template schema: {path}")
    family = _required_string(data, "family", "template")
    if family != expected_family:
        raise ManagerConfigurationError(
            f"Template family {family!r} does not match {expected_family!r}: {path}"
        )
    rows = data.get("properties")
    if not isinstance(rows, list):
        raise ManagerConfigurationError(f"template.properties must be an array: {path}")
    properties: list[TemplateProperty] = []
    seen: set[str] = set()
    for index, value in enumerate(rows):
        if not isinstance(value, dict):
            raise ManagerConfigurationError(f"properties[{index}] must be an object: {path}")
        _check_keys(
            value,
            {"path", "requirement", "profiles", "default"},
            f"template properties[{index}]",
        )
        property_path = _required_string(value, "path", "template property")
        definition = property_catalog.property_definition(property_path)
        if definition is None:
            raise ManagerConfigurationError(
                f"Unknown property {property_path!r} in template {path}"
            )
        property_path = definition.path
        folded = property_path.casefold()
        if folded in seen:
            raise ManagerConfigurationError(f"Duplicate property {property_path!r}: {path}")
        seen.add(folded)
        requirement = value.get("requirement", "optional")
        if requirement not in ("required", "recommended", "optional"):
            raise ManagerConfigurationError(
                f"Invalid requirement for {property_path!r}: {requirement!r}"
            )
        default = value.get("default")
        if default is not None and not isinstance(default, dict):
            raise ManagerConfigurationError(
                f"Default for {property_path!r} must be an object or null"
            )
        item = TemplateProperty(
            path=property_path,
            requirement=requirement,
            profiles=_string_array(value.get("profiles"), "profiles"),
            default=default,
        )
        default_property = item.default_property()
        if default_property is not None:
            property_catalog.validate_property(property_path, default_property)
        properties.append(item)
    return MaterialTemplate(
        family=family,
        description=str(data.get("description", "")),
        properties=tuple(properties),
    )


def load_material_type_catalog(
    types_path: str | Path,
    templates_directory: str | Path,
    *,
    property_catalog: PropertyCatalog = DEFAULT_PROPERTY_CATALOG,
) -> MaterialTypeCatalog:
    """Load material type choices and validate every referenced template."""

    source = Path(types_path)
    templates_root = Path(templates_directory)
    data = _read_json(source, "material type catalog")
    _check_keys(
        data,
        {"schema", "schema_version", "allow_custom_family", "types"},
        "material type catalog",
    )
    if data.get("schema") != "ems_material_type_catalog" or data.get("schema_version") != "1.0":
        raise ManagerConfigurationError(f"Unsupported material type catalog: {source}")
    rows = data.get("types")
    if not isinstance(rows, list):
        raise ManagerConfigurationError(f"types must be an array: {source}")
    types: list[MaterialTypeDefinition] = []
    templates: list[MaterialTemplate] = []
    names: set[str] = set()
    for index, value in enumerate(rows):
        if not isinstance(value, dict):
            raise ManagerConfigurationError(f"types[{index}] must be an object: {source}")
        _check_keys(
            value,
            {"id", "label", "description", "aliases", "template"},
            f"types[{index}]",
        )
        family = _required_string(value, "id", "material type")
        aliases = _string_array(value.get("aliases"), "aliases")
        all_names = {family.casefold(), *(alias.casefold() for alias in aliases)}
        duplicate = all_names & names
        if duplicate:
            raise ManagerConfigurationError(
                f"Duplicate material type name or alias {sorted(duplicate)[0]!r}"
            )
        names.update(all_names)
        template_file = _required_string(value, "template", "material type")
        candidate = Path(template_file)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ManagerConfigurationError(f"Template path must be relative: {template_file!r}")
        template_path = (templates_root / candidate).resolve()
        try:
            template_path.relative_to(templates_root.resolve())
        except ValueError as error:
            raise ManagerConfigurationError(
                f"Template escapes its configured directory: {template_file!r}"
            ) from error
        item = MaterialTypeDefinition(
            family=family,
            label=_required_string(value, "label", "material type"),
            description=str(value.get("description", "")),
            aliases=aliases,
            template_file=template_file,
        )
        types.append(item)
        templates.append(
            _load_template(
                template_path,
                expected_family=family,
                property_catalog=property_catalog,
            )
        )
    allow_custom = data.get("allow_custom_family", True)
    if not isinstance(allow_custom, bool):
        raise ManagerConfigurationError("allow_custom_family must be true or false")
    return MaterialTypeCatalog(
        schema_version="1.0",
        types=tuple(types),
        templates=tuple(templates),
        allow_custom_family=allow_custom,
    )


DEFAULT_CATALOG_DIRECTORY = Path(__file__).with_name("catalog_defaults")
DEFAULT_MATERIAL_TYPE_CATALOG_PATH = DEFAULT_CATALOG_DIRECTORY / "material_types.v1.json"
DEFAULT_TEMPLATE_DIRECTORY = DEFAULT_CATALOG_DIRECTORY / "templates"
DEFAULT_MATERIAL_TYPE_CATALOG = load_material_type_catalog(
    DEFAULT_MATERIAL_TYPE_CATALOG_PATH,
    DEFAULT_TEMPLATE_DIRECTORY,
)


def _inside(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ManagerConfigurationError(f"{label} must be relative: {relative!r}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ManagerConfigurationError(f"{label} escapes the library root: {relative!r}") from error
    return resolved


def load_catalog_bundle(
    library_root: str | Path | None,
) -> tuple[PropertyCatalog, MaterialTypeCatalog]:
    """Load a library-specific catalog, falling back to packaged defaults."""

    if library_root is None:
        return DEFAULT_PROPERTY_CATALOG, DEFAULT_MATERIAL_TYPE_CATALOG
    root = Path(library_root)
    config_path = root / "manager.config.json"
    if not config_path.is_file():
        return DEFAULT_PROPERTY_CATALOG, DEFAULT_MATERIAL_TYPE_CATALOG
    config = _read_json(config_path, "library config")
    catalog_config = config.get("catalog")
    if catalog_config is None:
        return DEFAULT_PROPERTY_CATALOG, DEFAULT_MATERIAL_TYPE_CATALOG
    if not isinstance(catalog_config, dict):
        raise ManagerConfigurationError(f"catalog must be an object: {config_path}")
    allowed = {"properties", "material_types", "templates"}
    unknown = set(catalog_config) - allowed
    if unknown:
        raise ManagerConfigurationError(
            f"Unknown catalog option {sorted(unknown)[0]!r}: {config_path}"
        )
    property_path = (
        _inside(root, str(catalog_config["properties"]), "Property catalog path")
        if "properties" in catalog_config
        else DEFAULT_PROPERTY_CATALOG_PATH
    )
    types_path = (
        _inside(root, str(catalog_config["material_types"]), "Material type path")
        if "material_types" in catalog_config
        else DEFAULT_MATERIAL_TYPE_CATALOG_PATH
    )
    templates_path = (
        _inside(root, str(catalog_config["templates"]), "Template directory")
        if "templates" in catalog_config
        else DEFAULT_TEMPLATE_DIRECTORY
    )
    properties = load_property_catalog(property_path)
    types = load_material_type_catalog(
        types_path,
        templates_path,
        property_catalog=properties,
    )
    return properties, types
