# EMSolution Python API

This is the supported public product API. It copies material values into an EMSolution `input.json`; the source material remains the master record.

## Export a material to `input.json`

```python
from ems_material import ExportSelection, MaterialManager
from ems_material.adapters import EMSolutionInputAdapter

manager = MaterialManager("materials")
material = manager.get("ieej:50a350")

EMSolutionInputAdapter().apply_to_file(
    "input.json",
    material,
    selection=ExportSelection(
        permeability="bh_isotropy",
        iron_loss="isotropy",
    ),
)
```

The adapter atomically updates the EMSolution material and B-H-curve sections. It writes an adjacent `<input-name>.ems-material-links.json` sidecar containing the source material ID, version, and hash.

Supported values include electrical conductivity, relative and complex permittivity, relative permeability, isotropic and directional B-H curves, iron loss, and complex relative permeability.

## Register an adjusted EMSolution material

```python
from ems_material import MaterialManager
from ems_material.adapters import EMSolutionInputAdapter

manager = MaterialManager("materials")
registered = EMSolutionInputAdapter().register_from_file(
    manager,
    "input.json",
    "50A350",
    family="electrical_steel",
    author="analysis user",
    new_name="50A350 project adjusted",
)
print(registered.material_id, registered.parent_ref)
```

The imported record is created as a new `User` material. Its lineage identifies the source project material without overwriting the original master record.

## Compatibility boundary

The adapter supports the EMSolution element-property structure currently implemented by EMS Material Manager. M-H to B-H conversion for permanent-magnet source data is intentionally not performed automatically and remains a separately reviewed future capability.