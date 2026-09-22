# Material type and property catalog

This directory configures the Material Manager without changing Python source.
It is referenced by `../manager.config.json` and is not a material data source,
so files placed here do not appear in the material tree.

## Files

- `property_definitions.v1.json`: property paths, labels, kinds, canonical units,
  ranges, categories, and family applicability.
- `material_types.v1.json`: material types shown by the New Material dropdown,
  aliases for legacy family names, and template file references.
- `templates/*.template.json`: the properties offered for each material type and
  their `required`, `recommended`, or `optional` status.

Only templates referenced by `material_types.v1.json` are loaded. Restart the
Material Manager after editing these files. Configuration errors are reported at
startup rather than silently falling back to Electrical Steel.

## Default values

Most template rows have no physical-property defaults. Blank rows are displayed
by the GUI but are not written to a material JSON until a user enters a value.
`soft_magnetic_material` and `carbon_steel` are the deliberate exception: they
create relative permeability `1` as a documented linear fallback when no B-H
curve is registered.

Analysis clients should call `resolve_magnetic_characteristic(material)` (or
`MaterialManager.get_magnetic_characteristic`) so a registered B-H curve takes
precedence over the linear fallback. A malformed B-H curve is an error and must
not silently fall back to relative permeability.

Electric and magnetic properties are grouped separately in the GUI. Complex
relative permeability and permittivity use explicit real/imaginary scalar rows;
their anisotropic variants use complete XYZ component sets. Directional B-H
curves reuse the normal curve editor. Partial component sets are reported by the
non-destructive audit.

## Model boundary

Material-intrinsic values belong here. Component geometry and usage settings do
not. In particular, winding insulation thickness, wire dimensions, fill factor,
and permanent-magnet orientation remain EMSolution component inputs.
