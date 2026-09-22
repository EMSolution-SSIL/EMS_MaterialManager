from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ems_material import (
    JsonMaterialRepository,
    MaterialAlreadyExistsError,
    MaterialConflictError,
    MaterialNotFoundError,
    Provenance,
    ReadOnlyMaterialError,
    RepositoryCorruptionError,
    VersionMetadata,
    load_material,
    save_material,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "test_steel.material.json"
UPDATED_AT = "2026-09-12T00:00:00+09:00"


class JsonMaterialRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = JsonMaterialRepository(self.temporary.name)
        self.material = load_material(EXAMPLE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_get_list_and_duplicate_id_guard(self) -> None:
        self.repository.create(self.material)

        self.assertEqual(self.repository.get(self.material.id), self.material)
        self.assertEqual(self.repository.list(), (self.material,))
        with self.assertRaises(MaterialAlreadyExistsError):
            self.repository.create(self.material)

    def test_update_uses_optimistic_version_check(self) -> None:
        self.repository.create(self.material)
        updated = replace(
            self.material,
            material_version="1.1.0",
            version_metadata=VersionMetadata("tester", UPDATED_AT, "density reviewed"),
        )

        self.repository.update(updated, expected_version="1.0.0")
        self.assertEqual(self.repository.get(self.material.id).material_version, "1.1.0")
        with self.assertRaises(MaterialConflictError):
            self.repository.update(updated, expected_version="1.0.0")

    def test_duplicate_becomes_user_material_and_tracks_parent(self) -> None:
        reference = replace(
            self.material,
            material_id="ems:test_steel",
            provenance=Provenance("EMS", reference="fixture"),
        )
        self.repository.create(reference)

        duplicate = self.repository.duplicate(
            reference.id,
            new_material_id="user:test_steel_copy",
            new_name="Test Steel Copy",
            author="tester",
            updated_at=UPDATED_AT,
        )

        self.assertEqual(duplicate.material_version, "1.0.0")
        self.assertEqual(duplicate.provenance.source_type, "USER_INPUT")
        self.assertEqual(duplicate.parent_ref, "ems:test_steel@1.0.0")
        self.assertEqual(self.repository.get(duplicate.id), duplicate)

    def test_search_filters_family_text_and_tags(self) -> None:
        self.repository.create(self.material)

        self.assertEqual(len(self.repository.search(family="ELECTRICAL_STEEL")), 1)
        self.assertEqual(len(self.repository.search(text="test steel")), 1)
        self.assertEqual(len(self.repository.search(tags=("POC",))), 1)
        self.assertEqual(self.repository.search(text="missing"), ())

    def test_user_delete_and_missing_material(self) -> None:
        self.repository.create(self.material)
        self.repository.delete(self.material.id)

        with self.assertRaises(MaterialNotFoundError):
            self.repository.get(self.material.id)

    def test_reference_material_cannot_be_deleted_or_updated(self) -> None:
        reference = replace(
            self.material,
            material_id="ems:test_steel",
            provenance=Provenance("EMS"),
        )
        self.repository.create(reference)

        with self.assertRaises(ReadOnlyMaterialError):
            self.repository.delete(reference.id)
        with self.assertRaises(ReadOnlyMaterialError):
            self.repository.update(reference)

    def test_mismatched_filename_is_reported_as_corruption(self) -> None:
        wrong_path = Path(self.temporary.name) / "wrong.material.json"
        save_material(self.material, wrong_path)

        with self.assertRaises(RepositoryCorruptionError):
            self.repository.list()

    def test_import_and_export_json(self) -> None:
        imported = self.repository.import_json(EXAMPLE)
        destination = Path(self.temporary.name) / "exports" / "material.json"

        self.repository.export_json(imported.id, destination)

        self.assertEqual(load_material(destination), imported)


if __name__ == "__main__":
    unittest.main()
