"""Filesystem-backed repository for user-owned canonical materials."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from typing import Protocol
from urllib.parse import quote

from .errors import (
    MaterialAlreadyExistsError,
    MaterialConflictError,
    MaterialNotFoundError,
    ManagerConfigurationError,
    ReadOnlyMaterialError,
    RepositoryCorruptionError,
)
from .model import Material, MaterialIdentity, VersionMetadata
from .serialization import load_material, save_material


class MaterialRepository(Protocol):
    def list(self) -> tuple[Material, ...]: ...

    def get(self, material_id: str) -> Material: ...

    def create(self, material: Material) -> Material: ...

    def update(self, material: Material, *, expected_version: str | None = None) -> Material: ...

    def delete(self, material_id: str) -> None: ...

    def duplicate(
        self,
        source_id: str,
        *,
        new_material_id: str,
        new_name: str,
        author: str,
        updated_at: str,
        change_note: str = "Duplicated material",
    ) -> Material: ...

    def search(
        self,
        *,
        family: str | None = None,
        text: str | None = None,
        manufacturer: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[Material, ...]: ...

    def import_json(self, source: str | Path) -> Material: ...

    def export_json(self, material_id: str, destination: str | Path) -> None: ...

    def source_for(self, material_id: str) -> str | None: ...

    def is_writable(self, material_id: str) -> bool: ...

    def is_deletable(self, material_id: str) -> bool: ...

    def list_sources(self) -> tuple[str, ...]: ...


class JsonMaterialRepository:
    """A deterministic, single-user JSON repository.

    Cross-process locking is intentionally deferred. Atomic replacement prevents
    partial files; ``expected_version`` provides an optimistic stale-write check.
    """

    suffix = ".material.json"

    def __init__(
        self, root: str | Path, *, allow_reference_updates: bool = False
    ) -> None:
        self.root = Path(root)
        self.allow_reference_updates = allow_reference_updates
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for_id(self, material_id: str) -> Path:
        safe_name = quote(material_id, safe="-._")
        return self.root / f"{safe_name}{self.suffix}"

    def _load_checked(self, path: Path) -> Material:
        material = load_material(path)
        expected = self.path_for_id(material.material_id).resolve()
        if path.resolve() != expected:
            raise RepositoryCorruptionError(
                f"Stored material ID {material.material_id!r} does not match file {path.name!r}"
            )
        return material

    def list(self) -> tuple[Material, ...]:
        materials = tuple(
            self._load_checked(path) for path in sorted(self.root.glob(f"*{self.suffix}"))
        )
        ids = [material.material_id for material in materials]
        if len(ids) != len(set(ids)):
            raise RepositoryCorruptionError("Duplicate material_id found in repository")
        return materials

    def get(self, material_id: str) -> Material:
        path = self.path_for_id(material_id)
        if not path.is_file():
            raise MaterialNotFoundError(f"Material not found: {material_id}")
        return self._load_checked(path)

    def create(self, material: Material) -> Material:
        path = self.path_for_id(material.material_id)
        if path.exists():
            raise MaterialAlreadyExistsError(
                f"Material already exists: {material.material_id}"
            )
        save_material(material, path)
        return material

    def update(
        self,
        material: Material,
        *,
        expected_version: str | None = None,
    ) -> Material:
        existing = self.get(material.material_id)
        if expected_version is not None and existing.material_version != expected_version:
            raise MaterialConflictError(
                f"Expected {expected_version}, found {existing.material_version} for "
                f"{material.material_id}"
            )
        if (
            existing.provenance.source_type != "USER_INPUT"
            and not self.allow_reference_updates
        ):
            raise ReadOnlyMaterialError(
                f"Only USER_INPUT materials can be updated: {material.material_id}"
            )
        save_material(material, self.path_for_id(material.material_id))
        return material

    def duplicate(
        self,
        source_id: str,
        *,
        new_material_id: str,
        new_name: str,
        author: str,
        updated_at: str,
        change_note: str = "Duplicated material",
    ) -> Material:
        source = self.get(source_id)
        duplicate = replace(
            source,
            material_id=new_material_id,
            material_version="1.0.0",
            identity=replace(source.identity, name=new_name),
            provenance=replace(
                source.provenance,
                source_type="USER_INPUT",
                reference=f"{source.material_id}@{source.material_version}",
                notes="Duplicated from an existing material",
            ),
            version_metadata=VersionMetadata(author, updated_at, change_note),
            parent_ref=f"{source.material_id}@{source.material_version}",
        )
        return self.create(duplicate)

    def delete(self, material_id: str) -> None:
        material = self.get(material_id)
        if material.provenance.source_type != "USER_INPUT":
            raise ReadOnlyMaterialError(
                f"Only USER_INPUT materials can be deleted: {material_id}"
            )
        self.path_for_id(material_id).unlink()

    def search(
        self,
        *,
        family: str | None = None,
        text: str | None = None,
        manufacturer: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[Material, ...]:
        text_query = text.casefold() if text else None
        tag_query = {tag.casefold() for tag in tags}
        matches: list[Material] = []
        for material in self.list():
            identity: MaterialIdentity = material.identity
            if family and identity.family.casefold() != family.casefold():
                continue
            if manufacturer and (identity.manufacturer or "").casefold() != manufacturer.casefold():
                continue
            if tag_query and not tag_query.issubset({tag.casefold() for tag in identity.tags}):
                continue
            haystack = " ".join(
                part
                for part in (
                    material.material_id,
                    identity.name,
                    identity.grade or "",
                    identity.manufacturer or "",
                    *identity.aliases,
                    *identity.tags,
                )
                if part
            ).casefold()
            if text_query and text_query not in haystack:
                continue
            matches.append(material)
        return tuple(matches)

    def import_json(self, source: str | Path) -> Material:
        return self.create(load_material(source))

    def export_json(self, material_id: str, destination: str | Path) -> None:
        save_material(self.get(material_id), destination)

    def source_for(self, material_id: str) -> str | None:
        self.get(material_id)
        return self.root.name or str(self.root)

    def is_writable(self, material_id: str) -> bool:
        material = self.get(material_id)
        return (
            material.provenance.source_type == "USER_INPUT"
            or self.allow_reference_updates
        )

    def is_deletable(self, material_id: str) -> bool:
        return self.get(material_id).provenance.source_type == "USER_INPUT"

    def list_sources(self) -> tuple[str, ...]:
        return (self.root.name or str(self.root),)


class ConfiguredMaterialRepository:
    """Repository composed from explicitly enabled material source folders.

    The root ``manager.config.json`` is the allow-list of source directories.
    Every enabled source has its own ``source.config.json`` allow-list of files.
    Files and directories that are not listed are deliberately invisible.
    """

    root_config_name = "manager.config.json"
    source_config_name = "source.config.json"
    suffix = ".material.json"

    def __init__(
        self, root: str | Path, *, allow_reference_updates: bool = False
    ) -> None:
        self.root = Path(root)
        self.allow_reference_updates = allow_reference_updates
        self.root.mkdir(parents=True, exist_ok=True)
        self._cached_index: dict[str, tuple[Material, dict, Path]] | None = None
        self._load_sources()

    @staticmethod
    def _read_object(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ManagerConfigurationError(f"Configuration file not found: {path}") from error
        except json.JSONDecodeError as error:
            raise ManagerConfigurationError(
                f"Invalid JSON in {path} at line {error.lineno}: {error.msg}"
            ) from error
        if not isinstance(data, dict):
            raise ManagerConfigurationError(f"Configuration must be an object: {path}")
        return data

    @staticmethod
    def _check_keys(data: dict, allowed: set[str], path: Path) -> None:
        unknown = set(data) - allowed
        if unknown:
            raise ManagerConfigurationError(
                f"Unknown key(s) in {path}: {', '.join(sorted(unknown))}"
            )

    def _resolve_relative(self, relative: str, *, parent: Path, label: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute():
            raise ManagerConfigurationError(f"{label} must be relative: {relative!r}")
        resolved = (parent / candidate).resolve()
        try:
            resolved.relative_to(parent.resolve())
        except ValueError as error:
            raise ManagerConfigurationError(
                f"{label} escapes its configured directory: {relative!r}"
            ) from error
        return resolved

    def _load_sources(self) -> tuple[dict, ...]:
        config_path = self.root / self.root_config_name
        data = self._read_object(config_path)
        self._check_keys(
            data,
            {"schema", "schema_version", "default_write_source", "catalog", "sources"},
            config_path,
        )
        if data.get("schema") != "ems_material_manager_config":
            raise ManagerConfigurationError(f"Invalid material manager config schema: {config_path}")
        if data.get("schema_version") != "1.0":
            raise ManagerConfigurationError(
                f"Unsupported library config version in {config_path}"
            )
        entries = data.get("sources")
        if not isinstance(entries, list):
            raise ManagerConfigurationError(f"sources must be an array: {config_path}")
        sources: list[dict] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ManagerConfigurationError(f"sources[{index}] must be an object")
            self._check_keys(entry, {"path", "enabled", "writable"}, config_path)
            relative = entry.get("path")
            if not isinstance(relative, str) or not relative.strip():
                raise ManagerConfigurationError(f"sources[{index}].path must be a string")
            if relative.casefold() in seen:
                raise ManagerConfigurationError(f"Duplicate source path: {relative}")
            seen.add(relative.casefold())
            enabled = entry.get("enabled", True)
            writable = entry.get("writable", False)
            if not isinstance(enabled, bool) or not isinstance(writable, bool):
                raise ManagerConfigurationError(
                    f"enabled/writable must be boolean for source {relative!r}"
                )
            if not enabled:
                continue
            directory = self._resolve_relative(
                relative, parent=self.root, label="Source path"
            )
            if not directory.is_dir():
                raise ManagerConfigurationError(f"Source directory not found: {directory}")
            source_config_path = directory / self.source_config_name
            source_data = self._read_object(source_config_path)
            self._check_keys(
                source_data,
                {"schema", "schema_version", "name", "description", "files"},
                source_config_path,
            )
            if source_data.get("schema") != "ems_material_source_config":
                raise ManagerConfigurationError(
                    f"Invalid source config schema: {source_config_path}"
                )
            if source_data.get("schema_version") != "1.0":
                raise ManagerConfigurationError(
                    f"Unsupported source config version: {source_config_path}"
                )
            name = source_data.get("name")
            files = source_data.get("files")
            if not isinstance(name, str) or not name.strip():
                raise ManagerConfigurationError(f"Source name is required: {source_config_path}")
            if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
                raise ManagerConfigurationError(f"files must be a string array: {source_config_path}")
            if len(files) != len({item.casefold() for item in files}):
                raise ManagerConfigurationError(f"Duplicate file in {source_config_path}")
            resolved_files: list[Path] = []
            for filename in files:
                material_path = self._resolve_relative(
                    filename, parent=directory, label="Material file"
                )
                if material_path.parent != directory.resolve():
                    raise ManagerConfigurationError(
                        f"Material files must be directly inside {directory}: {filename!r}"
                    )
                if not filename.endswith(self.suffix):
                    raise ManagerConfigurationError(
                        f"Configured material must end with {self.suffix}: {filename!r}"
                    )
                if not material_path.is_file():
                    raise ManagerConfigurationError(
                        f"Configured material file not found: {material_path}"
                    )
                resolved_files.append(material_path)
            sources.append(
                {
                    "path": relative,
                    "directory": directory,
                    "name": name,
                    "writable": writable,
                    "files": tuple(resolved_files),
                    "file_names": tuple(files),
                    "config_path": source_config_path,
                    "config": source_data,
                }
            )
        default = data.get("default_write_source")
        if default is not None and not isinstance(default, str):
            raise ManagerConfigurationError("default_write_source must be a string or null")
        if default is not None:
            matches = [source for source in sources if source["path"] == default]
            if len(matches) != 1 or not matches[0]["writable"]:
                raise ManagerConfigurationError(
                    "default_write_source must name one enabled writable source"
                )
        self._root_config = data
        self._default_write_source = default
        self._sources = tuple(sources)
        return self._sources

    def _index(self) -> dict[str, tuple[Material, dict, Path]]:
        self._load_sources()
        index: dict[str, tuple[Material, dict, Path]] = {}
        for source in self._sources:
            for path in source["files"]:
                material = load_material(path)
                if material.material_id in index:
                    previous = index[material.material_id][2]
                    raise RepositoryCorruptionError(
                        f"Duplicate material_id {material.material_id!r}: {previous} and {path}"
                    )
                index[material.material_id] = (material, source, path)
        return index

    def _default_source(self) -> dict:
        self._load_sources()
        for source in self._sources:
            if source["path"] == self._default_write_source:
                return source
        raise ReadOnlyMaterialError("No default writable material source is configured")

    @staticmethod
    def _write_json_atomic(data: dict, destination: Path) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
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

    def _replace_source_files(self, source: dict, file_names: list[str]) -> None:
        config = dict(source["config"])
        config["files"] = file_names
        self._write_json_atomic(config, source["config_path"])

    def list(self) -> tuple[Material, ...]:
        self._cached_index = self._index()
        return tuple(value[0] for value in self._cached_index.values())

    def get(self, material_id: str) -> Material:
        try:
            return self._index()[material_id][0]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material_id}") from error

    def create(self, material: Material) -> Material:
        if material.material_id in self._index():
            raise MaterialAlreadyExistsError(
                f"Material already exists: {material.material_id}"
            )
        source = self._default_source()
        filename = f"{quote(material.material_id, safe='-._')}{self.suffix}"
        destination = source["directory"] / filename
        if destination.exists():
            raise MaterialAlreadyExistsError(f"Material file already exists: {destination}")
        save_material(material, destination)
        try:
            self._replace_source_files(source, [*source["file_names"], filename])
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        self._cached_index = None
        return material

    def update(
        self, material: Material, *, expected_version: str | None = None
    ) -> Material:
        try:
            existing, source, path = self._index()[material.material_id]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material.material_id}") from error
        if expected_version is not None and existing.material_version != expected_version:
            raise MaterialConflictError(
                f"Expected {expected_version}, found {existing.material_version} for "
                f"{material.material_id}"
            )
        normally_writable = (
            source["writable"] and existing.provenance.source_type == "USER_INPUT"
        )
        if not normally_writable and not self.allow_reference_updates:
            raise ReadOnlyMaterialError(
                f"Material source is read-only: {material.material_id}"
            )
        save_material(material, path)
        self._cached_index = None
        return material

    def duplicate(
        self,
        source_id: str,
        *,
        new_material_id: str,
        new_name: str,
        author: str,
        updated_at: str,
        change_note: str = "Duplicated material",
    ) -> Material:
        source = self.get(source_id)
        duplicate = replace(
            source,
            material_id=new_material_id,
            material_version="1.0.0",
            identity=replace(source.identity, name=new_name),
            provenance=replace(
                source.provenance,
                source_type="USER_INPUT",
                reference=f"{source.material_id}@{source.material_version}",
                notes="Duplicated from an existing material",
            ),
            version_metadata=VersionMetadata(author, updated_at, change_note),
            parent_ref=f"{source.material_id}@{source.material_version}",
        )
        return self.create(duplicate)

    def delete(self, material_id: str) -> None:
        try:
            material, source, path = self._index()[material_id]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material_id}") from error
        if not source["writable"] or material.provenance.source_type != "USER_INPUT":
            raise ReadOnlyMaterialError(f"Material source is read-only: {material_id}")
        remaining = [name for name in source["file_names"] if name != path.name]
        path.unlink()
        try:
            self._replace_source_files(source, remaining)
        except Exception:
            save_material(material, path)
            raise
        self._cached_index = None

    def search(
        self,
        *,
        family: str | None = None,
        text: str | None = None,
        manufacturer: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[Material, ...]:
        text_query = text.casefold() if text else None
        tag_query = {tag.casefold() for tag in tags}
        matches: list[Material] = []
        for material in self.list():
            identity = material.identity
            if family and identity.family.casefold() != family.casefold():
                continue
            if manufacturer and (identity.manufacturer or "").casefold() != manufacturer.casefold():
                continue
            if tag_query and not tag_query.issubset({tag.casefold() for tag in identity.tags}):
                continue
            haystack = " ".join(
                part
                for part in (
                    material.material_id,
                    identity.name,
                    identity.grade or "",
                    identity.manufacturer or "",
                    *identity.aliases,
                    *identity.tags,
                )
                if part
            ).casefold()
            if text_query and text_query not in haystack:
                continue
            matches.append(material)
        return tuple(matches)

    def import_json(self, source: str | Path) -> Material:
        return self.create(load_material(source))

    def export_json(self, material_id: str, destination: str | Path) -> None:
        save_material(self.get(material_id), destination)

    def source_for(self, material_id: str) -> str | None:
        index = self._cached_index if self._cached_index is not None else self._index()
        try:
            return index[material_id][1]["name"]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material_id}") from error

    def is_writable(self, material_id: str) -> bool:
        index = self._cached_index if self._cached_index is not None else self._index()
        try:
            material, source, _path = index[material_id]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material_id}") from error
        return (
            source["writable"] and material.provenance.source_type == "USER_INPUT"
        ) or self.allow_reference_updates

    def is_deletable(self, material_id: str) -> bool:
        index = self._cached_index if self._cached_index is not None else self._index()
        try:
            material, source, _path = index[material_id]
        except KeyError as error:
            raise MaterialNotFoundError(f"Material not found: {material_id}") from error
        return source["writable"] and material.provenance.source_type == "USER_INPUT"

    def list_sources(self) -> tuple[str, ...]:
        self._load_sources()
        return tuple(source["name"] for source in self._sources)
