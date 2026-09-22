# eMotorSolution連携

[English](integration-emotorsolution.md)

Material Managerのルートは、eMotorSolutionで一度選択すると、そのWindowsユーザーに対して記憶されます。

## ルートを設定する

1. eMotorSolutionで **Preferences** を開きます。
2. **Paths** タブを開きます。
3. **Material Manager root** に `manager.config.json` を含むフォルダを設定します。
4. **Apply** または **OK** を選択します。

管理対象のインストールでは、eMotorSolutionを起動する前に `EMS_MATERIAL_MANAGER_ROOT` を設定します。この値は記憶済みの場所より優先されます。

```powershell
$env:EMS_MATERIAL_MANAGER_ROOT = "C:\path\to\materials"
```

## マスター材料を取り込む

1. eMotorSolutionで **Materials** を右クリックします。
2. **Import from material manager** を選択します。
3. Managerダイアログで材料を選択します。
4. インポートを確定します。

プロジェクトには、出所メタデータとともに値のスナップショットが作成されます。eMotorSolutionプロジェクト側の材料を編集しても、マスターレコードは変更されません。

## プロジェクト材料を登録する

1. 磁石または非磁石材料を右クリックします。
2. **Export to material manager** を選択します。
3. 登録先の材料タイプを選択し、登録情報を入力します。
4. Managerダイアログで新しい `User` 材料として保存します。

プロジェクト材料は新しいUserレコードとして登録されます。参照ソースを上書きすることはありません。

この連携は、対応するeMotorSolutionビルドで提供されます。PythonレベルのeMotorSolutionフックは、EMS Material Managerの公開Python APIには含めません。
