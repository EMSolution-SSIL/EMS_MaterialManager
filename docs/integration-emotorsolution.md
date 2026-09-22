# eMotorSolution Integration

[日本語](integration-emotorsolution_ja.md)

The Material Manager root is selected once in eMotorSolution and then remembered for that Windows user.

## Configure the root

1. Open **Preferences** in eMotorSolution.
2. Open the **Paths** tab.
3. Set **Material Manager root** to the folder containing `manager.config.json`.
4. Select **Apply** or **OK**.

For managed installations, set `EMS_MATERIAL_MANAGER_ROOT` before starting eMotorSolution. This value takes precedence over the remembered location.

```powershell
$env:EMS_MATERIAL_MANAGER_ROOT = "C:\path\to\materials"
```

## Import a master material

1. Right-click **Materials** in eMotorSolution.
2. Select **Import from material manager**.
3. Select a material in the Manager dialog.
4. Confirm the import.

The project receives a value snapshot together with origin metadata. Editing the eMotorSolution project material does not modify the master record.

## Register a project material

1. Right-click a magnet or non-magnet material.
2. Select **Export to material manager**.
3. Choose the target material type and enter the registration information.
4. Save the new `User` material in the Manager dialog.

The project material is registered as a new User record; it does not overwrite a reference source.

The integration is supplied with supported eMotorSolution builds. Python-level eMotorSolution hooks are intentionally not part of the public EMS Material Manager API.