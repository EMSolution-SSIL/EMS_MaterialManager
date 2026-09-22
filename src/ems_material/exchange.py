"""Product-neutral snapshot contract for material import and export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol

from .model import Material

ORIGIN_KEY = "_ems_material_origin"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def document_sha256(value: object) -> str:
    """Return a deterministic SHA-256 for a JSON-compatible value."""

    return sha256(_canonical_bytes(value)).hexdigest()


def material_sha256(material: Material) -> str:
    """Hash the complete canonical material record."""

    return document_sha256(material.to_dict())


def exported_payload_sha256(payload: Mapping[str, Any]) -> str:
    """Hash target values while excluding embedded lineage metadata."""

    values = deepcopy(dict(payload))
    values.pop(ORIGIN_KEY, None)
    return document_sha256(values)


@dataclass(frozen=True, slots=True)
class ExportSelection:
    """Select one active representation when a master stores several modes."""

    permeability: str = "auto"
    iron_loss: str = "auto"

    def to_dict(self) -> dict[str, str]:
        return {"permeability": self.permeability, "iron_loss": self.iron_loss}


@dataclass(frozen=True, slots=True)
class SnapshotOrigin:
    """Lineage stored beside a detached, editable product snapshot."""

    material_id: str
    material_version: str
    master_content_sha256: str
    exported_payload_sha256: str
    exported_at: str
    adapter_format: str
    selection: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "material_version": self.material_version,
            "master_content_sha256": self.master_content_sha256,
            "exported_payload_sha256": self.exported_payload_sha256,
            "exported_at": self.exported_at,
            "adapter_format": self.adapter_format,
            "selection": dict(self.selection),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SnapshotOrigin:
        return cls(
            material_id=str(data["material_id"]),
            material_version=str(data["material_version"]),
            master_content_sha256=str(data["master_content_sha256"]),
            exported_payload_sha256=str(data["exported_payload_sha256"]),
            exported_at=str(data["exported_at"]),
            adapter_format=str(data["adapter_format"]),
            selection=dict(data.get("selection", {})),
        )


@dataclass(frozen=True, slots=True)
class ProductMaterialSnapshot:
    """Product-format values plus their immutable master lineage."""

    payload: Mapping[str, Any]
    origin: SnapshotOrigin

    @classmethod
    def create(
        cls,
        material: Material,
        payload: Mapping[str, Any],
        *,
        adapter_format: str,
        selection: ExportSelection,
        exported_at: str | None = None,
    ) -> ProductMaterialSnapshot:
        detached = deepcopy(dict(payload))
        detached.pop(ORIGIN_KEY, None)
        origin = SnapshotOrigin(
            material_id=material.material_id,
            material_version=material.material_version,
            master_content_sha256=material_sha256(material),
            exported_payload_sha256=exported_payload_sha256(detached),
            exported_at=exported_at or datetime.now(timezone.utc).isoformat(),
            adapter_format=adapter_format,
            selection=selection.to_dict(),
        )
        return cls(detached, origin)

    def embedded_payload(self) -> dict[str, Any]:
        result = deepcopy(dict(self.payload))
        result[ORIGIN_KEY] = self.origin.to_dict()
        return result

    def is_modified(self, payload: Mapping[str, Any] | None = None) -> bool:
        candidate = self.payload if payload is None else payload
        return exported_payload_sha256(candidate) != self.origin.exported_payload_sha256


def origin_from_payload(payload: Mapping[str, Any]) -> SnapshotOrigin | None:
    value = payload.get(ORIGIN_KEY)
    if not isinstance(value, Mapping):
        return None
    return SnapshotOrigin.from_dict(value)


class ProductMaterialAdapter(Protocol):
    """Minimum bidirectional contract implemented by product adapters."""

    format_id: str

    def export_material(
        self, material: Material, *, selection: ExportSelection | None = None
    ) -> ProductMaterialSnapshot: ...

    def import_material(
        self, payload: Mapping[str, Any], **metadata: Any
    ) -> Material: ...
