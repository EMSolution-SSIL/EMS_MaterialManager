from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from ems_material import (
    CurveProperty,
    LegacyImportError,
    ScalarProperty,
    import_legacy_material_document,
    load_legacy_material,
    material_from_json,
    material_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_synthetic_steel.json"
UPDATED_AT = "2026-09-12T00:00:00+09:00"


def import_fixture():
    return load_legacy_material(
        FIXTURE,
        material_id="legacy:synthetic_steel",
        family="electrical_steel",
        author="migration-test",
        updated_at=UPDATED_AT,
        source_type="REFERENCE",
    )


class LegacySyntheticSteelTests(unittest.TestCase):
    def test_synthetic_fixture_import_preserves_curve_and_units(self) -> None:
        result = import_fixture()
        material = result.material
        curve = material.get_property("electromagnetic.BH_curve")
        conductivity = material.get_property("electromagnetic.electrical_conductivity")

        self.assertEqual(result.source_format, "emotorsolution_material_public_keys")
        self.assertEqual(material.name, "Synthetic Legacy Steel")
        self.assertIsInstance(curve, CurveProperty)
        self.assertEqual(curve.x.unit, "A/m")
        self.assertEqual(curve.y.unit, "T")
        self.assertEqual(len(curve.x.values), 4)
        self.assertEqual((curve.x.values[0], curve.y.values[0]), (0.0, 0.0))
        self.assertEqual((curve.x.values[-1], curve.y.values[-1]), (1000.0, 1.5))
        self.assertIsInstance(conductivity, ScalarProperty)
        self.assertEqual(conductivity.unit, "S/m")

    def test_legacy_to_canonical_to_reload_is_semantically_equal(self) -> None:
        migrated = import_fixture().material
        reloaded = material_from_json(material_to_json(migrated))

        self.assertEqual(reloaded, migrated)
        self.assertEqual(reloaded.to_dict(), migrated.to_dict())

    def test_private_project_key_shape_is_also_accepted(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        permeability = document["permeability"]
        for public in ("data", "b_unit", "h_unit"):
            permeability[f"_{public}"] = permeability.pop(public)

        result = import_legacy_material_document(
            document,
            material_id="legacy:private_synthetic_steel",
            family="electrical_steel",
            author="migration-test",
            updated_at=UPDATED_AT,
        )

        self.assertEqual(result.source_format, "emotorsolution_material_private_keys")
        curve = result.material.get_property("electromagnetic.BH_curve")
        self.assertEqual(len(curve.x.values), 4)

    def test_product_expression_is_rejected_without_eval(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        document["_conductivity_expression"] = "sigma_parameter * 2"

        with self.assertRaises(LegacyImportError):
            import_legacy_material_document(
                document,
                material_id="legacy:expression",
                family="electrical_steel",
                author="migration-test",
                updated_at=UPDATED_AT,
            )

    def test_encrypted_material_is_explicitly_out_of_scope(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        document["permeability_type"] = "encrypted nonlinear"

        with self.assertRaisesRegex(LegacyImportError, "outside the PoC scope"):
            import_legacy_material_document(
                document,
                material_id="legacy:protected",
                family="electrical_steel",
                author="migration-test",
                updated_at=UPDATED_AT,
            )

    def test_legacy_iron_loss_density_is_migrated_with_warning(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        document["iron_loss"] = {
            "type": "yamazaki",
            "_ke_expression": "0.01",
            "_ke_unit": "W/kg/T^2/Hz^2",
            "_kh_expression": "0.02",
            "_kh_unit": "W/kg/T^2/Hz",
            "_mass_density_expression": "7650",
            "_mass_density_unit": "kg/m^3"
        }

        result = import_legacy_material_document(
            document,
            material_id="legacy:with_density",
            family="electrical_steel",
            author="migration-test",
            updated_at=UPDATED_AT,
        )

        density = result.material.get_property("general.density")
        self.assertEqual(density.to_unit("kg/m^3"), 7650.0)
        self.assertTrue(any("iron-loss" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
