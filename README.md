# pyjmaxml

[![CI](https://github.com/dk-butsuri/pyjmaxml/actions/workflows/ci.yml/badge.svg)](https://github.com/dk-butsuri/pyjmaxml/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

気象庁の防災情報XMLを Python で扱うライブラリです。
市町村名を指定するだけで、その地域に出ている警報・注意報や天気予報を取得できます。
Python 3.11以上に対応します。バージョン0.1.0は公開準備中です。

[MIERUNE の jmaxml](https://github.com/MIERUNE/jmaxml) とは別のプロジェクトです。

## 特長

- **区域名で指定**：`"大阪府枚方市"` のように書けます。1,805区域の名前は型になっているので、
  誤入力はエディタや pyright が実行前に検出します。
- **警報を状態として管理**：電文を順に適用して「いま何が出ているか」を保持し、発表・解除などの差分を返します。
- **取得の面倒も見る**：フィードの条件付き取得、失敗した電文の再取得、処理済みの記録まで行います。
- **型付き**：気象庁のXMLスキーマから生成したデータ構造で、補完と型検査が効きます。

## できること

- 市町村ごとの警報・注意報の発表状況と、その変化（発表・解除など）
- 府県天気予報・週間天気予報、警報級の可能性、警報・注意報の予想時系列
- 地震情報（震度速報、震源・震度に関する情報）
- 気象庁のフィードの取得と、電文XMLの型付きパース

## インストール

PyPIにはまだ公開していないため、GitHubから直接インストールします。

```sh
python -m pip install "pyjmaxml @ git+https://github.com/dk-butsuri/pyjmaxml"
# httpxの通信アダプターと非同期クライアントを使う場合
python -m pip install "pyjmaxml[httpx] @ git+https://github.com/dk-butsuri/pyjmaxml"
```

clone したリポジトリでは `python -m pip install .`（httpx も使う場合は `'.[httpx]'`）です。

## はじめに

次の例は気象庁にアクセスして、枚方市と長野市（鬼無里戸隠）の情報を1回取得します。

```python
from pyjmaxml import Tracker

tracker = Tracker(["大阪府枚方市", "長野県長野市（鬼無里戸隠）"], user_agent="my-signage/1.0")
result = tracker.update()
hirakata = tracker.area("大阪府枚方市")
print(hirakata.name, sorted(kind.name for kind in hirakata.warnings))
for error in result.errors:
    print("取得失敗:", error)
print("出典：気象庁ホームページ（https://xml.kishou.go.jp/xmlpull.html）")
print("気象庁の防災情報XMLを、このサンプルの実行者が加工して作成")
```

- 区域名は「都道府県名 + 市町村名」で書きます（分割された区域の書き方は[ガイド](docs/guide.md#区域名の指定)）。名前を間違えるとエディタや pyright が教えてくれます。
- `user_agent` には、自分のアプリの名前を入れてください。
- `tracker.area(...)` で、その区域の警報（`warnings`）や天気予報（`forecast`）などを参照できます。
- 情報を新しくするには、`tracker.update()` を **60秒以上空けて**繰り返し呼びます。

ネットワークにつながずに動きを確かめるには、録画済みのサンプルを使う実行例を試せます。

```sh
python examples/track_areas.py --offline-sample
```

```text
録画済みサンプルの再生です。現在の発表状況ではありません。
北海道稚内市 ['レベル４大雨危険警報']
出典：気象庁ホームページ（https://xml.kishou.go.jp/xmlpull.html）
気象庁の防災情報XMLを、このサンプルの実行者が加工して作成
```

## 使うときの注意

- **起動直後や取得に失敗したとき、警報が空でも「警報なし」とは限りません。** 取得エラーは `result.errors` で確認できます。
- 気象庁の情報を表示するときは、**出典と、加工した旨の表示が必要**です。上の例の最後の2行がそれです。
  詳しくは[出典表示と利用上の注意](#出典表示と利用上の注意)を読んでください。
- **防災上の判断は、気象庁・自治体等の公式発表で確認してください。**

## もっと詳しく

[使い方ガイド](docs/guide.md) に、目的別の説明があります。

| やりたいこと | ガイドの節 |
| --- | --- |
| 府県内のすべての区域を見る、更新の動作を知る | [Tracker で区域名から見る](docs/guide.md#tracker-で区域名から見る) |
| フィードと警報の状態を自分で管理する | [フィードから市町村の警報を表示する](docs/guide.md#フィードから市町村の警報を表示する)、[ポーリングと状態の保持](docs/guide.md#ポーリングと状態の保持) |
| asyncio で使う | [非同期で取得する](docs/guide.md#非同期で取得する) |
| 個別の電文を読み解く | [警報級の可能性](docs/guide.md#警報級の可能性)、[天気予報](docs/guide.md#天気予報)、[予想時系列](docs/guide.md#気象警報注意報の予想時系列)、[地震情報](docs/guide.md#地震情報) |
| XMLをパースするだけ | [パースだけを使う](docs/guide.md#パースだけを使う) |

## 出典表示と利用上の注意

2026-11-12に、気象庁の[「ご利用にあたって」](https://www.jma.go.jp/jma/kishou/info/coment.html) と、
同ページが指定する[公共データ利用規約（第1.0版）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0) を確認しました。
別の利用条件が示されているコンテンツ等は、その条件も確認してください。

気象庁のコンテンツを利用する際は出典を記載します。例：

> 出典：気象庁ホームページ（https://xml.kishou.go.jp/xmlpull.html）

本ライブラリで抽出・正規化・集約した表示には、出典とは別に**加工した旨と加工主体**も記載します。例：

> 気象庁の防災情報XML（https://xml.kishou.go.jp/xmlpull.html）を株式会社○○が加工して作成

URLは利用したコンテンツに合わせ、加工主体は実際の運用者名に置き換えてください。
加工後の情報を、気象庁が作成した情報であるかのように表示してはいけません。
上の使用例も、この2つの表示を含みます。気象庁のコンテンツの利用条件と本ライブラリのコードの利用条件は別です。

本ソフトウェアは、抽出・集約結果の正確性・完全性・即時性を保証しません。
気象庁の利用規約でも、コンテンツを用いて行う行為について気象庁は責任を負わないとしています。
情報が常に最新であるとは限りません。**防災上の判断は、気象庁・自治体等の公式発表で確認してください。**

## ライセンス

コードは [MIT License](LICENSE) です。

ただし、次のものは気象庁のコンテンツで、[公共データ利用規約（第1.0版）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)に従います。出典は次の通りで、`tests/data/` と `tests/golden/` は各ディレクトリの README にも記載しています。

- `tests/data/`、`tests/golden/` の電文・フィードとコード表から作ったデータ
- `pyjmaxml/_generated/`（気象庁の XML スキーマから自動生成したコード）と `pyjmaxml/codes/`（気象庁のコード表から生成した辞書）
  - 出典：気象庁「気象庁防災情報XMLフォーマット 技術資料」（https://xml.kishou.go.jp/tec_material.html）の XML スキーマとコード表を、同志社香里 物理部が加工して作成

## 開発と公開

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pyright --verifytypes pyjmaxml --ignoreexternal
uv run python scripts/codegen.py --offline --codes-only
uv run python benchmarks/benchmark_vpws50.py --repeat 7
```

テストは録画済みの素材を使用し、DNS・ソケット接続を禁止します。`tests/golden/` は変更禁止です。
コード表の再生成には `vendor/` の配布物が必要です。

[CHANGELOG](CHANGELOG.md) と [人間による公開手順](RELEASING.md) を参照してください。
TestPyPI・PyPIへの公開はまだ行っていません。
