from __future__ import annotations

import tempfile
import unittest

from ems_material import (
    ExportSelection,
    MaterialManager,
    ProductMaterialSnapshot,
    ScalarProperty,
    exported_payload_sha256,
    origin_from_payload,
)


class ProductMaterialSnapshotTests(unittest.TestCase):
    def test_embedded_origin_and_change_detection(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            material = MaterialManager(root).create(
                material_id="user:snapshot",
                name="Snapshot",
                family="generic",
                author="tester",
                properties={"general": {"density": ScalarProperty(1000, "kg/m^3")}},
            )
            snapshot = ProductMaterialSnapshot.create(
                material,
                {"name": "Snapshot", "value": 1},
                adapter_format="test/1",
                selection=ExportSelection(),
                exported_at="2026-09-14T00:00:00+00:00",
            )

        embedded = snapshot.embedded_payload()
        self.assertEqual(origin_from_payload(embedded), snapshot.origin)
        self.assertFalse(snapshot.is_modified(embedded))
        embedded["value"] = 2
        self.assertTrue(snapshot.is_modified(embedded))

    def test_payload_hash_ignores_origin_metadata(self) -> None:
        plain = {"a": 1, "b": [2, 3]}
        embedded = {**plain, "_ems_material_origin": {"material_id": "user:x"}}
        self.assertEqual(
            exported_payload_sha256(plain), exported_payload_sha256(embedded)
        )


if __name__ == "__main__":
    unittest.main()
