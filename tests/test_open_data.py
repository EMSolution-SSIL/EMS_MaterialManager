from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ems_material import (
    CandidateCatalog,
    OpenDataImportError,
    SourceManifest,
    import_csv_recipe,
    sha256_file,
)


class OpenDataImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        raw = self.root / "raw" / "copper.csv"
        raw.parent.mkdir()
        raw.write_text("temperature_k,k_w_mk\n273,401\n300,398\n", encoding="utf-8")
        digest = sha256_file(raw)
        (self.root / "source_manifest.json").write_text(
            json.dumps(
                {
                    "schema": "ems_open_material_source_manifest",
                    "schema_version": "1.0",
                    "dataset_id": "test_copper_v1",
                    "repository": "Test repository",
                    "title": "Test copper table",
                    "source_url": "https://example.invalid/copper",
                    "record_version": "v1",
                    "license": "CC-BY-4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "license_status": "VERIFIED_RECORD_VERSION",
                    "attribution": "Test Author, Test copper table, CC BY 4.0",
                    "files": [{"path": "raw/copper.csv", "sha256": digest}],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "import_recipe.json").write_text(
            json.dumps(
                {
                    "schema": "ems_open_material_import_recipe",
                    "schema_version": "1.0",
                    "dataset_id": "test_copper_v1",
                    "manifest": "source_manifest.json",
                    "source": {"path": "raw/copper.csv", "format": "csv"},
                    "author": "EMS Open Data Import",
                    "updated_at": "2026-09-16T00:00:00+00:00",
                    "material": {
                        "material_id": "open:test_copper_v1:thermal_v1",
                        "material_version": "1.0.0",
                        "name": "Copper thermal reference",
                        "family": "conductor",
                        "variant_id": "v1",
                    },
                    "mappings": [
                        {
                            "property": "thermal.thermal_conductivity_vs_temperature",
                            "kind": "curve",
                            "x_column": "temperature_k",
                            "y_column": "k_w_mk",
                            "x": {"name": "Temperature", "unit": "K"},
                            "y": {"name": "Thermal Conductivity", "unit": "W/(m*K)"},
                            "conditions": {"sample_state": "reference"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_manifest_verification_and_csv_recipe_preserve_traceability(self) -> None:
        manifest = SourceManifest.load(self.root / "source_manifest.json")
        manifest.verify_files(self.root)

        result = import_csv_recipe(self.root / "import_recipe.json")
        curve = result.material.get_property(
            "thermal.thermal_conductivity_vs_temperature"
        )

        self.assertEqual(curve.x.values, (273.0, 300.0))
        self.assertEqual(curve.conditions["sample_state"].value, "reference")
        self.assertEqual(curve.source.raw_path, "raw/copper.csv")
        self.assertEqual(
            curve.source.sha256, sha256_file(self.root / "raw" / "copper.csv")
        )
        self.assertFalse(result.report["release_allowed"])

    def test_unverified_manifest_cannot_produce_candidate(self) -> None:
        path = self.root / "source_manifest.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["license_status"] = "UNVERIFIED"
        path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaises(OpenDataImportError):
            import_csv_recipe(self.root / "import_recipe.json")

    def test_candidate_catalog_requires_unique_ids(self) -> None:
        path = self.root / "candidates.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "ems_open_material_dataset_candidate_catalog",
                    "schema_version": "1.0",
                    "datasets": [
                        {"id": "one", "title": "One", "license": "CC-BY-4.0"},
                        {"id": "one", "title": "Duplicate", "license": "CC-BY-4.0"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(OpenDataImportError):
            CandidateCatalog.load(path)

if __name__ == "__main__":
    unittest.main()
