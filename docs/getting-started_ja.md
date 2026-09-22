# はじめに

[English](getting-started.md)

EMS Material Manager は、EMSolution ワークフローで使用する材料データの登録、検証、再利用、交換を行うデスクトップ／Pythonツールです。

## 必要条件

- Python 3.11以降
- Qtデスクトップアプリケーションを使用する場合はWindows

## インストール

配布パッケージからGUI対応版をインストールします。

```powershell
python -m pip install "ems-material-manager[gui]"
```

ソースを取得して開発する場合は、編集可能モードでインストールします。

```powershell
python -m pip install -e ".[gui]"
```

## デスクトップアプリケーションの起動

`manager.config.json` を含むルートフォルダを指定します。

```powershell
ems-material-manager --library-root .\materials
```

リポジトリに含まれる `materials` フォルダは、マネージャルートの例です。利用者または組織は別のルートを作成し、表示するソースフォルダを設定できます。

## 最初の操作

1. アプリケーションを起動し、**New Material** を選択します。
2. 材料タイプを選択して、名称と必須項目を入力します。
3. 書き込み可能な `User` ソースへ保存します。
4. **Export** で持ち運び可能な Canonical JSON を作成するか、EMSolution／eMotorSolutionのワークフローに取り込みます。

`IEEJ` などの参照ソースは意図的に読み取り専用です。参照材料を変更する場合は、先に **Edit as User Copy** を使用してください。

フォルダ設定は [材料データ管理](material-data_ja.md)、編集操作は [GUIガイド](gui-guide_ja.md) を参照してください。
