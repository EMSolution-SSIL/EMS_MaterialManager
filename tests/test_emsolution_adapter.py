from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ems_material import (
    Axis,
    CurveProperty,
    ExportSelection,
    MaterialManager,
    ScalarProperty,
)
from ems_material.adapters import EMSolutionInputAdapter


def _curve(scale: float = 1.0) -> CurveProperty:
    return CurveProperty(
        Axis("H", "A/m", (0.0, 100.0, 1000.0)),
        Axis("B", "T", (0.0, scale, 1.5 * scale)),
    )


class EMSolutionInputAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = MaterialManager(self.root / "library")
        self.material = self.library.create(
            material_id="user:emsolution_steel",
            name="EMSolution Steel",
            family="electrical_steel",
            author="tester",
            properties={
                "general": {"density": ScalarProperty(7650, "kg/m^3")},
                "electrical": {
                    "relative_permittivity": ScalarProperty(4.2, "1"),
                    "complex_relative_permittivity_real": ScalarProperty(12.5, "1"),
                    "complex_relative_permittivity_imaginary": ScalarProperty(
                        0.25, "1"
                    ),
                },
                "electromagnetic": {
                    "electrical_conductivity": ScalarProperty(2.0e6, "S/m"),
                    "relative_permeability": ScalarProperty(1000, "1"),
                    "BH_curve": _curve(),
                    "BH_curve_x": _curve(),
                    "BH_curve_y": _curve(0.9),
                    "BH_curve_z": _curve(0.8),
                    "complex_relative_permeability_real": ScalarProperty(202, "1"),
                    "complex_relative_permeability_imaginary": ScalarProperty(80, "1"),
                    "iron_loss_ke": ScalarProperty(1.5e-4, "W/kg/T^2/Hz^2"),
                    "iron_loss_kh": ScalarProperty(2.0e-2, "W/kg/T^2/Hz"),
                    "iron_loss_ke_x": ScalarProperty(1.0e-4, "W/kg/T^2/Hz^2"),
                    "iron_loss_ke_y": ScalarProperty(1.1e-4, "W/kg/T^2/Hz^2"),
                    "iron_loss_kh_x": ScalarProperty(2.0e-2, "W/kg/T^2/Hz"),
                    "iron_loss_kh_y": ScalarProperty(2.1e-2, "W/kg/T^2/Hz"),
                    "iron_loss_kh_z": ScalarProperty(2.2e-2, "W/kg/T^2/Hz"),
                },
            },
        )
        self.adapter = EMSolutionInputAdapter()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_export_matches_emotorsolution_update_shape(self) -> None:
        document, _snapshot = self.adapter.apply_to_document({}, self.material)
        entry = document["16_Material_Properties"]["16_1_3D_Element_Properties"][0]

        self.assertEqual(entry["ElectricProperty"]["conductivity"]["SIGMA"], 2.0e6)
        self.assertEqual(entry["ElectricProperty"]["permittivity"]["EPS"], 4.2)
        self.assertEqual(entry["ElectricProperty"]["EPS_COMPLEX"]["EPS_Re"], 12.5)
        self.assertEqual(entry["ElectricProperty"]["EPS_COMPLEX"]["EPS_Im"], 0.25)
        self.assertEqual(entry["MagneticProperty"]["BH_CURVE_ID"], 1)
        self.assertEqual(entry["MagneticProperty"]["MU_COMPLEX"]["MU_Re"], 202)
        self.assertEqual(entry["MagneticProperty"]["IRON_LOSS"]["MASS_DENSITY"], 7650)
        self.assertEqual(document["20_BH_Curve"][0]["data"]["H"], [0.0, 100.0, 1000.0])

    def test_directional_export_uses_three_direction_profile(self) -> None:
        document, _snapshot = self.adapter.apply_to_document(
            {},
            self.material,
            selection=ExportSelection(
                permeability="bh_anisotropy", iron_loss="anisotropy"
            ),
        )
        magnetic = document["16_Material_Properties"]["16_1_3D_Element_Properties"][0][
            "MagneticProperty"
        ]

        self.assertEqual(magnetic["BH_CURVE_XYZ"]["BH_XYZ_ID"], [1, 2, 3])
        self.assertEqual(magnetic["IRON_LOSS"]["KE_XY"], [1.0e-4, 1.1e-4])
        self.assertEqual(len(document["20_BH_Curve"]), 3)

    def test_file_export_writes_lineage_sidecar_and_can_register(self) -> None:
        input_path = self.root / "input.json"
        input_path.write_text("{}\n", encoding="utf-8")
        self.adapter.apply_to_file(input_path, self.material)

        sidecar = self.adapter.sidecar_path(input_path)
        links = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(
            links["materials"]["EMSolution Steel"]["material_id"],
            "user:emsolution_steel",
        )
        registered = self.adapter.register_from_file(
            self.library,
            input_path,
            "EMSolution Steel",
            family="electrical_steel",
            author="EMSolution user",
            new_name="Modified EMSolution Steel",
        )
        self.assertEqual(registered.parent_ref, "user:emsolution_steel@1.0.0")
        self.assertEqual(
            registered.get_property("electrical.relative_permittivity").value,
            4.2,
        )
        self.assertEqual(
            registered.get_property(
                "electrical.complex_relative_permittivity_real"
            ).value,
            12.5,
        )

    def test_complex_permittivity_directional_export_and_import(self) -> None:
        material = self.material
        for axis, real, imaginary in (
            ("x", 3.0, 0.1),
            ("y", 4.0, 0.2),
            ("z", 5.0, 0.3),
        ):
            material = material.with_property(
                f"electrical.complex_relative_permittivity_real_{axis}",
                ScalarProperty(real, "1"),
            ).with_property(
                f"electrical.complex_relative_permittivity_imaginary_{axis}",
                ScalarProperty(imaginary, "1"),
            )

        document, _snapshot = self.adapter.apply_to_document({}, material)
        complex_eps = document["16_Material_Properties"]["16_1_3D_Element_Properties"][
            0
        ]["ElectricProperty"]["EPS_COMPLEX"]
        self.assertEqual(complex_eps["EPS_Re_XYZ"], [3.0, 4.0, 5.0])
        self.assertEqual(complex_eps["EPS_Im_XYZ"], [0.1, 0.2, 0.3])

        extracted = self.adapter.extract_material(
            document,
            material.name,
            family="electrical_steel",
            author="EMSolution user",
        )
        self.assertEqual(
            extracted.get_property(
                "electrical.complex_relative_permittivity_imaginary_z"
            ).value,
            0.3,
        )

    def test_mh_curve_is_not_silently_exported_as_an_emsolution_bh_curve(self) -> None:
        magnet = self.library.create(
            material_id="user:mh_magnet",
            name="M-H Reference Magnet",
            family="permanent_magnet",
            author="tester",
            properties={
                "general": {"density": ScalarProperty(7500.0, "kg/m^3")},
                "electromagnetic": {
                    "relative_permeability": ScalarProperty(1.05, "1"),
                    "MH_curve": CurveProperty(
                        Axis("H", "A/m", (0.0, 100.0, 1000.0)),
                        Axis("M", "A/m", (0.0, 1.0e5, 8.0e5)),
                    ),
                },
            },
        )

        document, _snapshot = self.adapter.apply_to_document({}, magnet)
        magnetic = document["16_Material_Properties"]["16_1_3D_Element_Properties"][0][
            "MagneticProperty"
        ]

        self.assertNotIn("BH_CURVE_ID", magnetic)
        self.assertEqual(document["20_BH_Curve"], [])


if __name__ == "__main__":
    unittest.main()
