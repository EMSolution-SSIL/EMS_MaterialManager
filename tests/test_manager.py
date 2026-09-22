from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ems_material import (
    MaterialManager,
    ModelValidationError,
    ScalarProperty,
    VersionMetadata,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE = ROOT / "tests" / "fixtures" / "legacy_synthetic_steel.json"
UPDATED_AT = "2026-09-12T00:00:00+09:00"


class MaterialManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.library = MaterialManager(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_user_material_lifecycle_through_public_api(self) -> None:
        created = self.library.create(
            material_id="user:copper_test",
            name="Copper Test",
            family="electrical_conductor",
            author="tester",
            updated_at=UPDATED_AT,
            tags=("poc",),
        )
        edited = replace(
            created.with_property("general.density", ScalarProperty(8.96, "g/cm3")),
            material_version="1.1.0",
            version_metadata=VersionMetadata("tester", UPDATED_AT, "Added density"),
        )
        self.library.update(edited, expected_version="1.0.0")
        duplicate = self.library.duplicate(
            edited.id,
            new_material_id="user:copper_test_copy",
            new_name="Copper Test Copy",
            author="tester",
            updated_at=UPDATED_AT,
        )

        self.assertEqual(self.library.get_property(edited.id, "general.density").to_unit("kg/m^3"), 8960.0)
        self.assertTrue(self.library.validate(edited.id, "manufacturing_bom").valid)
        self.assertEqual(len(self.library.search(text="copper")), 2)
        self.library.delete(duplicate.id)
        self.assertEqual(self.library.list(), (edited,))
        self.assertEqual(edited.identity.family, "conductor")

    def test_generated_id_is_stable_after_creation(self) -> None:
        created = self.library.create(
            name="日本語材料",
            family="unknown",
            author="tester",
            updated_at=UPDATED_AT,
        )

        self.assertTrue(created.id.startswith("user:material_"))
        self.assertEqual(self.library.get(created.id).id, created.id)

    def test_legacy_import_is_available_from_public_api(self) -> None:
        result = self.library.import_legacy_json(
            LEGACY_FIXTURE,
            material_id="legacy:synthetic_steel",
            family="electrical_steel",
            author="tester",
            updated_at=UPDATED_AT,
            source_type="REFERENCE",
        )

        self.assertEqual(result.material.name, "Synthetic Legacy Steel")
        self.assertEqual(self.library.get("legacy:synthetic_steel"), result.material)

    def test_public_create_rejects_invalid_catalog_property(self) -> None:
        with self.assertRaises(ModelValidationError):
            self.library.create(
                name="Invalid sheet",
                family="electrical_steel",
                author="tester",
                updated_at=UPDATED_AT,
                properties={
                    "manufacturing": {
                        "sheet_thickness": ScalarProperty(1.0, "kg/m^3")
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
