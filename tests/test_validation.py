from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from ems_material import Axis, CurveProperty, ScalarProperty, load_material, validate_material


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "test_steel.material.json"


class RequirementProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.material = load_material(EXAMPLE)

    def test_manufacturing_bom_ready(self) -> None:
        result = validate_material(self.material, "manufacturing_bom")

        self.assertTrue(result.valid)
        self.assertEqual(result.missing_required, ())

    def test_missing_density_is_normal_validation_result(self) -> None:
        without_density = replace(
            self.material,
            properties={"electromagnetic": self.material.properties["electromagnetic"]},
        )

        result = validate_material(without_density, "manufacturing_bom")

        self.assertFalse(result.valid)
        self.assertEqual(result.missing_required, ("general.density",))
        self.assertFalse(without_density.has_property("general.density"))

    def test_material_convenience_api_matches_profile_function(self) -> None:
        self.assertTrue(self.material.has_property("general.density"))
        self.assertEqual(
            self.material.validate("manufacturing_bom"),
            validate_material(self.material, "manufacturing_bom"),
        )
        self.assertEqual(self.material.family, self.material.identity.family)
        self.assertEqual(self.material.version, self.material.material_version)

    def test_density_curve_is_unsupported(self) -> None:
        invalid_type = replace(
            self.material,
            properties={
                **self.material.properties,
                "general": {
                    "density": CurveProperty(
                        Axis("x", "K", (0.0, 1.0)),
                        Axis("density", "kg/m^3", (1.0, 2.0)),
                    )
                },
            },
        )

        result = validate_material(invalid_type, "manufacturing_bom")

        self.assertFalse(result.valid)
        self.assertTrue(result.unsupported)

    def test_non_density_unit_is_unsupported(self) -> None:
        wrong_unit = replace(
            self.material,
            properties={
                **self.material.properties,
                "general": {"density": ScalarProperty(7650.0, "Pa")},
            },
        )

        result = validate_material(wrong_unit, "manufacturing_bom")

        self.assertFalse(result.valid)
        self.assertTrue(result.unsupported)

    def test_unknown_profile_is_unsupported(self) -> None:
        result = validate_material(self.material, "unknown_profile")

        self.assertFalse(result.valid)
        self.assertTrue(result.unsupported)


if __name__ == "__main__":
    unittest.main()
