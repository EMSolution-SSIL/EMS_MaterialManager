from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from ems_material import MaterialManager, ScalarProperty
from ems_material.adapters import EMotorSolutionMaterialAdapter


EMOTOR_ROOT = os.environ.get("EMOTOR_SOLUTION_ROOT")


@unittest.skipUnless(EMOTOR_ROOT, "EMOTOR_SOLUTION_ROOT is not configured")
class EMotorSolutionBomIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(Path(EMOTOR_ROOT)))
        from eMotorSolution.CheckPoints.ManufacturingBOM import providers
        from eMotorSolution.CheckPoints.ManufacturingBOM.models import BOMDiagnostic
        from eMotorSolution.CheckPoints.ManufacturingBOM.service import (
            compute_manufacturing_bom,
        )
        from Tests.test_manufacturing_bom import _project

        cls.providers = providers
        cls.BOMDiagnostic = BOMDiagnostic
        cls.compute_manufacturing_bom = staticmethod(compute_manufacturing_bom)
        cls.representative_project = staticmethod(_project)

    @classmethod
    def tearDownClass(cls) -> None:
        if EMOTOR_ROOT in sys.path:
            sys.path.remove(EMOTOR_ROOT)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        library = MaterialManager(self.temporary.name)
        material = library.create(
            material_id="user:integration_steel",
            name="Integration Steel",
            family="electrical_steel",
            author="test",
            updated_at="2026-09-12T00:00:00+09:00",
            properties={"general": {"density": ScalarProperty(7.65, "g/cm^3")}},
        )
        for material_id, name, density in (
            ("user:steel", "Steel", 7650.0),
            ("user:copper", "Copper", 8960.0),
            ("user:magnet", "Magnet", 7500.0),
            ("user:air", "Air", None),
        ):
            properties = (
                {"general": {"density": ScalarProperty(density, "kg/m^3")}}
                if density is not None
                else {}
            )
            library.create(
                material_id=material_id,
                name=name,
                family="integration_fixture",
                author="test",
                updated_at="2026-09-12T00:00:00+09:00",
                properties=properties,
            )
        self.adapter = EMotorSolutionMaterialAdapter(
            library,
            name_to_id={
                "50A350": material.material_id,
                "Steel": "user:steel",
                "Copper": "user:copper",
                "Magnet": "user:magnet",
                "Air": "user:air",
            },
        )

    def _provider(self, _project, name, source_path):
        return self.adapter.density_and_diagnostics(
            name,
            source_path,
            diagnostic_factory=self.BOMDiagnostic,
        )

    def test_real_bom_material_item_uses_library_density_for_mass(self) -> None:
        with patch.object(
            self.providers, "density_and_diagnostics", side_effect=self._provider
        ):
            item = self.providers._material_item(
                object(),
                volume=2.0e-6,
                item_id="stator_lamination",
                component_type="stator_lamination",
                source_path="stator.lamination",
                material_name="50A350",
            )

        self.assertEqual(item.status.value, "COMPLETE")
        self.assertAlmostEqual(item.mass_kg, 0.0153)
        self.assertEqual(item.diagnostics, ())

    def test_real_bom_material_item_keeps_volume_when_density_is_missing(self) -> None:
        with patch.object(
            self.providers, "density_and_diagnostics", side_effect=self._provider
        ):
            item = self.providers._material_item(
                object(),
                volume=3.0e-6,
                item_id="rotor_magnet",
                component_type="magnet",
                source_path="rotor.magnet",
                material_name="Unknown",
            )

        self.assertEqual(item.status.value, "PARTIAL")
        self.assertEqual(item.material_volume_m3, 3.0e-6)
        self.assertIsNone(item.mass_kg)
        self.assertIsInstance(item.diagnostics[0], self.BOMDiagnostic)
        self.assertEqual(item.diagnostics[0].code, "material_not_found")

    def test_representative_motor_uses_library_for_all_required_masses(self) -> None:
        project = self.representative_project()
        with patch.object(
            self.providers, "density_and_diagnostics", side_effect=self._provider
        ):
            result = self.compute_manufacturing_bom(project)

        by_id = {item.item_id: item for item in result.items}
        expected_density = {
            "stator_lamination": 7650.0,
            "rotor_lamination": 7650.0,
            "winding_copper": 8960.0,
            "rotor_magnet_1": 7500.0,
        }
        for item_id, density in expected_density.items():
            item = by_id[item_id]
            self.assertEqual(item.status.value, "COMPLETE")
            self.assertAlmostEqual(item.mass_kg, item.material_volume_m3 * density)
        self.assertIsNotNone(result.total_mass_kg)


if __name__ == "__main__":
    unittest.main()
