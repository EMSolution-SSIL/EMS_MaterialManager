"""Product-independent domain models for Canonical Material JSON v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from math import isfinite
from numbers import Real
from typing import TYPE_CHECKING, Any, TypeAlias

from .errors import ModelValidationError, PropertyNotFoundError
from .units import convert_value, normalize_unit

if TYPE_CHECKING:
    from .property_catalog import PropertyCatalog


_MATERIAL_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)+$"
)
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ModelValidationError(f"{label} must be a real number")
    number = float(value)
    if not isfinite(number):
        raise ModelValidationError(f"{label} must be finite")
    return number


def _optional_note(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelValidationError("Property note must be a string or null")
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class ConditionValue:
    """A numeric-with-unit or enumerated condition attached to a property."""

    value: float | str
    unit: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, str):
            value = self.value.strip()
            if not value:
                raise ModelValidationError("Text condition value must not be empty")
            if self.unit is not None:
                raise ModelValidationError("Text condition values must not have a unit")
            object.__setattr__(self, "value", value)
            return
        object.__setattr__(self, "value", _finite_number(self.value, "Condition value"))
        if self.unit is None:
            raise ModelValidationError("Numeric condition values require a unit")
        object.__setattr__(self, "unit", normalize_unit(self.unit))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConditionValue:
        return cls(value=data["value"], unit=data.get("unit"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"value": self.value}
        if self.unit is not None:
            result["unit"] = self.unit
        return result


@dataclass(frozen=True, slots=True)
class ValidityRange:
    """A source-declared numerical range in which a property is applicable."""

    minimum: float
    maximum: float
    unit: str

    def __post_init__(self) -> None:
        minimum = _finite_number(self.minimum, "Validity range minimum")
        maximum = _finite_number(self.maximum, "Validity range maximum")
        if minimum > maximum:
            raise ModelValidationError("Validity range minimum must not exceed maximum")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)
        object.__setattr__(self, "unit", normalize_unit(self.unit))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidityRange:
        return cls(minimum=data["minimum"], maximum=data["maximum"], unit=data["unit"])

    def to_dict(self) -> dict[str, Any]:
        return {"minimum": self.minimum, "maximum": self.maximum, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class PropertySource:
    """Traceable source metadata for an individual canonical property."""

    dataset_id: str | None = None
    manifest_ref: str | None = None
    raw_path: str | None = None
    sha256: str | None = None
    locator: str | None = None
    doi: str | None = None
    source_url: str | None = None
    license: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    original_unit: str | None = None
    conversion_note: str | None = None
    derivation_note: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "dataset_id",
            "manifest_ref",
            "raw_path",
            "locator",
            "doi",
            "source_url",
            "license",
            "license_url",
            "attribution",
            "original_unit",
            "conversion_note",
            "derivation_note",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ModelValidationError(
                    f"Property source {name} must be a non-empty string or null"
                )
            if isinstance(value, str):
                object.__setattr__(self, name, value.strip())
        if self.sha256 is not None:
            digest = self.sha256.casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ModelValidationError(
                    "Property source sha256 must be a SHA-256 hexadecimal digest"
                )
            object.__setattr__(self, "sha256", digest)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertySource:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("dataset_id", self.dataset_id),
                ("manifest_ref", self.manifest_ref),
                ("raw_path", self.raw_path),
                ("sha256", self.sha256),
                ("locator", self.locator),
                ("doi", self.doi),
                ("source_url", self.source_url),
                ("license", self.license),
                ("license_url", self.license_url),
                ("attribution", self.attribution),
                ("original_unit", self.original_unit),
                ("conversion_note", self.conversion_note),
                ("derivation_note", self.derivation_note),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class ScalarProperty:
    value: float
    unit: str
    conditions: dict[str, ConditionValue] = field(default_factory=dict)
    note: str | None = None
    source: PropertySource | None = None
    valid_ranges: dict[str, ValidityRange] = field(default_factory=dict)
    type: str = field(default="scalar", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _finite_number(self.value, "Scalar value"))
        object.__setattr__(self, "unit", normalize_unit(self.unit))
        normalized = {
            name: value
            if isinstance(value, ConditionValue)
            else ConditionValue.from_dict(value)
            for name, value in self.conditions.items()
        }
        object.__setattr__(self, "conditions", normalized)
        object.__setattr__(self, "note", _optional_note(self.note))
        source = self.source
        if source is not None and not isinstance(source, PropertySource):
            source = PropertySource.from_dict(source)
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "valid_ranges",
            {
                name: value
                if isinstance(value, ValidityRange)
                else ValidityRange.from_dict(value)
                for name, value in self.valid_ranges.items()
            },
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScalarProperty:
        return cls(
            value=data["value"],
            unit=data["unit"],
            conditions={
                name: ConditionValue.from_dict(value)
                for name, value in data.get("conditions", {}).items()
            },
            note=data.get("note"),
            source=(
                PropertySource.from_dict(data["source"]) if data.get("source") else None
            ),
            valid_ranges={
                name: ValidityRange.from_dict(value)
                for name, value in data.get("valid_ranges", {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "value": self.value,
            "unit": self.unit,
            "note": self.note,
        }
        if self.conditions:
            result["conditions"] = {
                name: value.to_dict() for name, value in self.conditions.items()
            }
        if self.source is not None:
            result["source"] = self.source.to_dict()
        if self.valid_ranges:
            result["valid_ranges"] = {
                name: value.to_dict() for name, value in self.valid_ranges.items()
            }
        return result

    def to_unit(self, unit: str) -> float:
        return convert_value(self.value, self.unit, unit)


@dataclass(frozen=True, slots=True)
class Axis:
    name: str
    unit: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ModelValidationError("Axis name must not be empty")
        object.__setattr__(self, "unit", normalize_unit(self.unit))
        object.__setattr__(
            self,
            "values",
            tuple(
                _finite_number(value, f"Axis {self.name} value")
                for value in self.values
            ),
        )
        if len(self.values) < 2:
            raise ModelValidationError("A curve axis requires at least two values")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Axis:
        return cls(name=data["name"], unit=data["unit"], values=tuple(data["values"]))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "unit": self.unit, "values": list(self.values)}

    def to_unit(self, unit: str) -> tuple[float, ...]:
        return tuple(convert_value(value, self.unit, unit) for value in self.values)


@dataclass(frozen=True, slots=True)
class CurveProperty:
    x: Axis
    y: Axis
    display: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    conditions: dict[str, ConditionValue] = field(default_factory=dict)
    source: PropertySource | None = None
    valid_ranges: dict[str, ValidityRange] = field(default_factory=dict)
    type: str = field(default="curve", init=False)

    def __post_init__(self) -> None:
        if len(self.x.values) != len(self.y.values):
            raise ModelValidationError("Curve x and y axes must have the same length")
        if any(left >= right for left, right in zip(self.x.values, self.x.values[1:])):
            raise ModelValidationError("Curve x values must be strictly increasing")
        allowed_scales = {"linear", "log"}
        for key, value in self.display.items():
            if key not in {"x_scale", "y_scale"} or value not in allowed_scales:
                raise ModelValidationError(
                    f"Unsupported curve display option: {key}={value}"
                )
        object.__setattr__(self, "display", dict(self.display))
        object.__setattr__(self, "note", _optional_note(self.note))
        object.__setattr__(
            self,
            "conditions",
            {
                name: value
                if isinstance(value, ConditionValue)
                else ConditionValue.from_dict(value)
                for name, value in self.conditions.items()
            },
        )
        source = self.source
        if source is not None and not isinstance(source, PropertySource):
            source = PropertySource.from_dict(source)
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "valid_ranges",
            {
                name: value
                if isinstance(value, ValidityRange)
                else ValidityRange.from_dict(value)
                for name, value in self.valid_ranges.items()
            },
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurveProperty:
        return cls(
            x=Axis.from_dict(data["x"]),
            y=Axis.from_dict(data["y"]),
            display=dict(data.get("display", {})),
            note=data.get("note"),
            conditions={
                name: ConditionValue.from_dict(value)
                for name, value in data.get("conditions", {}).items()
            },
            source=(
                PropertySource.from_dict(data["source"]) if data.get("source") else None
            ),
            valid_ranges={
                name: ValidityRange.from_dict(value)
                for name, value in data.get("valid_ranges", {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "x": self.x.to_dict(),
            "y": self.y.to_dict(),
            "note": self.note,
        }
        if self.display:
            result["display"] = dict(self.display)
        if self.conditions:
            result["conditions"] = {
                name: value.to_dict() for name, value in self.conditions.items()
            }
        if self.source is not None:
            result["source"] = self.source.to_dict()
        if self.valid_ranges:
            result["valid_ranges"] = {
                name: value.to_dict() for name, value in self.valid_ranges.items()
            }
        return result


MaterialProperty: TypeAlias = ScalarProperty | CurveProperty


@dataclass(frozen=True, slots=True)
class MaterialIdentity:
    name: str
    family: str
    manufacturer: str | None = None
    grade: str | None = None
    description: str | None = None
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ModelValidationError("Material name must not be empty")
        if not self.family:
            raise ModelValidationError("Material family must not be empty")
        if len(set(self.aliases)) != len(self.aliases):
            raise ModelValidationError("Material aliases must be unique")
        if len(set(self.tags)) != len(self.tags):
            raise ModelValidationError("Material tags must be unique")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialIdentity:
        return cls(
            name=data["name"],
            family=data["family"],
            manufacturer=data.get("manufacturer"),
            grade=data.get("grade"),
            description=data.get("description"),
            aliases=tuple(data.get("aliases", ())),
            tags=tuple(data.get("tags", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "manufacturer": self.manufacturer,
            "grade": self.grade,
            "description": self.description,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class Provenance:
    source_type: str
    reference: str | None = None
    date: str | None = None
    notes: str | None = None
    license: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    source_manifest: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Provenance:
        return cls(
            source_type=data["source_type"],
            reference=data.get("reference"),
            date=data.get("date"),
            notes=data.get("notes"),
            license=data.get("license"),
            license_url=data.get("license_url"),
            attribution=data.get("attribution"),
            source_manifest=data.get("source_manifest"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_type": self.source_type,
            "reference": self.reference,
            "date": self.date,
            "notes": self.notes,
        }
        for name, value in (
            ("license", self.license),
            ("license_url", self.license_url),
            ("attribution", self.attribution),
            ("source_manifest", self.source_manifest),
        ):
            if value is not None:
                result[name] = value
        return result


@dataclass(frozen=True, slots=True)
class VersionMetadata:
    author: str
    updated_at: str
    change_note: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionMetadata:
        return cls(
            author=data["author"],
            updated_at=data["updated_at"],
            change_note=data["change_note"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "updated_at": self.updated_at,
            "change_note": self.change_note,
        }


@dataclass(frozen=True, slots=True)
class Material:
    material_id: str
    material_version: str
    identity: MaterialIdentity
    properties: dict[str, dict[str, MaterialProperty]]
    provenance: Provenance
    version_metadata: VersionMetadata
    variant_id: str | None = None
    parent_ref: str | None = None
    schema: str = field(default="ems_material", init=False)
    schema_version: str = field(default="1.0", init=False)

    def __post_init__(self) -> None:
        if not _MATERIAL_ID_RE.fullmatch(self.material_id):
            raise ModelValidationError(f"Invalid material_id: {self.material_id!r}")
        if not _VERSION_RE.fullmatch(self.material_version):
            raise ModelValidationError(
                f"Invalid material_version: {self.material_version!r}"
            )
        normalized: dict[str, dict[str, MaterialProperty]] = {}
        for domain, values in self.properties.items():
            if not domain or not isinstance(values, dict):
                raise ModelValidationError(
                    "Property domains must be non-empty mappings"
                )
            normalized[domain] = dict(values)
        object.__setattr__(self, "properties", normalized)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Material:
        properties: dict[str, dict[str, MaterialProperty]] = {}
        for domain, values in data["properties"].items():
            properties[domain] = {}
            for name, value in values.items():
                if value["type"] == "scalar":
                    prop: MaterialProperty = ScalarProperty.from_dict(value)
                elif value["type"] == "curve":
                    prop = CurveProperty.from_dict(value)
                else:  # Defensive; JSON Schema rejects this before model creation.
                    raise ModelValidationError(
                        f"Unsupported property type: {value['type']!r}"
                    )
                properties[domain][name] = prop
        return cls(
            material_id=data["material_id"],
            material_version=data["material_version"],
            identity=MaterialIdentity.from_dict(data["identity"]),
            properties=properties,
            provenance=Provenance.from_dict(data["provenance"]),
            version_metadata=VersionMetadata.from_dict(data["version_metadata"]),
            variant_id=data.get("variant_id"),
            parent_ref=data.get("parent_ref"),
        )

    def get_property(self, path: str) -> MaterialProperty:
        """Return a property by its `<domain>.<property_name>` path."""

        try:
            domain, name = path.split(".", 1)
            return self.properties[domain][name]
        except (ValueError, KeyError) as error:
            raise PropertyNotFoundError(
                f"Material {self.material_id!r} does not define property {path!r}"
            ) from error

    def has_property(self, path: str) -> bool:
        """Return whether a `<domain>.<property_name>` path exists."""

        try:
            self.get_property(path)
        except PropertyNotFoundError:
            return False
        return True

    def validate(self, profile: str) -> Any:
        """Validate this record against a named use-case profile."""

        # Local import avoids a model/validation import cycle while retaining
        # the ergonomic API specified by the PoC plan.
        from .validation import validate_material

        return validate_material(self, profile)

    def with_property(
        self,
        path: str,
        value: MaterialProperty,
        *,
        catalog: PropertyCatalog | None = None,
    ) -> Material:
        """Return a copy with one property inserted or replaced."""

        if catalog is None:
            from .property_catalog import validate_catalog_property

            validate_catalog_property(path, value)
        else:
            catalog.validate_property(path, value)

        try:
            domain, name = path.split(".", 1)
        except ValueError as error:
            raise ModelValidationError(
                "Property path must use '<domain>.<property_name>'"
            ) from error
        if not domain or not name:
            raise ModelValidationError(
                "Property path must use '<domain>.<property_name>'"
            )
        properties = {
            existing_domain: dict(existing_values)
            for existing_domain, existing_values in self.properties.items()
        }
        properties.setdefault(domain, {})[name] = value
        return replace(self, properties=properties)

    def without_property(self, path: str) -> Material:
        """Return a copy without a property; missing paths are rejected."""

        try:
            domain, name = path.split(".", 1)
            properties = {
                existing_domain: dict(existing_values)
                for existing_domain, existing_values in self.properties.items()
            }
            del properties[domain][name]
            if not properties[domain]:
                del properties[domain]
        except (ValueError, KeyError) as error:
            raise PropertyNotFoundError(
                f"Material {self.material_id!r} does not define property {path!r}"
            ) from error
        return replace(self, properties=properties)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "material_id": self.material_id,
            "material_version": self.material_version,
            "identity": self.identity.to_dict(),
            "properties": {
                domain: {name: value.to_dict() for name, value in values.items()}
                for domain, values in self.properties.items()
            },
            "provenance": self.provenance.to_dict(),
            "version_metadata": self.version_metadata.to_dict(),
        }
        if self.variant_id is not None:
            result["variant_id"] = self.variant_id
        if self.parent_ref is not None:
            result["parent_ref"] = self.parent_ref
        return result

    @property
    def id(self) -> str:
        """Short alias used by the conceptual API in the implementation plan."""

        return self.material_id

    @property
    def name(self) -> str:
        return self.identity.name

    @property
    def family(self) -> str:
        return self.identity.family

    @property
    def version(self) -> str:
        return self.material_version
