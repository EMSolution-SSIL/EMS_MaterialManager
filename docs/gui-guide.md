# GUI Guide

[日本語](gui-guide_ja.md)

## Material tree

The left pane is a `source -> family -> material` tree. Material IDs are internal identifiers; the tree shows the source, family, and material name so that long IDs do not obscure the list.

Use the search field to filter by name, ID, manufacturer, or tag. Sources and families can be collapsed.

## Creating and editing materials

- **New Material** opens the material-type selector. The selected template controls the available required, recommended, and optional properties.
- **Edit Material** enables a writable `User` material.
- **Edit as User Copy** copies a read-only reference material into `User`, preserving the original as the reference record.
- **Duplicate**, **Import**, **Export**, and **Delete** are available from the File menu and the matching buttons.

Reference records are read-only by default. Administrators may launch the application with `--admin-edit-reference` to correct a reference record. Deletion of reference records remains disabled.

```powershell
ems-material-manager --library-root .\materials --admin-edit-reference
```

## Property catalog

The property pane keeps known properties visible even when they are not set. Its expandable groups distinguish base isotropic parameters from optional anisotropic and complex parameters.

- **Electric Property:** electrical conductivity, relative permittivity, complex relative permittivity
- **Magnetic Property:** relative permeability, B-H curve, directional B-H curves, iron-loss coefficients, complex relative permeability
- **Manufacturing:** density and, where applicable, electrical-steel sheet thickness

Every scalar and curve property has a note field. Record the representative flux density and other measurement conditions for iron-loss coefficients.

## Curve editor

Double-click a curve property or use **View Property** to open a table-and-plot editor. B-H curves can be edited as points and displayed with linear or logarithmic axes. Directional X/Y/Z curves are optional and are collapsed by default.

## Help

The Help menu, Help button, and F1 open the project README in the built-in read-only Markdown viewer.