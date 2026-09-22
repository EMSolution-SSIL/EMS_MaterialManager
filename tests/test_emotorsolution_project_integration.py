from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ems_material import Axis, CurveProperty, MaterialManager, ScalarProperty
from ems_material.adapters import EMotorSolutionProjectAdapter

EMOTOR_ROOT = os.environ.get("EMOTOR_SOLUTION_ROOT")


@unittest.skipUnless(EMOTOR_ROOT, "EMOTOR_SOLUTION_ROOT is not configured")
class EMotorSolutionProjectIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(Path(EMOTOR_ROOT)))
        from eMotorSolution.Tools.Material import Non_Magnet_Material

        cls.Non_Magnet_Material = Non_Magnet_Material

    @classmethod
    def tearDownClass(cls) -> None:
        if EMOTOR_ROOT in sys.path:
            sys.path.remove(EMOTOR_ROOT)

    def test_snapshot_loads_and_uses_existing_update_input_control(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            material = MaterialManager(root).create(
                material_id="user:product_integration",
                name="Product Integration",
                family="electrical_steel",
                author="tester",
                properties={
                    "general": {"density": ScalarProperty(7650, "kg/m^3")},
                    "electromagnetic": {
                        "electrical_conductivity": ScalarProperty(2.0e6, "S/m"),
                        "BH_curve": CurveProperty(
                            Axis("H", "A/m", (0.0, 100.0, 1000.0)),
                            Axis("B", "T", (0.0, 1.0, 1.5)),
                        ),
                    },
                },
            )
            payload = (
                EMotorSolutionProjectAdapter()
                .export_material(material)
                .embedded_payload()
            )

        product_material = self.Non_Magnet_Material.from_dict(
            payload, SimpleNamespace(parameters={})
        )
        self.assertEqual(
            product_material.to_dict()["_ems_material_origin"]["material_id"],
            "user:product_integration",
        )
        input_control = {
            "20_BH_Curve": [],
            "16_Material_Properties": {"16_1_3D_Element_Properties": []},
        }
        product_material.update_input_control(1, product_material.name, input_control)
        entry = input_control["16_Material_Properties"]["16_1_3D_Element_Properties"][0]
        self.assertEqual(entry["ElectricProperty"]["conductivity"]["SIGMA"], 2.0e6)
        self.assertEqual(entry["MagneticProperty"]["BH_CURVE_ID"], 1)
        self.assertEqual(input_control["20_BH_Curve"][0]["data"]["B"], [0.0, 1.0, 1.5])


if __name__ == "__main__":
    unittest.main()
