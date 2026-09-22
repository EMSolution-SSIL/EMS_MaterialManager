# EMS Material Manager

[English](README.md)

EMS Material Manager は、EMSolution ワークフローで使用する材料データを登録、検証、再利用、交換するためのデスクトップ／Pythonツールです。編集可能な材料データのマスターとして機能し、各製品プロジェクトにはマスター値へのライブリンクではなく独立したスナップショットを渡します。

> **v0.1.0:** ソースコードは PolyForm Perimeter License 1.0.1 で提供します。詳細は [LICENSE](LICENSE) を参照してください。

## 主な機能

- 電磁鋼板、永久磁石、導体、絶縁材、軟磁性材料、炭素鋼、構造材料、汎用材料に対応する材料タイプとテンプレート
- B-Hカーブ、方向別B-Hカーブ、鉄損、電気特性、複素電磁特性を含むスカラー／カーブ特性
- 検索可能な source/family/material ツリー、プロパティカタログ、カーブエディタ、ノート、参照ソースの読み取り専用化、管理者モードを備えたQt GUI
- Canonical JSONのインポート／エクスポート、来歴、検証、ソースフォルダの許可リスト、材料監査
- eMotorSolutionおよびEMSolutionの `input.json` とのスナップショット方式のデータ交換

## クイックスタート

Python 3.11以降が必要です。

```powershell
python -m pip install "ems-material-manager[gui]"
ems-material-manager --library-root .\materials
```

設定ルートには `manager.config.json` を置きます。インストールと初回利用は [はじめに](docs/getting-started_ja.md) を参照してください。

## ドキュメント

- [はじめに](docs/getting-started_ja.md)
- [GUIガイド](docs/gui-guide_ja.md)
- [EMSolution Python API](docs/api-emsolution_ja.md)
- [eMotorSolution連携](docs/integration-emotorsolution_ja.md)
- [材料データ管理](docs/material-data_ja.md)
- [ライセンスとデータ来歴](docs/licensing_ja.md)
- [リリースノート](docs/release-notes_ja.md)

## データとライセンス

コードと材料データのライセンスは別です。材料データセットにソースコードのライセンスが適用されるとは限りません。配布する各データセットには、提供者、出典、利用条件、帰属表示、変換履歴を明記してください。詳細は [ライセンスとデータ来歴](docs/licensing_ja.md) を参照してください。

## 開発

開発計画、実装記録、社内向けリリース準備資料は `docs_dev/` にあります。テストは次のコマンドで実行します。

```powershell
python -m pytest -q -p no:cacheprovider
```
