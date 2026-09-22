# Material Data Management

[日本語](material-data_ja.md)

## Manager root

A manager root contains an explicit allow-list of data sources.

```text
materials/
  manager.config.json
  _catalog/
  User/
    source.config.json
  IEEJ/
    source.config.json
```

- `manager.config.json` enables source folders and selects the default writable source.
- Each `source.config.json` lists the material files visible from that source.
- `_catalog` defines material types, property definitions, units, requirements, and templates.

Folders or files not listed in these configuration files are ignored. This allows an organization to keep candidate, private, or infrequently used data near the manager root without exposing it in the GUI.

## Sources

`User` is normally writable. New, Import, Duplicate, and project-registration operations add records there. Reference sources are normally read-only and should be copied into `User` before modification.

## Exchange formats

Canonical JSON is the portable material-record format. The GUI supports JSON import and export; tabular curve data can be edited in the curve editor. Users may transform exported JSON or CSV data for research or other tools under the applicable data license.

## Data quality

Store provenance, source URL, version, units, and measurement conditions with each record. Add notes to values such as iron-loss coefficients when they apply only at a representative flux density, frequency, temperature, or specimen condition.

See [Licensing and data provenance](licensing.md) before distributing any material dataset.