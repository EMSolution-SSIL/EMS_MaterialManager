from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ems_material import (
    ConfiguredMaterialRepository,
    CurveProperty,
    ManagerConfigurationError,
    MaterialManager,
    Provenance,
    ReadOnlyMaterialError,
    load_material,
    save_material,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "test_steel.material.json"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def source_config(name: str, files: list[str]) -> dict:
    return {
        "schema": "ems_material_source_config",
        "schema_version": "1.0",
        "name": name,
        "files": files,
    }


def library_config(sources: list[dict], default: str | None = None) -> dict:
    return {
        "schema": "ems_material_manager_config",
        "schema_version": "1.0",
        "default_write_source": default,
        "sources": sources,
    }


class ConfiguredMaterialRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.material = load_material(EXAMPLE)

    def test_only_enabled_sources_and_listed_files_are_visible(self) -> None:
        write_json(
            self.root / "manager.config.json",
            library_config(
                [
                    {"path": "Visible", "enabled": True, "writable": False},
                    {"path": "Disabled", "enabled": False, "writable": False},
                ]
            ),
        )
        write_json(
            self.root / "Visible" / "source.config.json",
            source_config("Visible source", ["selected.material.json"]),
        )
        selected = replace(
            self.material,
            material_id="reference:selected",
            provenance=Provenance("REFERENCE"),
        )
        save_material(selected, self.root / "Visible" / "selected.material.json")
        save_material(
            replace(selected, material_id="reference:unlisted"),
            self.root / "Visible" / "unlisted.material.json",
        )
        save_material(
            replace(selected, material_id="reference:orphan"),
            self.root / "Orphan" / "orphan.material.json",
        )

        repository = ConfiguredMaterialRepository(self.root)

        self.assertEqual(repository.list(), (selected,))
        self.assertEqual(repository.source_for(selected.material_id), "Visible source")
        self.assertFalse(repository.is_writable(selected.material_id))

    def test_user_crud_updates_writable_source_file_allow_list(self) -> None:
        write_json(
            self.root / "manager.config.json",
            library_config(
                [{"path": "User", "enabled": True, "writable": True}],
                default="User",
            ),
        )
        write_json(
            self.root / "User" / "source.config.json",
            source_config("User materials", []),
        )
        library = MaterialManager(self.root)

        created = library.create(
            material_id="user:configured",
            name="Configured material",
            family="test",
            author="tester",
            updated_at="2026-09-12T00:00:00+09:00",
        )

        self.assertEqual(library.get(created.material_id), created)
        self.assertTrue(library.is_writable(created.material_id))
        self.assertEqual(library.source_for(created.material_id), "User materials")
        source_data = json.loads(
            (self.root / "User" / "source.config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(source_data["files"], ["user%3Aconfigured.material.json"])

        library.delete(created.material_id)
        source_data = json.loads(
            (self.root / "User" / "source.config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(source_data["files"], [])
        self.assertEqual(library.list(), ())

    def test_reference_duplicate_is_created_in_user_source(self) -> None:
        write_json(
            self.root / "manager.config.json",
            library_config(
                [
                    {"path": "User", "enabled": True, "writable": True},
                    {"path": "Reference", "enabled": True, "writable": False},
                ],
                default="User",
            ),
        )
        write_json(
            self.root / "User" / "source.config.json",
            source_config("User", []),
        )
        write_json(
            self.root / "Reference" / "source.config.json",
            source_config("Reference", ["steel.material.json"]),
        )
        reference = replace(
            self.material,
            material_id="reference:steel",
            provenance=Provenance("REFERENCE"),
        )
        save_material(reference, self.root / "Reference" / "steel.material.json")
        library = MaterialManager(self.root)

        with self.assertRaises(ReadOnlyMaterialError):
            library.delete(reference.material_id)
        duplicate = library.duplicate(
            reference.material_id,
            new_material_id="user:steel_copy",
            new_name="Steel copy",
            author="tester",
            updated_at="2026-09-12T00:00:00+09:00",
        )

        self.assertEqual(library.source_for(duplicate.material_id), "User")
        self.assertTrue(library.is_writable(duplicate.material_id))

    def test_admin_mode_updates_but_never_deletes_reference_material(self) -> None:
        write_json(
            self.root / "manager.config.json",
            library_config(
                [{"path": "Reference", "enabled": True, "writable": False}]
            ),
        )
        write_json(
            self.root / "Reference" / "source.config.json",
            source_config("Reference", ["steel.material.json"]),
        )
        reference = replace(
            self.material,
            material_id="reference:admin_steel",
            identity=replace(self.material.identity, description="Before"),
            provenance=Provenance("REFERENCE"),
        )
        save_material(reference, self.root / "Reference" / "steel.material.json")

        normal = ConfiguredMaterialRepository(self.root)
        with self.assertRaises(ReadOnlyMaterialError):
            normal.update(reference)

        admin = ConfiguredMaterialRepository(
            self.root, allow_reference_updates=True
        )
        revised = replace(
            reference,
            identity=replace(reference.identity, description="Corrected by admin"),
        )
        admin.update(revised, expected_version=reference.material_version)

        self.assertEqual(
            admin.get(reference.material_id).identity.description,
            "Corrected by admin",
        )
        self.assertTrue(admin.is_writable(reference.material_id))
        self.assertFalse(admin.is_deletable(reference.material_id))
        with self.assertRaises(ReadOnlyMaterialError):
            admin.delete(reference.material_id)

    def test_path_traversal_is_rejected(self) -> None:
        write_json(
            self.root / "manager.config.json",
            library_config(
                [{"path": "../outside", "enabled": True, "writable": False}]
            ),
        )

        with self.assertRaisesRegex(ManagerConfigurationError, "escapes"):
            ConfiguredMaterialRepository(self.root)

    def test_checked_in_materials_folder_loads_public_example(self) -> None:
        manager = MaterialManager(ROOT / "materials")

        material_ids = {material.material_id for material in manager.list()}
        self.assertEqual(material_ids, {"example:test_steel"})
        self.assertEqual(manager.source_for("example:test_steel"), "Examples")
        self.assertFalse(manager.is_writable("example:test_steel"))

    def test_public_example_curve_preserves_points_and_units(self) -> None:
        manager = MaterialManager(ROOT / "materials")
        material = manager.get("example:test_steel")
        curve = material.get_property("electromagnetic.BH_curve")
        self.assertIsInstance(curve, CurveProperty)
        self.assertEqual(len(curve.x.values), 3)
        self.assertEqual((curve.x.unit, curve.y.unit), ("A/m", "T"))
if __name__ == "__main__":
    unittest.main()
