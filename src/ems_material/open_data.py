"""Reproducible, review-gated imports for openly licensed material datasets.

The module deliberately reads only locally stored source files.  Downloading,
license confirmation, and promotion to ``materials/`` are separate human
review steps.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import OpenDataImportError
from .model import (
    Axis,
    ConditionValue,
    CurveProperty,
    Material,
    MaterialIdentity,
    PropertySource,
    Provenance,
    VersionMetadata,
)

_LICENSE_STATUSES = {
    "UNVERIFIED",
    "VERIFIED_RECORD_VERSION",
    "REVIEW_REQUIRED",
    "REJECTED",
}


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenDataImportError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenDataImportError(f"{label} must be a non-empty string")
    return value.strip()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, json.JSONDecodeError) as error:
        raise OpenDataImportError(f"Cannot read {label} {path}: {error}") from error


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a local immutable raw file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ManifestFile:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceManifest:
    dataset_id: str
    repository: str
    title: str
    source_url: str
    record_version: str
    license: str
    license_url: str
    license_status: str
    attribution: str
    files: tuple[ManifestFile, ...]
    doi: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> SourceManifest:
        document = _load_json(Path(path), "source manifest")
        if document.get("schema") != "ems_open_material_source_manifest":
            raise OpenDataImportError("Invalid source manifest schema")
        if document.get("schema_version") != "1.0":
            raise OpenDataImportError("Unsupported source manifest version")
        status = _string(document.get("license_status"), "license_status")
        if status not in _LICENSE_STATUSES:
            raise OpenDataImportError(f"Unsupported license_status {status!r}")
        rows = document.get("files")
        if not isinstance(rows, list) or not rows:
            raise OpenDataImportError("source manifest files must be a non-empty array")
        files: list[ManifestFile] = []
        for index, row in enumerate(rows):
            item = _object(row, f"files[{index}]")
            raw_path = _string(item.get("path"), f"files[{index}].path")
            digest = _string(item.get("sha256"), f"files[{index}].sha256").casefold()
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise OpenDataImportError(
                    f"files[{index}].sha256 must be a SHA-256 digest"
                )
            files.append(ManifestFile(raw_path, digest))
        return cls(
            dataset_id=_string(document.get("dataset_id"), "dataset_id"),
            repository=_string(document.get("repository"), "repository"),
            title=_string(document.get("title"), "title"),
            source_url=_string(document.get("source_url"), "source_url"),
            record_version=_string(document.get("record_version"), "record_version"),
            license=_string(document.get("license"), "license"),
            license_url=_string(document.get("license_url"), "license_url"),
            license_status=status,
            attribution=_string(document.get("attribution"), "attribution"),
            files=tuple(files),
            doi=(str(document["doi"]).strip() if document.get("doi") else None),
        )

    def verify_files(self, workspace: str | Path) -> None:
        root = Path(workspace)
        for item in self.files:
            source = root / item.path
            if not source.is_file():
                raise OpenDataImportError(f"Manifest raw file is missing: {item.path}")
            actual = sha256_file(source)
            if actual != item.sha256:
                raise OpenDataImportError(
                    f"SHA-256 mismatch for {item.path}: expected {item.sha256}, got {actual}"
                )

    def file_sha256(self, raw_path: str) -> str:
        for item in self.files:
            if item.path == raw_path:
                return item.sha256
        raise OpenDataImportError(f"Raw file is not declared in manifest: {raw_path}")


@dataclass(frozen=True, slots=True)
class CandidateCatalog:
    records: tuple[Mapping[str, Any], ...]

    @classmethod
    def load(cls, path: str | Path) -> CandidateCatalog:
        document = _load_json(Path(path), "candidate catalog")
        if document.get("schema") != "ems_open_material_dataset_candidate_catalog":
            raise OpenDataImportError("Invalid candidate catalog schema")
        if document.get("schema_version") != "1.0":
            raise OpenDataImportError("Unsupported candidate catalog version")
        rows = document.get("datasets")
        if not isinstance(rows, list):
            raise OpenDataImportError("candidate catalog datasets must be an array")
        ids: set[str] = set()
        records: list[Mapping[str, Any]] = []
        for index, row in enumerate(rows):
            item = _object(row, f"datasets[{index}]")
            dataset_id = _string(item.get("id"), f"datasets[{index}].id")
            if dataset_id in ids:
                raise OpenDataImportError(
                    f"Duplicate candidate dataset ID: {dataset_id}"
                )
            ids.add(dataset_id)
            _string(item.get("title"), f"datasets[{index}].title")
            _string(item.get("license"), f"datasets[{index}].license")
            records.append(dict(item))
        return cls(tuple(records))


@dataclass(frozen=True, slots=True)
class OpenDataImportResult:
    material: Material
    report: Mapping[str, Any]


def _conditions(data: object) -> dict[str, ConditionValue]:
    if data is None:
        return {}
    values = _object(data, "mapping conditions")
    result: dict[str, ConditionValue] = {}
    for name, value in values.items():
        if isinstance(value, str):
            result[name] = ConditionValue(value)
        else:
            row = _object(value, f"condition {name}")
            result[name] = ConditionValue.from_dict(row)
    return result


def import_csv_recipe(
    recipe_path: str | Path,
    *,
    workspace: str | Path | None = None,
) -> OpenDataImportResult:
    """Import declared CSV columns without downloading, sorting, or inferring data.

    Only a checked local manifest with ``VERIFIED_RECORD_VERSION`` can produce
    a candidate Material.  Release registration remains a separate action.
    """

    recipe_file = Path(recipe_path)
    root = Path(workspace) if workspace is not None else recipe_file.parent
    recipe = _load_json(recipe_file, "import recipe")
    if recipe.get("schema") != "ems_open_material_import_recipe":
        raise OpenDataImportError("Invalid import recipe schema")
    if recipe.get("schema_version") != "1.0":
        raise OpenDataImportError("Unsupported import recipe version")
    manifest_ref = _string(recipe.get("manifest"), "manifest")
    manifest = SourceManifest.load(root / manifest_ref)
    if manifest.license_status != "VERIFIED_RECORD_VERSION":
        raise OpenDataImportError(
            "Manifest license_status must be VERIFIED_RECORD_VERSION"
        )
    if recipe.get("dataset_id") != manifest.dataset_id:
        raise OpenDataImportError("Recipe dataset_id does not match source manifest")
    source = _object(recipe.get("source"), "recipe source")
    raw_path = _string(source.get("path"), "recipe source.path")
    if source.get("format") != "csv":
        raise OpenDataImportError("The generic importer currently supports CSV only")
    manifest.verify_files(root)
    material_data = _object(recipe.get("material"), "recipe material")
    mappings = recipe.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise OpenDataImportError("recipe mappings must be a non-empty array")
    csv_path = root / raw_path
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as error:
        raise OpenDataImportError(f"Cannot read CSV {raw_path}: {error}") from error
    if not rows or not rows[0]:
        raise OpenDataImportError("CSV must contain a header and at least one data row")
    properties: dict[str, dict[str, CurveProperty]] = {}
    generated: list[str] = []
    for index, mapping_value in enumerate(mappings):
        mapping = _object(mapping_value, f"mappings[{index}]")
        if mapping.get("kind") != "curve":
            raise OpenDataImportError(
                "The generic importer currently supports curve mappings"
            )
        path = _string(mapping.get("property"), f"mappings[{index}].property")
        try:
            domain, name = path.split(".", 1)
        except ValueError as error:
            raise OpenDataImportError(f"Invalid property path {path!r}") from error
        x_column = _string(mapping.get("x_column"), f"mappings[{index}].x_column")
        y_column = _string(mapping.get("y_column"), f"mappings[{index}].y_column")
        x_data = _object(mapping.get("x"), f"mappings[{index}].x")
        y_data = _object(mapping.get("y"), f"mappings[{index}].y")
        try:
            x_values = tuple(float(row[x_column]) for row in rows)
            y_values = tuple(float(row[y_column]) for row in rows)
        except (KeyError, TypeError, ValueError) as error:
            raise OpenDataImportError(
                f"Cannot read numeric columns {x_column!r}/{y_column!r} from {raw_path}"
            ) from error
        source_metadata = PropertySource(
            dataset_id=manifest.dataset_id,
            manifest_ref=manifest_ref,
            raw_path=raw_path,
            sha256=manifest.file_sha256(raw_path),
            locator=f"CSV columns {x_column}, {y_column}; rows 2:{len(rows) + 1}",
            doi=manifest.doi,
            source_url=manifest.source_url,
            license=manifest.license,
            license_url=manifest.license_url,
            attribution=manifest.attribution,
            original_unit=mapping.get("original_unit"),
            conversion_note=mapping.get("conversion_note"),
        )
        properties.setdefault(domain, {})[name] = CurveProperty(
            Axis(
                _string(x_data.get("name"), "x.name"),
                _string(x_data.get("unit"), "x.unit"),
                x_values,
            ),
            Axis(
                _string(y_data.get("name"), "y.name"),
                _string(y_data.get("unit"), "y.unit"),
                y_values,
            ),
            conditions=_conditions(mapping.get("conditions")),
            note=(str(mapping["note"]).strip() if mapping.get("note") else None),
            source=source_metadata,
        )
        generated.append(path)
    material = Material(
        material_id=_string(material_data.get("material_id"), "material.material_id"),
        material_version=_string(
            material_data.get("material_version"), "material.material_version"
        ),
        identity=MaterialIdentity(
            name=_string(material_data.get("name"), "material.name"),
            family=_string(material_data.get("family"), "material.family"),
            description=(
                str(material_data["description"]).strip()
                if material_data.get("description")
                else None
            ),
            tags=tuple(str(item) for item in material_data.get("tags", [])),
        ),
        properties=properties,
        provenance=Provenance(
            "REFERENCE",
            reference=manifest.source_url,
            date=datetime.now(UTC).date().isoformat(),
            notes="Candidate generated by the local open-data importer; human review required.",
            license=manifest.license,
            license_url=manifest.license_url,
            attribution=manifest.attribution,
            source_manifest=manifest_ref,
        ),
        version_metadata=VersionMetadata(
            author=_string(recipe.get("author"), "author"),
            updated_at=_string(recipe.get("updated_at"), "updated_at"),
            change_note="Open-data candidate import; not released.",
        ),
        variant_id=(
            str(material_data["variant_id"]).strip()
            if material_data.get("variant_id")
            else None
        ),
    )
    return OpenDataImportResult(
        material=material,
        report={
            "dataset_id": manifest.dataset_id,
            "status": "IMPORTED_CANDIDATE",
            "raw_file": raw_path,
            "raw_sha256": manifest.file_sha256(raw_path),
            "properties_generated": generated,
            "rows_processed": len(rows),
            "license": manifest.license,
            "license_status": manifest.license_status,
            "release_allowed": False,
        },
    )
