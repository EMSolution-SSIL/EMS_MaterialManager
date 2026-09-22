# EMSolution Python API

[English](api-emsolution.md)

これはサポート対象の公開製品APIです。材料値を EMSolution の `input.json` にコピーします。元の材料レコードはマスターとして変更されません。

## 材料を `input.json` へ出力する

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

アダプタはEMSolutionの材料およびB-Hカーブのセクションをアトミックに更新します。隣接する `<input-name>.ems-material-links.json` サイドカーファイルには、出力元の材料ID、バージョン、ハッシュを記録します。

対応する値には、導電率、比誘電率・複素比誘電率、比透磁率、等方性・方向別B-Hカーブ、鉄損、複素比透磁率が含まれます。

## 調整済みのEMSolution材料を登録する

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

取り込んだレコードは新しい `User` 材料として作成されます。来歴には、元のマスターレコードを上書きせずにプロジェクト材料の出所を識別する情報を保持します。

## 互換性の境界

このアダプタは、EMS Material Managerで現在実装しているEMSolutionの要素プロパティ構造を対象としています。永久磁石のM-H形式の元データをB-H形式へ変換する機能は意図的に自動化しておらず、別途レビューする将来機能です。
