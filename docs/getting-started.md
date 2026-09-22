# Getting Started

[日本語](getting-started_ja.md)

EMS Material Manager is a desktop and Python tool for registering, validating, reusing, and exchanging material data used by EMSolution workflows.

## Requirements

- Python 3.11 or later
- Windows for the Qt desktop application

## Install

Install the GUI-enabled package from the distribution selected by your organization:

```powershell
python -m pip install "ems-material-manager[gui]"
```

For a source checkout, install it in editable mode:

```powershell
python -m pip install -e ".[gui]"
```

## Start the desktop application

Pass the root folder that contains `manager.config.json`:

```powershell
ems-material-manager --library-root .\materials
```

The checked-in `materials` folder is an example manager root. A user or organization can create another root and configure the source folders that it exposes.

## First workflow

1. Start the application and select **New Material**.
2. Select a material type, then enter the name and required values.
3. Save it into the writable `User` source.
4. Use **Export** to create a portable Canonical JSON record, or import it into an EMSolution or eMotorSolution workflow.

Reference sources such as `IEEJ` are intentionally read-only. Use **Edit as User Copy** before modifying a reference material.

See [Material data management](material-data.md) for the configured-folder layout and [GUI guide](gui-guide.md) for the editor.