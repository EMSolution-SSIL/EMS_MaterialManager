from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ems_material import MaterialManager, ScalarProperty
from ems_material.property_catalog import (
    PROPERTY_CATEGORIES,
    PROPERTY_DEFINITIONS,
    PROPERTY_SUBCATEGORIES,
    property_applies_to_family,
    property_definition,
)


class PropertyCatalogTests(unittest.TestCase):
    def test_paths_are_unique_and_categories_exist(self) -> None:
        category_keys = {category.key for category in PROPERTY_CATEGORIES}
        paths = [definition.path.casefold() for definition in PROPERTY_DEFINITIONS]

        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(
            all(
                definition.category in category_keys
                for definition in PROPERTY_DEFINITIONS
            )
        )

    def test_catalog_contains_bom_and_emotor_reference_properties(self) -> None:
        density = property_definition("general.density")
        bh_curve = property_definition("electromagnetic.bh_curve")
        mh_curve = property_definition("electromagnetic.MH_curve")
        iron_loss = property_definition("electromagnetic.iron_loss_ke")

        self.assertEqual(density.required_profiles, ("manufacturing_bom",))
        self.assertEqual(bh_curve.path, "electromagnetic.BH_curve")
        self.assertEqual((bh_curve.x_unit, bh_curve.y_unit), ("A/m", "T"))
        self.assertEqual(mh_curve.path, "electromagnetic.MH_curve")
        self.assertEqual((mh_curve.x_unit, mh_curve.y_unit), ("A/m", "A/m"))
        self.assertTrue(property_applies_to_family(mh_curve, "permanent_magnet"))
        self.assertFalse(property_applies_to_family(mh_curve, "electrical_steel"))
        self.assertEqual(iron_loss.unit, "W/kg/T^2/Hz^2")
        self.assertTrue(iron_loss.note_recommended)
        self.assertIn("representative magnetic flux density", iron_loss.note_guidance)

        thickness = property_definition("manufacturing.sheet_thickness")
        self.assertEqual(thickness.unit, "m")
        self.assertTrue(property_applies_to_family(thickness, "electrical_steel"))
        self.assertFalse(property_applies_to_family(thickness, "gas"))

    def test_iron_loss_definitions_are_split_into_isotropy_and_anisotropy(self) -> None:
        subcategories = {
            subcategory.key: subcategory for subcategory in PROPERTY_SUBCATEGORIES
        }
        self.assertIn("iron_loss_isotropy", subcategories)
        self.assertIn("iron_loss_anisotropy", subcategories)
        self.assertEqual(subcategories["iron_loss_isotropy"].category, "magnetic")
        self.assertEqual(subcategories["iron_loss_anisotropy"].category, "magnetic")
        members = {
            definition.subcategory: definition.label
            for definition in PROPERTY_DEFINITIONS
            if definition.category == "magnetic"
            and definition.subcategory
            in {
                "iron_loss_isotropy",
                "iron_loss_anisotropy",
            }
        }
        self.assertEqual(
            [
                definition.label
                for definition in PROPERTY_DEFINITIONS
                if definition.subcategory == "iron_loss_isotropy"
            ],
            ["Ke", "Kh"],
        )
        self.assertEqual(
            [
                definition.label
                for definition in PROPERTY_DEFINITIONS
                if definition.subcategory == "iron_loss_anisotropy"
            ],
            ["Ke_X", "Ke_Y", "Kh_X", "Kh_Y", "Kh_Z"],
        )
        self.assertIn("iron_loss_anisotropy", members)

    def test_material_can_store_both_iron_loss_coefficient_sets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = MaterialManager(Path(directory))
            coefficients = {
                "iron_loss_ke": ScalarProperty(
                    1.0, "W/kg/T^2/Hz^2", note="Representative B=1.5 T"
                ),
                "iron_loss_kh": ScalarProperty(
                    2.0, "W/kg/T^2/Hz", note="Representative B=1.5 T"
                ),
                "iron_loss_ke_x": ScalarProperty(3.0, "W/kg/T^2/Hz^2"),
                "iron_loss_ke_y": ScalarProperty(4.0, "W/kg/T^2/Hz^2"),
                "iron_loss_kh_x": ScalarProperty(5.0, "W/kg/T^2/Hz"),
                "iron_loss_kh_y": ScalarProperty(6.0, "W/kg/T^2/Hz"),
                "iron_loss_kh_z": ScalarProperty(7.0, "W/kg/T^2/Hz"),
            }
            material = library.create(
                name="Iron loss test",
                family="electrical_steel",
                author="tester",
                properties={"electromagnetic": coefficients},
            )
            reloaded = library.get(material.material_id)

        self.assertEqual(set(reloaded.properties["electromagnetic"]), set(coefficients))
        self.assertEqual(
            reloaded.get_property("electromagnetic.iron_loss_ke").note,
            "Representative B=1.5 T",
        )


if __name__ == "__main__":
    unittest.main()
