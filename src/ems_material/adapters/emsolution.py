"""Bidirectional adapter for EMSolution ``input.json`` material sections."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from ..exchange import ExportSelection, ProductMaterialSnapshot, SnapshotOrigin
from ..formats import load_format_profile
from ..manager import MaterialManager
from ..model import (
    Axis,
    CurveProperty,
    Material,
    MaterialIdentity,
    MaterialProperty,
    Provenance,
    ScalarProperty,
    VersionMetadata,
)
from ._values import curve_points, require_values, scalar_value


class EMSolutionInputAdapter:
    """Copy canonical values into and out of an EMSolution input document.

    EMSolution input-control JSON is intentionally kept free of library-only
    keys.  Snapshot lineage is written to ``<stem>.ems-material-links.json``.
    """

    profile_filename = "emsolution-input.v1.json"

    def __init__(self) -> None:
        self.profile = load_format_profile(self.profile_filename)
        self.format_id = str(self.profile["format_id"])
        self.keys: Mapping[str, Any] = self.profile["keys"]

    @staticmethod
    def load_document(path: str | Path) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            raise TypeError("EMSolution input document must be a JSON object")
        return document

    @staticmethod
    def sidecar_path(path: str | Path) -> Path:
        source = Path(path)
        return source.with_name(f"{source.stem}.ems-material-links.json")

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                temporary_name = stream.name
            os.replace(temporary_name, path)
        finally:
            if temporary_name is not None:
                temporary = Path(temporary_name)
                if temporary.exists():
                    temporary.unlink()

    def _materials(self, document: MutableMapping[str, Any]) -> list[dict[str, Any]]:
        section: Any = document
        path = self.profile["sections"]["materials"]
        for key in path[:-1]:
            existing = section.get(key)
            if existing is None:
                existing = {}
                section[key] = existing
            if not isinstance(existing, dict):
                raise TypeError(f"EMSolution section {key!r} must be an object")
            section = existing
        values = section.get(path[-1])
        if values is None:
            values = []
            section[path[-1]] = values
        if not isinstance(values, list):
            raise TypeError("EMSolution 3D element properties section must be a list")
        return values

    def _bh_curves(self, document: MutableMapping[str, Any]) -> list[dict[str, Any]]:
        key = self.profile["sections"]["bh_curves"][0]
        values = document.get(key)
        if values is None:
            values = []
            document[key] = values
        if not isinstance(values, list):
            raise TypeError("EMSolution BH curve section must be a list")
        return values

    @staticmethod
    def _next_id(rows: Sequence[Mapping[str, Any]], key: str) -> int:
        ids = [row.get(key) for row in rows]
        numeric = [
            value
            for value in ids
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        return max(numeric, default=0) + 1

    @staticmethod
    def _curve_record(
        name: str, curve_id: int, points: list[list[float]]
    ) -> dict[str, Any]:
        return {
            "BH_CURVE_ID": curve_id,
            "BH_CURVE_NAME": name,
            "data": {
                "H": [row[0] for row in points],
                "B": [row[1] for row in points],
            },
        }

    @staticmethod
    def _permeability_mode(material: Material, requested: str) -> str:
        if requested != "auto":
            return requested
        if curve_points(material, "electromagnetic.BH_curve") is not None:
            return "bh_isotropy"
        directional = tuple(
            curve_points(material, f"electromagnetic.BH_curve_{axis}")
            for axis in ("x", "y", "z")
        )
        if any(value is not None for value in directional):
            return "bh_anisotropy"
        return "linear"

    @staticmethod
    def _iron_loss(material: Material, requested: str) -> dict[str, Any] | None:
        mode = requested
        if mode == "auto":
            isotropic = tuple(
                scalar_value(material, path, unit)
                for path, unit in (
                    ("electromagnetic.iron_loss_ke", "W/kg/T^2/Hz^2"),
                    ("electromagnetic.iron_loss_kh", "W/kg/T^2/Hz"),
                )
            )
            anisotropic = tuple(
                scalar_value(material, path, unit)
                for path, unit in (
                    ("electromagnetic.iron_loss_ke_x", "W/kg/T^2/Hz^2"),
                    ("electromagnetic.iron_loss_ke_y", "W/kg/T^2/Hz^2"),
                    ("electromagnetic.iron_loss_kh_x", "W/kg/T^2/Hz"),
                    ("electromagnetic.iron_loss_kh_y", "W/kg/T^2/Hz"),
                    ("electromagnetic.iron_loss_kh_z", "W/kg/T^2/Hz"),
                )
            )
            mode = (
                "isotropy"
                if all(v is not None for v in isotropic)
                else (
                    "anisotropy" if all(v is not None for v in anisotropic) else "none"
                )
            )
        if mode == "none":
            return None
        density = scalar_value(material, "general.density", "kg/m^3")
        if density is None:
            raise ValueError("general.density is required when exporting iron loss")
        if mode == "isotropy":
            values = require_values(
                (
                    (
                        "KE",
                        scalar_value(
                            material, "electromagnetic.iron_loss_ke", "W/kg/T^2/Hz^2"
                        ),
                    ),
                    (
                        "KH",
                        scalar_value(
                            material, "electromagnetic.iron_loss_kh", "W/kg/T^2/Hz"
                        ),
                    ),
                )
            )
            return {"COORD_ID": 0, "MASS_DENSITY": density, **values}
        if mode != "anisotropy":
            raise ValueError(f"Unsupported iron-loss mode: {mode}")
        values = require_values(
            (
                (
                    "KE_X",
                    scalar_value(
                        material, "electromagnetic.iron_loss_ke_x", "W/kg/T^2/Hz^2"
                    ),
                ),
                (
                    "KE_Y",
                    scalar_value(
                        material, "electromagnetic.iron_loss_ke_y", "W/kg/T^2/Hz^2"
                    ),
                ),
                (
                    "KH_X",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_x", "W/kg/T^2/Hz"
                    ),
                ),
                (
                    "KH_Y",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_y", "W/kg/T^2/Hz"
                    ),
                ),
                (
                    "KH_Z",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_z", "W/kg/T^2/Hz"
                    ),
                ),
            )
        )
        return {
            "COORD_ID": 0,
            "MASS_DENSITY": density,
            "KE_XY": [values["KE_X"], values["KE_Y"]],
            "KH_XYZ": [values["KH_X"], values["KH_Y"], values["KH_Z"]],
        }

    @staticmethod
    def _complex_permeability(material: Material) -> dict[str, Any] | None:
        real_xyz = tuple(
            scalar_value(
                material,
                f"electromagnetic.complex_relative_permeability_real_{axis}",
                "1",
            )
            for axis in ("x", "y", "z")
        )
        imaginary_xyz = tuple(
            scalar_value(
                material,
                f"electromagnetic.complex_relative_permeability_imaginary_{axis}",
                "1",
            )
            for axis in ("x", "y", "z")
        )
        if all(value is not None for value in real_xyz + imaginary_xyz):
            return {
                "comment": "AC=2, ANISOTROPY=2",
                "COORD_ID": 0,
                "MU_Re_XYZ": list(real_xyz),
                "MU_Im_XYZ": list(imaginary_xyz),
            }
        real = scalar_value(
            material, "electromagnetic.complex_relative_permeability_real", "1"
        )
        imaginary = scalar_value(
            material, "electromagnetic.complex_relative_permeability_imaginary", "1"
        )
        if real is None and imaginary is None:
            return None
        values = require_values((("MU_Re", real), ("MU_Im", imaginary)))
        return {"comment": "AC=2, ANISOTROPY=1", **values}

    @staticmethod
    def _complex_permittivity(material: Material) -> dict[str, Any] | None:
        """Return the ``EPS_COMPLEX`` payload mirroring ``SIGMA_COMPLEX``.

        EMSolution uses the same isotropic/anisotropic layout for complex
        electrical material values.  The property names remain explicit in
        the canonical library; the adapter is responsible for the product
        field names and the vector ordering.
        """
        real_xyz = tuple(
            scalar_value(
                material,
                f"electrical.complex_relative_permittivity_real_{axis}",
                "1",
            )
            for axis in ("x", "y", "z")
        )
        imaginary_xyz = tuple(
            scalar_value(
                material,
                f"electrical.complex_relative_permittivity_imaginary_{axis}",
                "1",
            )
            for axis in ("x", "y", "z")
        )
        if all(value is not None for value in real_xyz + imaginary_xyz):
            return {
                "comment": "AC=2, ANISOTROPY=2",
                "COORD_ID": 0,
                "EPS_Re_XYZ": list(real_xyz),
                "EPS_Im_XYZ": list(imaginary_xyz),
            }
        real = scalar_value(
            material, "electrical.complex_relative_permittivity_real", "1"
        )
        imaginary = scalar_value(
            material, "electrical.complex_relative_permittivity_imaginary", "1"
        )
        if real is None and imaginary is None:
            return None
        values = require_values((("EPS_Re", real), ("EPS_Im", imaginary)))
        return {"comment": "AC=2, ANISOTROPY=1", **values}

    def _build_fragment(
        self,
        material: Material,
        selection: ExportSelection,
        *,
        material_id: int,
        curve_ids: Sequence[int],
    ) -> dict[str, Any]:
        electric: dict[str, Any] = {}
        conductivity = scalar_value(
            material, "electromagnetic.electrical_conductivity", "S/m"
        )
        if conductivity is not None:
            electric["conductivity"] = {"SIGMA": conductivity}
        permittivity = scalar_value(material, "electrical.relative_permittivity", "1")
        if permittivity is not None:
            electric["permittivity"] = {"EPS": permittivity}
        complex_eps = self._complex_permittivity(material)
        if complex_eps is not None:
            electric["EPS_COMPLEX"] = complex_eps

        magnetic: dict[str, Any] = {}
        curves: list[dict[str, Any]] = []
        mode = self._permeability_mode(material, selection.permeability)
        if mode == "linear":
            mu = scalar_value(material, "electromagnetic.relative_permeability", "1")
            magnetic["MU"] = mu if mu is not None else 1.0
        elif mode == "bh_isotropy":
            points = curve_points(material, "electromagnetic.BH_curve")
            if points is None:
                raise ValueError("electromagnetic.BH_curve is required")
            magnetic.update({"MU": 1.0, "BH_CURVE_ID": curve_ids[0]})
            curves.append(self._curve_record(material.name, curve_ids[0], points))
        elif mode == "bh_anisotropy":
            directional = [
                curve_points(material, f"electromagnetic.BH_curve_{axis}")
                for axis in ("x", "y", "z")
            ]
            if any(points is None for points in directional):
                raise ValueError("BH_curve_x, BH_curve_y, and BH_curve_z are required")
            magnetic["BH_CURVE_XYZ"] = {
                "comment": "ANISOTROPY=1",
                "COORD_ID": 0,
                "BH_XYZ_ID": list(curve_ids[:3]),
                "MU_XYZ": [1.0, 1.0, 1.0],
            }
            for axis, curve_id, points in zip(("x", "y", "z"), curve_ids, directional):
                assert points is not None
                curves.append(
                    self._curve_record(f"{material.name}_{axis}", curve_id, points)
                )
        else:
            raise ValueError(f"Unsupported permeability mode: {mode}")

        complex_mu = self._complex_permeability(material)
        if complex_mu is not None:
            magnetic["MU_COMPLEX"] = complex_mu
        iron_loss = self._iron_loss(material, selection.iron_loss)
        if iron_loss is not None:
            magnetic["IRON_LOSS"] = iron_loss

        entry: dict[str, Any] = {
            "MAT_ID": material_id,
            "MAT_NAME": material.name,
            "POTENTIAL": 0,
        }
        if electric:
            entry["ElectricProperty"] = electric
        if magnetic:
            entry["MagneticProperty"] = magnetic
        return {"material": entry, "bh_curves": curves}

    def export_material(
        self,
        material: Material,
        *,
        selection: ExportSelection | None = None,
    ) -> ProductMaterialSnapshot:
        selected = selection or ExportSelection()
        count = (
            3
            if self._permeability_mode(material, selected.permeability)
            == "bh_anisotropy"
            else 1
        )
        payload = self._build_fragment(
            material, selected, material_id=1, curve_ids=tuple(range(1, count + 1))
        )
        return ProductMaterialSnapshot.create(
            material, payload, adapter_format=self.format_id, selection=selected
        )

    def apply_to_document(
        self,
        document: Mapping[str, Any],
        material: Material,
        *,
        selection: ExportSelection | None = None,
        replace_name: str | None = None,
    ) -> tuple[dict[str, Any], ProductMaterialSnapshot]:
        selected = selection or ExportSelection()
        updated = deepcopy(dict(document))
        materials = self._materials(updated)
        curves = self._bh_curves(updated)
        target_name = replace_name or material.name

        existing = next(
            (row for row in materials if row.get("MAT_NAME") == target_name), None
        )
        material_id = (
            existing.get("MAT_ID")
            if isinstance(existing, dict) and isinstance(existing.get("MAT_ID"), int)
            else self._next_id(materials, "MAT_ID")
        )
        materials[:] = [row for row in materials if row.get("MAT_NAME") != target_name]
        owned_names = {
            target_name,
            *(f"{target_name}_{axis}" for axis in ("x", "y", "z")),
        }
        curves[:] = [
            row for row in curves if row.get("BH_CURVE_NAME") not in owned_names
        ]

        mode = self._permeability_mode(material, selected.permeability)
        curve_count = (
            3 if mode == "bh_anisotropy" else (1 if mode == "bh_isotropy" else 0)
        )
        next_curve = self._next_id(curves, "BH_CURVE_ID")
        curve_ids = tuple(range(next_curve, next_curve + curve_count))
        fragment = self._build_fragment(
            material,
            selected,
            material_id=material_id,
            curve_ids=curve_ids or (0,),
        )
        materials.append(fragment["material"])
        curves.extend(fragment["bh_curves"])
        snapshot = ProductMaterialSnapshot.create(
            material, fragment, adapter_format=self.format_id, selection=selected
        )
        return updated, snapshot

    def apply_to_file(
        self,
        path: str | Path,
        material: Material,
        *,
        selection: ExportSelection | None = None,
        replace_name: str | None = None,
    ) -> ProductMaterialSnapshot:
        input_path = Path(path)
        document = self.load_document(input_path)
        updated, snapshot = self.apply_to_document(
            document, material, selection=selection, replace_name=replace_name
        )
        self._write_json_atomic(input_path, updated)
        sidecar_path = self.sidecar_path(input_path)
        links: dict[str, Any] = {
            "schema": "ems_material_links",
            "schema_version": "1.0",
            "materials": {},
        }
        if sidecar_path.exists():
            try:
                existing = self.load_document(sidecar_path)
                if isinstance(existing.get("materials"), dict):
                    links = existing
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        links.setdefault("materials", {})[material.name] = snapshot.origin.to_dict()
        if replace_name and replace_name != material.name:
            links["materials"].pop(replace_name, None)
        self._write_json_atomic(sidecar_path, links)
        return snapshot

    def list_material_names(self, document: Mapping[str, Any]) -> tuple[str, ...]:
        mutable = deepcopy(dict(document))
        return tuple(
            str(row["MAT_NAME"])
            for row in self._materials(mutable)
            if isinstance(row, dict) and row.get("MAT_NAME")
        )

    @staticmethod
    def _curve_property(record: Mapping[str, Any]) -> CurveProperty:
        data = record.get("data")
        if not isinstance(data, Mapping):
            raise TypeError("EMSolution BH curve data must be an object")
        h_values = data.get("H")
        b_values = data.get("B")
        if not isinstance(h_values, list) or not isinstance(b_values, list):
            raise TypeError("EMSolution BH curve requires H and B arrays")
        return CurveProperty(
            x=Axis("H", "A/m", tuple(h_values)),
            y=Axis("B", "T", tuple(b_values)),
            display={"x_scale": "log", "y_scale": "linear"},
        )

    def extract_material(
        self,
        document: Mapping[str, Any],
        name: str,
        *,
        family: str,
        author: str,
        source_reference: str | None = None,
        origin: SnapshotOrigin | None = None,
    ) -> Material:
        mutable = deepcopy(dict(document))
        entry = next(
            (row for row in self._materials(mutable) if row.get("MAT_NAME") == name),
            None,
        )
        if entry is None:
            raise ValueError(f"EMSolution material {name!r} was not found")
        curve_by_id = {
            row.get("BH_CURVE_ID"): row
            for row in self._bh_curves(mutable)
            if isinstance(row, dict)
        }
        properties: dict[str, dict[str, MaterialProperty]] = {}
        electromagnetic = properties.setdefault("electromagnetic", {})
        electric = entry.get("ElectricProperty", {})
        if isinstance(electric, Mapping):
            conductivity = electric.get("conductivity")
            if (
                isinstance(conductivity, Mapping)
                and conductivity.get("SIGMA") is not None
            ):
                electromagnetic["electrical_conductivity"] = ScalarProperty(
                    conductivity["SIGMA"], "S/m"
                )
            permittivity = electric.get("permittivity")
            if (
                isinstance(permittivity, Mapping)
                and permittivity.get("EPS") is not None
            ):
                properties.setdefault("electrical", {})["relative_permittivity"] = (
                    ScalarProperty(permittivity["EPS"], "1")
                )
            complex_eps = electric.get("EPS_COMPLEX")
            if isinstance(complex_eps, Mapping):
                electrical = properties.setdefault("electrical", {})
                if isinstance(complex_eps.get("EPS_Re_XYZ"), list) and isinstance(
                    complex_eps.get("EPS_Im_XYZ"), list
                ):
                    for axis, real, imaginary in zip(
                        ("x", "y", "z"),
                        complex_eps["EPS_Re_XYZ"],
                        complex_eps["EPS_Im_XYZ"],
                    ):
                        electrical[f"complex_relative_permittivity_real_{axis}"] = (
                            ScalarProperty(real, "1")
                        )
                        electrical[
                            f"complex_relative_permittivity_imaginary_{axis}"
                        ] = ScalarProperty(imaginary, "1")
                elif (
                    complex_eps.get("EPS_Re") is not None
                    and complex_eps.get("EPS_Im") is not None
                ):
                    electrical["complex_relative_permittivity_real"] = ScalarProperty(
                        complex_eps["EPS_Re"], "1"
                    )
                    electrical["complex_relative_permittivity_imaginary"] = (
                        ScalarProperty(complex_eps["EPS_Im"], "1")
                    )

        magnetic = entry.get("MagneticProperty", {})
        if isinstance(magnetic, Mapping):
            xyz = magnetic.get("BH_CURVE_XYZ")
            if isinstance(xyz, Mapping) and isinstance(xyz.get("BH_XYZ_ID"), list):
                for axis, curve_id in zip(("x", "y", "z"), xyz["BH_XYZ_ID"]):
                    if curve_id in curve_by_id:
                        electromagnetic[f"BH_curve_{axis}"] = self._curve_property(
                            curve_by_id[curve_id]
                        )
            else:
                curve_id = next(
                    (
                        magnetic.get(key)
                        for key in ("BH_CURVE_ID", "B_H_CURVE_ID")
                        if magnetic.get(key) is not None
                    ),
                    None,
                )
                if curve_id in curve_by_id:
                    electromagnetic["BH_curve"] = self._curve_property(
                        curve_by_id[curve_id]
                    )
                elif magnetic.get("MU") is not None:
                    electromagnetic["relative_permeability"] = ScalarProperty(
                        magnetic["MU"], "1"
                    )
            complex_mu = magnetic.get("MU_COMPLEX")
            if isinstance(complex_mu, Mapping):
                if isinstance(complex_mu.get("MU_Re_XYZ"), list) and isinstance(
                    complex_mu.get("MU_Im_XYZ"), list
                ):
                    for axis, real, imaginary in zip(
                        ("x", "y", "z"),
                        complex_mu["MU_Re_XYZ"],
                        complex_mu["MU_Im_XYZ"],
                    ):
                        electromagnetic[
                            f"complex_relative_permeability_real_{axis}"
                        ] = ScalarProperty(real, "1")
                        electromagnetic[
                            f"complex_relative_permeability_imaginary_{axis}"
                        ] = ScalarProperty(imaginary, "1")
                elif (
                    complex_mu.get("MU_Re") is not None
                    and complex_mu.get("MU_Im") is not None
                ):
                    electromagnetic["complex_relative_permeability_real"] = (
                        ScalarProperty(complex_mu["MU_Re"], "1")
                    )
                    electromagnetic["complex_relative_permeability_imaginary"] = (
                        ScalarProperty(complex_mu["MU_Im"], "1")
                    )
            loss = magnetic.get("IRON_LOSS")
            if isinstance(loss, Mapping):
                if loss.get("MASS_DENSITY") is not None:
                    properties.setdefault("general", {})["density"] = ScalarProperty(
                        loss["MASS_DENSITY"], "kg/m^3"
                    )
                if loss.get("KE") is not None and loss.get("KH") is not None:
                    electromagnetic["iron_loss_ke"] = ScalarProperty(
                        loss["KE"], "W/kg/T^2/Hz^2"
                    )
                    electromagnetic["iron_loss_kh"] = ScalarProperty(
                        loss["KH"], "W/kg/T^2/Hz"
                    )
                if isinstance(loss.get("KE_XY"), list) and isinstance(
                    loss.get("KH_XYZ"), list
                ):
                    for axis, value in zip(("x", "y"), loss["KE_XY"]):
                        electromagnetic[f"iron_loss_ke_{axis}"] = ScalarProperty(
                            value, "W/kg/T^2/Hz^2"
                        )
                    for axis, value in zip(("x", "y", "z"), loss["KH_XYZ"]):
                        electromagnetic[f"iron_loss_kh_{axis}"] = ScalarProperty(
                            value, "W/kg/T^2/Hz"
                        )
        if not electromagnetic:
            properties.pop("electromagnetic", None)

        parent_ref = (
            f"{origin.material_id}@{origin.material_version}" if origin else None
        )
        return Material(
            material_id="user:emsolution_extract",
            material_version="1.0.0",
            identity=MaterialIdentity(name=name, family=family),
            properties=properties,
            provenance=Provenance(
                "USER_INPUT",
                reference=source_reference,
                notes="Extracted from an EMSolution input material snapshot",
            ),
            version_metadata=VersionMetadata(
                author=author,
                updated_at=datetime.now(UTC).isoformat(),
                change_note="Extracted from EMSolution input.json",
            ),
            parent_ref=parent_ref,
        )

    def register_from_file(
        self,
        library: MaterialManager,
        path: str | Path,
        name: str,
        *,
        family: str,
        author: str,
        new_name: str | None = None,
    ) -> Material:
        input_path = Path(path)
        origin: SnapshotOrigin | None = None
        sidecar_path = self.sidecar_path(input_path)
        if sidecar_path.exists():
            links = self.load_document(sidecar_path).get("materials", {})
            if isinstance(links, Mapping) and isinstance(links.get(name), Mapping):
                origin = SnapshotOrigin.from_dict(links[name])
        extracted = self.extract_material(
            self.load_document(input_path),
            name,
            family=family,
            author=author,
            source_reference=str(input_path),
            origin=origin,
        )
        parent_ref = (
            f"{origin.material_id}@{origin.material_version}" if origin else None
        )
        return library.create(
            name=new_name or extracted.name,
            family=family,
            author=author,
            properties=extracted.properties,
            provenance=Provenance(
                "USER_INPUT",
                reference=str(input_path),
                notes="Imported from an EMSolution input material snapshot",
            ),
            parent_ref=parent_ref,
            change_note="Imported from EMSolution input.json",
        )
