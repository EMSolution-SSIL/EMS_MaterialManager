# EMS Material Manager

[日本語](README_ja.md)

EMS Material Manager is a desktop and Python tool for registering, validating, reusing, and exchanging material data for EMSolution workflows. It is the editable material-data master; product projects receive independent snapshots rather than live links to master values.

> **v0.1.0:** The source code is licensed under PolyForm Perimeter License 1.0.1; see `LICENSE`.

## Highlights

- Material types and templates for electrical steel, permanent magnets, conductors, insulators, soft magnetic materials, carbon steels, structural materials, and generic materials
- Scalar and curve properties, including B-H curves, directional B-H curves, iron loss, electric properties, and complex electromagnetic properties
- Qt GUI with searchable source/family/material tree, property catalog, curve editor, notes, read-only reference sources, and administrator mode
- Canonical JSON import/export, provenance, validation, source-folder allow-lists, and material audit
- Snapshot-based exchange with eMotorSolution and EMSolution `input.json`

## Quick start

Python 3.11 or later is required.

```powershell
python -m pip install "ems-material-manager[gui]"
ems-material-manager --library-root .\materials
```

The configured root contains `manager.config.json`. See [Getting started](docs/getting-started.md) for package installation and first use.

## Documentation

- [Getting started](docs/getting-started.md)
- [GUI guide](docs/gui-guide.md)
- [EMSolution Python API](docs/api-emsolution.md)
- [eMotorSolution integration](docs/integration-emotorsolution.md)
- [Material data management](docs/material-data.md)
- [Licensing and data provenance](docs/licensing.md)
- [Release notes](docs/release-notes.md)

## Data and licensing

Code and material data are licensed separately. Never assume that a material dataset inherits the source-code license. Each distributed dataset must identify its provider, source, terms of use, attribution, and transformation history. See [Licensing and data provenance](docs/licensing.md).

## Development

Development plans, implementation records, and internal release preparation are in `docs_dev/`. Run the test suite with:

```powershell
python -m pytest -q -p no:cacheprovider
```