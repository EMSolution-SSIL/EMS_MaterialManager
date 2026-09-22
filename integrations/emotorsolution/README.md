# eMotorSolution Manufacturing BOM integration

Status as of 2026-09-14: the BOM adapter contract remains available, and the
material snapshot import/export patch has been applied to the reference
eMotorSolution checkout. Product GUI UAT and representative-project regression
remain.

Both patches were checked with `git apply --check` against the reference
checkout. `material_manager_exchange.patch` is applied there; the patch file is
kept as the reproducible integration artifact.

The common package intentionally does not import eMotorSolution. The only
product-side change needed by the PoC is to let the existing BOM density lookup
delegate to an `EMotorSolutionMaterialAdapter` when one is configured.

Apply `providers_material_manager.patch` in the eMotorSolution repository. At
application startup, attach the adapter to the project data passed to
`compute_manufacturing_bom`:

```python
from ems_material import MaterialManager
from ems_material.adapters import EMotorSolutionMaterialAdapter

library = MaterialManager(user_material_directory)
project.props.material_manager_adapter = EMotorSolutionMaterialAdapter(
    library,
    name_to_id={"50A350": "legacy:50a350"},
)
```

If the project data class does not permit dynamic attributes, add an optional
`material_manager_adapter` field excluded from project serialization. The patch
preserves legacy lookup when no adapter is configured, so existing projects
continue to run unchanged.

`material_manager_exchange.patch` adds:

- `Import from material manager` on the Materials context menu
- `Export to material manager` on non-magnet and magnet context menus
- `_ems_material_origin` persistence in project material JSON
- reuse of the existing material classes and `update_input_control()` path

Set `EMS_MATERIAL_MANAGER_ROOT` to the configured `materials` directory before
starting eMotorSolution when a managed, fixed location is required. Otherwise,
the first Import or Export asks the user to select the library root and stores
that choice in `%APPDATA%\EMSolution\ems_material_product_exchange.json`.
Subsequent Material Manager actions reuse the saved location automatically.
The per-user setting is deliberately kept outside eMotorSolution project files.
The `Preferences → Paths → Material Manager root` entry can view or change the
same location; it takes precedence over the automatically remembered path.
Apply `material_manager_preferences.patch` after
`material_manager_exchange.patch` to add this Preferences control to the
eMotorSolution GUI.

The integration contract is exercised against the real eMotorSolution
`BOMItem`, `BOMDiagnostic`, and `_material_item` in
`tests/test_emotorsolution_bom_integration.py`.
