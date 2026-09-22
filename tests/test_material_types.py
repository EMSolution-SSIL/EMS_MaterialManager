from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ems_material import ManagerConfigurationError, MaterialManager, audit_material
from ems_material.material_types import (
    DEFAULT_MATERIAL_TYPE_CATALOG,
    load_catalog_bundle,
)
from ems_material.property_catalog import (
    DEFAULT_PROPERTY_CATALOG,
    DEFAULT_PROPERTY_CATALOG_PATH,
    load_property_catalog,
)

ROOT = Path(__file__).resolve().parents[1]


class MaterialTypeCatalogTests(unittest.TestCase):
    def test_default_catalog_has_versioned_types_templates_and_aliases(self) -> None:
        catalog = DEFAULT_MATERIAL_TYPE_CATALOG
        self.assertEqual(len(catalog.types), 9)
        self.assertEqual(catalog.resolve_family("magnet"), "permanent_magnet")
        self.assertEqual(catalog.resolve_family("coil_conductor"), "conductor")
        self.assertEqual(catalog.resolve_family("electrical_conductor"), "conductor")
        self.assertEqual(
            catalog.resolve_family("soft_magnetic_bulk"),
            "soft_magnetic_material",
        )
        self.assertEqual(catalog.resolve_family("carbon_steel"), "carbon_steel")
        self.assertEqual(catalog.resolve_family("insulation"), "electrical_insulator")
        magnet = catalog.template_for("permanent_magnet")
        self.assertIsNotNone(magnet)
        paths = {item.path for item in magnet.properties}
        self.assertIn("electromagnetic.remanent_flux_density", paths)
        self.assertIn("electromagnetic.coercive_field_strength", paths)
        self.assertIn("general.density", paths)
        self.assertNotIn("manufacturing.sheet_thickness", paths)

    def test_property_catalog_is_loaded_from_external_json(self) -> None:
        self.assertEqual(len(DEFAULT_PROPERTY_CATALOG.definitions), 52)
        remanence = DEFAULT_PROPERTY_CATALOG.property_definition(
            "electromagnetic.remanent_flux_density"
        )
        self.assertIsNotNone(remanence)
        self.assertEqual(remanence.unit, "T")
        dielectric = DEFAULT_PROPERTY_CATALOG.property_definition(
            "electrical.dielectric_strength"
        )
        self.assertEqual(dielectric.unit, "V/m")
        self.assertEqual(
            DEFAULT_PROPERTY_CATALOG.property_definition("electromagnetic.MU_Re").path,
            "electromagnetic.complex_relative_permeability_real",
        )
        self.assertEqual(
            DEFAULT_PROPERTY_CATALOG.property_definition("electrical.EPS_Im_Z").path,
            "electrical.complex_relative_permittivity_imaginary_z",
        )
        bh_x = DEFAULT_PROPERTY_CATALOG.property_definition(
            "electromagnetic.BH_curve_x"
        )
        self.assertEqual((bh_x.kind, bh_x.x_unit, bh_x.y_unit), ("curve", "A/m", "T"))

    def test_checked_in_library_uses_root_catalog_configuration(self) -> None:
        properties, types = load_catalog_bundle(ROOT / "materials")
        self.assertEqual(len(properties.definitions), 50)
        self.assertEqual(len(types.types), 9)
        self.assertEqual(types.types[0].label, "Electrical Steel Sheet")

    def test_template_creation_is_sparse_and_uses_canonical_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = MaterialManager(Path(temporary))
            material = library.create_from_template(
                material_id="user:ndfeb",
                name="NdFeB",
                family="magnet",
                author="tester",
                updated_at="2026-09-13T00:00:00+09:00",
            )
            self.assertEqual(material.identity.family, "permanent_magnet")
            self.assertEqual(material.properties, {})
            template = library.material_type_catalog.template_for(
                material.identity.family
            )
            self.assertEqual(
                template.property("general.density").requirement, "required"
            )
            missing = {
                issue.path
                for issue in audit_material(
                    material,
                    property_catalog=library.property_catalog,
                    material_types=library.material_type_catalog,
                )
                if issue.code == "REQUIRED_TEMPLATE_PROPERTY_MISSING"
            }
            self.assertEqual(
                missing,
                {
                    "general.density",
                    "electromagnetic.remanent_flux_density",
                    "electromagnetic.relative_permeability",
                },
            )

    def test_soft_magnetic_and_carbon_steel_templates_default_to_linear_mu_r(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = MaterialManager(Path(temporary))
            for requested_family, expected_family in (
                ("soft_magnetic_bulk", "soft_magnetic_material"),
                ("carbon_steel", "carbon_steel"),
            ):
                material = library.create_from_template(
                    name=expected_family,
                    family=requested_family,
                    author="tester",
                    updated_at="2026-09-13T00:00:00+09:00",
                )
                self.assertEqual(material.identity.family, expected_family)
                permeability = material.get_property(
                    "electromagnetic.relative_permeability"
                )
                self.assertEqual(permeability.value, 1.0)
                self.assertEqual(permeability.unit, "1")
                self.assertIn("fallback", permeability.note.casefold())

    def test_catalog_typo_is_rejected_instead_of_ignored(self) -> None:
        data = json.loads(DEFAULT_PROPERTY_CATALOG_PATH.read_text(encoding="utf-8"))
        data["properties"][0]["unti"] = "S/m"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "properties.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManagerConfigurationError):
                load_property_catalog(path)


if __name__ == "__main__":
    unittest.main()
