"""Bidirectional detached-snapshot adapter for eMotorSolution materials."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exchange import (
    ExportSelection,
    ProductMaterialSnapshot,
    origin_from_payload,
)
from ..formats import load_format_profile
from ..legacy import LegacyImportResult, import_legacy_material_document
from ..manager import MaterialManager
from ..model import Material, Provenance
from ._values import curve_points, require_values, scalar_value


class EMotorSolutionProjectAdapter:
    """Convert canonical materials to/from eMotorSolution project records."""

    profile_filename = "emotorsolution-project.v1.json"

    def __init__(self) -> None:
        self.profile = load_format_profile(self.profile_filename)
        self.format_id = str(self.profile["format_id"])

    @staticmethod
    def _manufacturing(material: Material) -> dict[str, Any]:
        density = scalar_value(material, "general.density", "kg/m^3")
        return {
            "_mass_density_expression": None if density is None else f"{density:.17g}",
            "_mass_density_unit": "kg/m^3",
            "family": material.family,
            "provenance": material.provenance.source_type,
            "manufacturer": material.identity.manufacturer or "",
            "grade": material.identity.grade or "",
            "notes": material.provenance.notes or "",
        }

    @staticmethod
    def _permeability_mode(material: Material, requested: str) -> str:
        if requested != "auto":
            return requested
        if curve_points(material, "electromagnetic.BH_curve") is not None:
            return "bh_isotropy"
        directional = tuple(
            curve_points(material, f"electromagnetic.BH_curve_{axis}")
            for axis in ("x", "y")
        )
        if all(points is not None for points in directional):
            return "bh_anisotropy"
        if (
            scalar_value(material, "electromagnetic.relative_permeability", "1")
            is not None
        ):
            return "linear"
        return "linear"

    @staticmethod
    def _iron_loss(material: Material, requested: str) -> dict[str, Any] | None:
        mode = requested
        if mode == "auto":
            iso = (
                scalar_value(material, "electromagnetic.iron_loss_ke", "W/kg/T^2/Hz^2"),
                scalar_value(material, "electromagnetic.iron_loss_kh", "W/kg/T^2/Hz"),
            )
            aniso = tuple(
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
                if all(value is not None for value in iso)
                else (
                    "anisotropy"
                    if all(value is not None for value in aniso)
                    else "none"
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
                        "Ke",
                        scalar_value(
                            material, "electromagnetic.iron_loss_ke", "W/kg/T^2/Hz^2"
                        ),
                    ),
                    (
                        "Kh",
                        scalar_value(
                            material, "electromagnetic.iron_loss_kh", "W/kg/T^2/Hz"
                        ),
                    ),
                )
            )
            return {
                "type": "yamazaki",
                "_ke_expression": f"{values['Ke']:.17g}",
                "_ke_unit": "W/kg/T^2/Hz^2",
                "_kh_expression": f"{values['Kh']:.17g}",
                "_kh_unit": "W/kg/T^2/Hz",
                "_mass_density_expression": f"{density:.17g}",
                "_mass_density_unit": "kg/m^3",
            }
        if mode != "anisotropy":
            raise ValueError(f"Unsupported iron-loss mode: {mode}")
        values = require_values(
            (
                (
                    "Ke_X",
                    scalar_value(
                        material, "electromagnetic.iron_loss_ke_x", "W/kg/T^2/Hz^2"
                    ),
                ),
                (
                    "Ke_Y",
                    scalar_value(
                        material, "electromagnetic.iron_loss_ke_y", "W/kg/T^2/Hz^2"
                    ),
                ),
                (
                    "Kh_X",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_x", "W/kg/T^2/Hz"
                    ),
                ),
                (
                    "Kh_Y",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_y", "W/kg/T^2/Hz"
                    ),
                ),
                (
                    "Kh_Z",
                    scalar_value(
                        material, "electromagnetic.iron_loss_kh_z", "W/kg/T^2/Hz"
                    ),
                ),
            )
        )
        return {
            "type": "anisotropic_yamazaki",
            "_ke_x_expression": f"{values['Ke_X']:.17g}",
            "_ke_x_unit": "W/kg/T^2/Hz^2",
            "_ke_y_expression": f"{values['Ke_Y']:.17g}",
            "_ke_y_unit": "W/kg/T^2/Hz^2",
            "_kh_x_expression": f"{values['Kh_X']:.17g}",
            "_kh_x_unit": "W/kg/T^2/Hz",
            "_kh_y_expression": f"{values['Kh_Y']:.17g}",
            "_kh_y_unit": "W/kg/T^2/Hz",
            "_kh_z_expression": f"{values['Kh_Z']:.17g}",
            "_kh_z_unit": "W/kg/T^2/Hz",
            "_mass_density_expression": f"{density:.17g}",
            "_mass_density_unit": "kg/m^3",
        }

    def _non_magnet_payload(
        self, material: Material, selection: ExportSelection
    ) -> dict[str, Any]:
        conductivity = scalar_value(
            material, "electromagnetic.electrical_conductivity", "S/m"
        )
        if conductivity is None:
            resistivity = scalar_value(
                material, "electromagnetic.electrical_resistivity", "Ohm*m"
            )
            conductivity = 0.0 if resistivity is None else 1.0 / resistivity
        mode = self._permeability_mode(material, selection.permeability)
        if mode == "linear":
            mu = scalar_value(material, "electromagnetic.relative_permeability", "1")
            permeability = {
                "_relative_permeability_expression": f"{(mu if mu is not None else 1.0):.17g}"
            }
            permeability_type = "linear"
        elif mode == "bh_isotropy":
            points = curve_points(material, "electromagnetic.BH_curve")
            if points is None:
                raise ValueError("electromagnetic.BH_curve is required")
            permeability = {"_b_unit": "T", "_h_unit": "A/m", "_data": points}
            permeability_type = "nonlinear"
        elif mode == "bh_anisotropy":
            x_points = curve_points(material, "electromagnetic.BH_curve_x")
            y_points = curve_points(material, "electromagnetic.BH_curve_y")
            if x_points is None or y_points is None:
                raise ValueError(
                    "BH_curve_x and BH_curve_y are required for eMotorSolution anisotropy"
                )
            permeability = {
                "_b_unit": "T",
                "_h_unit": "A/m",
                "_x_data": x_points,
                "_y_data": y_points,
            }
            permeability_type = "anisotropic nonlinear"
        else:
            raise ValueError(
                f"Permeability mode {mode!r} is not verified for eMotorSolution format v1"
            )
        return {
            "type": "non_magnet",
            "name": material.name,
            "_conductivity_expression": f"{conductivity:.17g}",
            "_conductivity_unit": "S/m",
            "permeability_type": permeability_type,
            "permeability": permeability,
            "manufacturing": self._manufacturing(material),
            "iron_loss": self._iron_loss(material, selection.iron_loss),
        }

    def _magnet_payload(self, material: Material) -> dict[str, Any]:
        br = scalar_value(material, "electromagnetic.remanent_flux_density", "T")
        conductivity = scalar_value(
            material, "electromagnetic.electrical_conductivity", "S/m"
        )
        mu = scalar_value(material, "electromagnetic.relative_permeability", "1")
        return {
            "type": "magnet",
            "name": material.name,
            "_radial_expression": f"{(br if br is not None else 0.0):.17g}",
            "_radial_unit": "T",
            "_tangential_expression": "0",
            "_tangential_unit": "T",
            "_conductivity_expression": f"{(conductivity if conductivity is not None else 0.0):.17g}",
            "_conductivity_unit": "S/m",
            "_relative_permeability_expression": f"{(mu if mu is not None else 1.0):.17g}",
            "manufacturing": self._manufacturing(material),
        }

    def export_material(
        self,
        material: Material,
        *,
        selection: ExportSelection | None = None,
    ) -> ProductMaterialSnapshot:
        selected = selection or ExportSelection()
        payload = (
            self._magnet_payload(material)
            if material.family == "permanent_magnet"
            else self._non_magnet_payload(material, selected)
        )
        return ProductMaterialSnapshot.create(
            material,
            payload,
            adapter_format=self.format_id,
            selection=selected,
        )

    def import_legacy(
        self,
        payload: Mapping[str, Any],
        *,
        material_id: str,
        family: str,
        author: str,
        source_reference: str | None = None,
    ) -> LegacyImportResult:
        return import_legacy_material_document(
            deepcopy(dict(payload)),
            material_id=material_id,
            family=family,
            author=author,
            source_reference=source_reference,
            source_type="USER_INPUT",
        )

    def import_material(
        self,
        payload: Mapping[str, Any],
        *,
        material_id: str = "user:emotorsolution_import",
        family: str = "generic",
        author: str = "eMotorSolution",
        source_reference: str | None = None,
    ) -> Material:
        return self.import_legacy(
            payload,
            material_id=material_id,
            family=family,
            author=author,
            source_reference=source_reference,
        ).material

    def register_payload(
        self,
        library: MaterialManager,
        payload: Mapping[str, Any],
        *,
        author: str,
        family: str | None = None,
        source_reference: str | None = None,
        name: str | None = None,
    ) -> Material:
        origin = origin_from_payload(payload)
        manufacturing = payload.get("manufacturing")
        source_family = (
            manufacturing.get("family") if isinstance(manufacturing, Mapping) else None
        )
        selected_family = family or str(
            source_family
            or ("permanent_magnet" if payload.get("type") == "magnet" else "generic")
        )
        imported = self.import_material(
            payload,
            family=selected_family,
            author=author,
            source_reference=source_reference,
        )
        parent_ref = (
            f"{origin.material_id}@{origin.material_version}" if origin else None
        )
        return library.create(
            name=name or imported.name,
            family=selected_family,
            author=author,
            properties=imported.properties,
            manufacturer=imported.identity.manufacturer,
            grade=imported.identity.grade,
            provenance=Provenance(
                "USER_INPUT",
                reference=source_reference or parent_ref,
                notes="Imported from an eMotorSolution project material snapshot",
            ),
            parent_ref=parent_ref,
            change_note="Imported from eMotorSolution",
        )
