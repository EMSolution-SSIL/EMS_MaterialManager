from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from ems_material import (
    Axis,
    ConditionValue,
    CurveProperty,
    MaterialParseError,
    ModelValidationError,
    PropertyNotFoundError,
    PropertySource,
    ScalarProperty,
    SchemaValidationError,
    UnitConversionError,
    ValidityRange,
    convert_value,
    load_material,
    material_from_dict,
    material_from_json,
    material_to_json,
    save_material,
    schema_document,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "test_steel.material.json"


def valid_document() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_packaged_schema_is_a_valid_draft_2020_12_schema(self) -> None:
        Draft202012Validator.check_schema(schema_document())

    def test_missing_required_field_reports_path(self) -> None:
        document = valid_document()
        del document["identity"]["family"]

        with self.assertRaises(SchemaValidationError) as caught:
            material_from_dict(document)

        self.assertTrue(any("identity" in issue for issue in caught.exception.issues))

    def test_unknown_structural_field_is_rejected(self) -> None:
        document = valid_document()
        document["typo_field"] = 1

        with self.assertRaises(SchemaValidationError):
            material_from_dict(document)

    def test_malformed_json_has_a_parse_error(self) -> None:
        with self.assertRaises(MaterialParseError):
            material_from_json('{"schema":')


class UnitTests(unittest.TestCase):
    def test_density_g_per_cm3_to_kg_per_m3(self) -> None:
        self.assertAlmostEqual(convert_value(7.65, "g/cm3", "kg/m^3"), 7650.0)

    def test_legacy_density_spelling_is_accepted(self) -> None:
        self.assertEqual(convert_value(7650, "kg/m3", "kg/m^3"), 7650.0)

    def test_temperature_offset_conversion(self) -> None:
        self.assertAlmostEqual(convert_value(20.0, "degC", "K"), 293.15)

    def test_dielectric_strength_conversion(self) -> None:
        self.assertEqual(convert_value(1.0, "MV/m", "V/m"), 1_000_000.0)

    def test_inverse_temperature_alias(self) -> None:
        self.assertEqual(convert_value(1.0, "1/degC", "1/K"), 1.0)

    def test_cross_dimension_conversion_is_rejected(self) -> None:
        with self.assertRaises(UnitConversionError):
            convert_value(1.0, "T", "A/m")


class ModelTests(unittest.TestCase):
    def test_load_and_query_scalar_and_curve(self) -> None:
        material = load_material(EXAMPLE)

        density = material.get_property("general.density")
        curve = material.get_property("electromagnetic.BH_curve")

        self.assertIsInstance(density, ScalarProperty)
        self.assertAlmostEqual(density.to_unit("kg/m^3"), 7650.0)
        self.assertIsInstance(curve, CurveProperty)
        self.assertEqual(curve.x.name, "H")
        self.assertEqual(curve.y.name, "B")
        self.assertEqual(len(curve.x.values), 3)

    def test_missing_property_is_not_a_load_error(self) -> None:
        material = load_material(EXAMPLE)

        with self.assertRaises(PropertyNotFoundError):
            material.get_property("thermal.specific_heat")

    def test_curve_axis_lengths_must_match(self) -> None:
        with self.assertRaises(ModelValidationError):
            CurveProperty(
                x=Axis("H", "A/m", (0.0, 1.0, 2.0)),
                y=Axis("B", "T", (0.0, 1.0)),
            )

    def test_curve_x_must_be_strictly_increasing(self) -> None:
        with self.assertRaises(ModelValidationError):
            CurveProperty(
                x=Axis("H", "A/m", (0.0, 1.0, 1.0)),
                y=Axis("B", "T", (0.0, 1.0, 1.1)),
            )

    def test_property_source_and_text_curve_conditions_round_trip(self) -> None:
        material = load_material(EXAMPLE).with_property(
            "electromagnetic.BH_curve",
            CurveProperty(
                Axis("H", "A/m", (0.0, 100.0, 1000.0)),
                Axis("B", "T", (0.0, 1.0, 1.5)),
                conditions={
                    "orientation": ConditionValue("RD"),
                    "frequency": ConditionValue(50.0, "Hz"),
                },
                source=PropertySource(
                    dataset_id="example_open_data_v1",
                    manifest_ref="open_material_import/datasets/example/source_manifest.json",
                    raw_path="raw/bh.csv",
                    sha256="a" * 64,
                    locator="sheet=BH; rows=2:4",
                    license="CC-BY-4.0",
                    original_unit="mT",
                    conversion_note="Converted B from mT to T.",
                ),
                valid_ranges={"temperature": ValidityRange(293.15, 373.15, "K")},
            ),
        )

        reloaded = material_from_json(material_to_json(material))
        curve = reloaded.get_property("electromagnetic.BH_curve")

        self.assertEqual(curve.conditions["orientation"].value, "RD")
        self.assertIsNone(curve.conditions["orientation"].unit)
        self.assertEqual(curve.conditions["frequency"].unit, "Hz")
        self.assertEqual(curve.source.dataset_id, "example_open_data_v1")
        self.assertEqual(curve.valid_ranges["temperature"].unit, "K")

    def test_text_condition_rejects_a_unit(self) -> None:
        with self.assertRaises(ModelValidationError):
            ConditionValue("RD", "1")

    def test_non_finite_scalar_is_rejected(self) -> None:
        document = valid_document()
        document["properties"]["general"]["density"]["value"] = float("nan")

        with self.assertRaises(ModelValidationError):
            material_from_dict(document)

    def test_property_notes_round_trip_for_scalar_and_curve(self) -> None:
        document = valid_document()
        document["properties"]["general"]["density"]["note"] = (
            "Nominal value at room temperature"
        )
        document["properties"]["electromagnetic"]["BH_curve"]["note"] = (
            "Reference curve"
        )

        material = material_from_dict(document)
        reloaded = material_from_json(material_to_json(material))

        self.assertEqual(
            reloaded.get_property("general.density").note,
            "Nominal value at room temperature",
        )
        self.assertEqual(
            reloaded.get_property("electromagnetic.BH_curve").note,
            "Reference curve",
        )

    def test_known_property_rejects_wrong_dimension_and_invalid_range(self) -> None:
        material = load_material(EXAMPLE)
        material = material.with_property(
            "manufacturing.sheet_thickness", ScalarProperty(0.35, "mm")
        )
        self.assertAlmostEqual(
            material.get_property("manufacturing.sheet_thickness").to_unit("m"),
            0.00035,
        )
        with self.assertRaises(ModelValidationError):
            material.with_property(
                "manufacturing.sheet_thickness", ScalarProperty(1.0, "kg/m^3")
            )
        with self.assertRaises(ModelValidationError):
            material.with_property(
                "manufacturing.sheet_thickness", ScalarProperty(0.0, "m")
            )


class SerializationTests(unittest.TestCase):
    def test_json_object_round_trip_is_semantically_equal(self) -> None:
        original = load_material(EXAMPLE)
        reloaded = material_from_json(material_to_json(original))

        self.assertEqual(reloaded, original)
        self.assertEqual(reloaded.to_dict(), original.to_dict())

    def test_save_and_reload_uses_no_remaining_temp_file(self) -> None:
        material = load_material(EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "material.json"
            save_material(material, destination)

            self.assertEqual(load_material(destination), material)
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])

    def test_material_to_json_does_not_mutate_model(self) -> None:
        material = load_material(EXAMPLE)
        before = copy.deepcopy(material.to_dict())

        material_to_json(material)

        self.assertEqual(material.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
