from __future__ import annotations

import tempfile
import unittest

from ems_material import (
    Axis,
    CurveProperty,
    ExportSelection,
    MaterialManager,
    ScalarProperty,
)
from ems_material.adapters import EMotorSolutionProjectAdapter


def _curve(scale: float = 1.0) -> CurveProperty:
    return CurveProperty(
        Axis("H", "A/m", (0.0, 100.0, 1000.0)),
        Axis("B", "T", (0.0, 1.0 * scale, 1.5 * scale)),
    )


class EMotorSolutionProjectAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.library = MaterialManager(self.temporary.name)
        self.material = self.library.create(
            material_id="user:motor_steel",
            name="Motor Steel",
            family="electrical_steel",
            author="tester",
            properties={
                "general": {"density": ScalarProperty(7650, "kg/m^3")},
                "electromagnetic": {
                    "electrical_conductivity": ScalarProperty(2.1e6, "S/m"),
                    "relative_permeability": ScalarProperty(1200, "1"),
                    "BH_curve": _curve(),
                    "BH_curve_x": _curve(),
                    "BH_curve_y": _curve(0.9),
                    "iron_loss_ke": ScalarProperty(1.5e-4, "W/kg/T^2/Hz^2"),
                    "iron_loss_kh": ScalarProperty(2.0e-2, "W/kg/T^2/Hz"),
                },
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exports_values_used_by_update_input_control(self) -> None:
        payload = (
            EMotorSolutionProjectAdapter()
            .export_material(self.material)
            .embedded_payload()
        )

        self.assertEqual(payload["type"], "non_magnet")
        self.assertEqual(payload["permeability_type"], "nonlinear")
        self.assertEqual(payload["permeability"]["_data"][1], [100.0, 1.0])
        self.assertEqual(float(payload["_conductivity_expression"]), 2.1e6)
        self.assertEqual(
            float(payload["manufacturing"]["_mass_density_expression"]), 7650
        )
        self.assertEqual(payload["iron_loss"]["type"], "yamazaki")
        self.assertIn("_ems_material_origin", payload)

    def test_roundtrip_and_registration_preserve_parent_reference(self) -> None:
        adapter = EMotorSolutionProjectAdapter()
        payload = adapter.export_material(
            self.material,
            selection=ExportSelection(permeability="linear", iron_loss="none"),
        ).embedded_payload()
        imported = adapter.register_payload(
            self.library,
            payload,
            author="product user",
            family="electrical_steel",
            name="Modified Motor Steel",
        )

        self.assertEqual(imported.parent_ref, "user:motor_steel@1.0.0")
        self.assertEqual(imported.provenance.source_type, "USER_INPUT")
        self.assertEqual(
            imported.get_property("electromagnetic.relative_permeability").value,
            1200,
        )

    def test_directional_curves_are_auto_selected_when_isotropic_is_absent(
        self,
    ) -> None:
        directional = self.material.without_property(
            "electromagnetic.BH_curve"
        ).without_property("electromagnetic.relative_permeability")

        payload = EMotorSolutionProjectAdapter().export_material(directional).payload

        self.assertEqual(payload["permeability_type"], "anisotropic nonlinear")
        self.assertEqual(payload["permeability"]["_x_data"][1], [100.0, 1.0])
        self.assertEqual(payload["permeability"]["_y_data"][1], [100.0, 0.9])


if __name__ == "__main__":
    unittest.main()
