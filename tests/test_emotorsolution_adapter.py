from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import unittest

from ems_material import MaterialManager, ScalarProperty
from ems_material.adapters import EMotorSolutionMaterialAdapter


UPDATED_AT = "2026-09-12T00:00:00+09:00"


class EMotorSolutionMaterialAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.library = MaterialManager(self.temporary.name)
        material = self.library.create(
            material_id="user:test_steel",
            name="Test Steel",
            family="electrical_steel",
            author="tester",
            updated_at=UPDATED_AT,
            properties={"general": {"density": ScalarProperty(7.65, "g/cm3")}},
        )
        self.material = material

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_explicit_name_mapping_resolves_density_in_si(self) -> None:
        adapter = EMotorSolutionMaterialAdapter(
            self.library,
            name_to_id={"50A350": self.material.id},
        )

        result = adapter.density_for_assignment("50A350", source_path="stator.lamination")

        self.assertEqual(result.material_id, self.material.id)
        self.assertEqual(result.density_kg_m3, 7650.0)
        self.assertEqual(result.source, "library")
        self.assertEqual(result.diagnostics, ())

    def test_canonical_id_and_exact_name_are_supported(self) -> None:
        adapter = EMotorSolutionMaterialAdapter(self.library)

        by_id = adapter.density_for_assignment(self.material.id)
        by_name = adapter.density_for_assignment(self.material.name)

        self.assertEqual(by_id.density_kg_m3, 7650.0)
        self.assertEqual(by_name.density_kg_m3, 7650.0)

    def test_explicit_library_material_missing_density_does_not_fallback(self) -> None:
        incomplete = self.library.create(
            material_id="user:incomplete",
            name="Incomplete",
            family="unknown",
            author="tester",
            updated_at=UPDATED_AT,
        )
        adapter = EMotorSolutionMaterialAdapter(
            self.library,
            name_to_id={"Legacy Name": incomplete.id},
            legacy_density_provider=lambda _: 9999.0,
        )

        result = adapter.density_for_assignment("Legacy Name")

        self.assertIsNone(result.density_kg_m3)
        self.assertEqual(result.diagnostics[0].code, "density_unavailable")

    def test_unconfigured_legacy_project_uses_legacy_fallback(self) -> None:
        adapter = EMotorSolutionMaterialAdapter(
            self.library,
            legacy_density_provider=lambda name: 8900.0 if name == "Copper" else None,
        )

        result = adapter.density_for_assignment("Copper")

        self.assertEqual(result.density_kg_m3, 8900.0)
        self.assertEqual(result.source, "legacy")

    def test_unresolved_assignment_has_machine_readable_diagnostic(self) -> None:
        adapter = EMotorSolutionMaterialAdapter(self.library)

        result = adapter.density_for_assignment("Unknown", source_path="rotor.lamination")

        self.assertIsNone(result.density_kg_m3)
        self.assertEqual(result.diagnostics[0].code, "material_not_found")
        self.assertEqual(result.diagnostics[0].source_path, "rotor.lamination")

    def test_bom_tuple_contract_accepts_product_diagnostic_factory(self) -> None:
        @dataclass(frozen=True)
        class ProductDiagnostic:
            code: str
            message: str
            severity: str
            source_path: str

        adapter = EMotorSolutionMaterialAdapter(
            self.library, name_to_id={"50A350": self.material.id}
        )

        density, diagnostics = adapter.density_and_diagnostics(
            "50A350",
            "stator.lamination",
            diagnostic_factory=ProductDiagnostic,
        )
        self.assertEqual(density, 7650.0)
        self.assertEqual(diagnostics, ())

        density, diagnostics = adapter.density_and_diagnostics(
            None,
            "rotor.magnet",
            diagnostic_factory=ProductDiagnostic,
        )
        self.assertIsNone(density)
        self.assertIsInstance(diagnostics[0], ProductDiagnostic)
        self.assertEqual(diagnostics[0].code, "material_not_found")


if __name__ == "__main__":
    unittest.main()
