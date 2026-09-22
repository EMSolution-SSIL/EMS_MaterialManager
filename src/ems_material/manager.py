"""Application facade for user material lifecycle operations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable
from uuid import uuid4

from .legacy import LegacyImportResult, load_legacy_material
from .magnetic import MagneticCharacteristic, resolve_magnetic_characteristic
from .material_types import load_catalog_bundle
from .model import (
    Material,
    MaterialIdentity,
    MaterialProperty,
    Provenance,
    VersionMetadata,
)
from .repository import (
    ConfiguredMaterialRepository,
    JsonMaterialRepository,
    MaterialRepository,
)
from .property_catalog import PropertyCatalog
from .serialization import load_material
from .validation import MaterialValidationResult, validate_material


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generated_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_") or "material"
    return f"user:{slug}_{uuid4().hex[:8]}"


def _validate_catalog_properties(material: Material, catalog: PropertyCatalog) -> None:
    for domain, properties in material.properties.items():
        for name, prop in properties.items():
            catalog.validate_property(f"{domain}.{name}", prop)


class MaterialManager:
    """Stable public API over a material repository."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        repository: MaterialRepository | None = None,
        allow_reference_updates: bool = False,
    ) -> None:
        if (root is None) == (repository is None):
            raise ValueError("Provide exactly one of root or repository")
        catalog_root = (
            Path(root)
            if root is not None
            else getattr(repository, "root", None)
        )
        self.property_catalog, self.material_type_catalog = load_catalog_bundle(
            catalog_root
        )
        if repository is not None:
            if allow_reference_updates:
                raise ValueError(
                    "Configure allow_reference_updates on the supplied repository"
                )
            self.repository = repository
            self.admin_reference_updates = bool(
                getattr(repository, "allow_reference_updates", False)
            )
        else:
            root_path = Path(root)  # type: ignore[arg-type]
            self.admin_reference_updates = allow_reference_updates
            if (root_path / ConfiguredMaterialRepository.root_config_name).is_file():
                self.repository = ConfiguredMaterialRepository(
                    root_path,
                    allow_reference_updates=allow_reference_updates,
                )
            else:
                self.repository = JsonMaterialRepository(
                    root_path,
                    allow_reference_updates=allow_reference_updates,
                )

    def list(self) -> tuple[Material, ...]:
        return self.repository.list()

    def get(self, material_id: str) -> Material:
        return self.repository.get(material_id)

    def search(
        self,
        *,
        family: str | None = None,
        text: str | None = None,
        manufacturer: str | None = None,
        tags: Iterable[str] = (),
    ) -> tuple[Material, ...]:
        return self.repository.search(
            family=family,
            text=text,
            manufacturer=manufacturer,
            tags=tuple(tags),
        )

    def create(
        self,
        *,
        name: str,
        family: str,
        author: str,
        material_id: str | None = None,
        material_version: str = "1.0.0",
        updated_at: str | None = None,
        change_note: str = "Created user material",
        manufacturer: str | None = None,
        grade: str | None = None,
        description: str | None = None,
        aliases: Iterable[str] = (),
        tags: Iterable[str] = (),
        properties: dict[str, dict[str, MaterialProperty]] | None = None,
        provenance: Provenance | None = None,
        parent_ref: str | None = None,
    ) -> Material:
        family = self.material_type_catalog.resolve_family(family)
        material = Material(
            material_id=material_id or _generated_id(name),
            material_version=material_version,
            identity=MaterialIdentity(
                name=name,
                family=family,
                manufacturer=manufacturer,
                grade=grade,
                description=description,
                aliases=tuple(aliases),
                tags=tuple(tags),
            ),
            properties=properties or {},
            provenance=provenance or Provenance("USER_INPUT"),
            version_metadata=VersionMetadata(
                author=author,
                updated_at=updated_at or _timestamp(),
                change_note=change_note,
            ),
            parent_ref=parent_ref,
        )
        _validate_catalog_properties(material, self.property_catalog)
        return self.repository.create(material)

    def create_from_template(
        self,
        *,
        name: str,
        family: str,
        author: str,
        **metadata: object,
    ) -> Material:
        """Create a sparse user material using explicit template defaults only."""

        canonical_family = self.material_type_catalog.resolve_family(family)
        template = self.material_type_catalog.template_for(canonical_family)
        properties = template.default_properties() if template else {}
        return self.create(
            name=name,
            family=canonical_family,
            author=author,
            properties=properties,
            **metadata,
        )

    def update(
        self,
        material: Material,
        *,
        expected_version: str | None = None,
    ) -> Material:
        _validate_catalog_properties(material, self.property_catalog)
        return self.repository.update(material, expected_version=expected_version)

    def duplicate(
        self,
        source_id: str,
        *,
        new_name: str,
        author: str,
        new_material_id: str | None = None,
        updated_at: str | None = None,
        change_note: str = "Duplicated material",
    ) -> Material:
        return self.repository.duplicate(
            source_id,
            new_material_id=new_material_id or _generated_id(new_name),
            new_name=new_name,
            author=author,
            updated_at=updated_at or _timestamp(),
            change_note=change_note,
        )

    def delete(self, material_id: str) -> None:
        self.repository.delete(material_id)

    def get_property(self, material_id: str, path: str) -> MaterialProperty:
        return self.get(material_id).get_property(path)

    def get_magnetic_characteristic(
        self, material_id: str
    ) -> MagneticCharacteristic:
        """Return the B-H curve, or relative permeability when the curve is absent."""

        return resolve_magnetic_characteristic(self.get(material_id))

    def source_for(self, material_id: str) -> str | None:
        return self.repository.source_for(material_id)

    def is_writable(self, material_id: str) -> bool:
        return self.repository.is_writable(material_id)

    def is_deletable(self, material_id: str) -> bool:
        return self.repository.is_deletable(material_id)

    def list_sources(self) -> tuple[str, ...]:
        return self.repository.list_sources()

    def validate(self, material_id: str, profile: str) -> MaterialValidationResult:
        return validate_material(self.get(material_id), profile)

    def import_json(self, source: str | Path) -> Material:
        material = load_material(source)
        _validate_catalog_properties(material, self.property_catalog)
        return self.repository.create(material)

    def export_json(self, material_id: str, destination: str | Path) -> None:
        self.repository.export_json(material_id, destination)

    def import_legacy_json(
        self,
        source: str | Path,
        *,
        material_id: str,
        family: str,
        author: str,
        updated_at: str | None = None,
        source_type: str = "UNKNOWN",
    ) -> LegacyImportResult:
        result = load_legacy_material(
            source,
            material_id=material_id,
            family=family,
            author=author,
            updated_at=updated_at,
            source_type=source_type,
        )
        _validate_catalog_properties(result.material, self.property_catalog)
        self.repository.create(result.material)
        return result
