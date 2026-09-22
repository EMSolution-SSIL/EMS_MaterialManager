from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ems_material import (
    Axis,
    CurveProperty,
    MaterialManager,
    ModelValidationError,
    PropertyNotFoundError,
    ScalarProperty,
    load_material,
    resolve_magnetic_characteristic,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "test_steel.material.json"


class MagneticCharacteristicTests(unittest.TestCase):
    def test_bh_curve_takes_precedence_over_relative_permeability(self) -> None:
        material = load_material(EXAMPLE).with_property(
            "electromagnetic.relative_permeability",
            ScalarProperty(250.0, "1"),
        )

        selected = resolve_magnetic_characteristic(material)

        self.assertEqual(selected.kind, "bh_curve")
        self.assertEqual(selected.path, "electromagnetic.BH_curve")
        self.assertIsInstance(selected.value, CurveProperty)

    def test_soft_magnetic_template_uses_default_mu_r_when_bh_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = MaterialManager(temporary)
            material = library.create_from_template(
                material_id="user:sus",
                name="SUS",
                family="soft_magnetic_material",
                author="tester",
                updated_at="2026-09-13T00:00:00+09:00",
            )

            selected = library.get_magnetic_characteristic(material.material_id)

            self.assertEqual(selected.kind, "relative_permeability")
            self.assertEqual(selected.value.value, 1.0)
            self.assertEqual(selected.value.unit, "1")

    def test_present_wrongly_typed_bh_property_does_not_fall_back(self) -> None:
        material = load_material(EXAMPLE)
        electromagnetic = dict(material.properties["electromagnetic"])
        electromagnetic["BH_curve"] = ScalarProperty(1.0, "1")
        malformed = replace(
            material,
            properties={**material.properties, "electromagnetic": electromagnetic},
        )

        with self.assertRaises(ModelValidationError):
            resolve_magnetic_characteristic(malformed)

    def test_missing_bh_and_mu_r_is_reported(self) -> None:
        material = load_material(EXAMPLE).without_property(
            "electromagnetic.BH_curve"
        )

        with self.assertRaises(PropertyNotFoundError):
            resolve_magnetic_characteristic(material)


if __name__ == "__main__":
    unittest.main()
