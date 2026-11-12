# pyjmaxml

気象庁防災情報XMLの型付きパーサー、PULL型フィードのクライアントと警報の状態管理です。
Python 3.11以上に対応します。バージョン0.1.0は公開準備中です。

## インストール

公開前は、このリポジトリで実行してください。

```sh
python -m pip install .
# httpxの通信アダプターを使う場合
python -m pip install '.[httpx]'
```

既定の通信は標準ライブラリのurllibを使います。実行時の依存はxsdataとlxmlです。
コード表は同梱され、実行時にopenpyxlやコード表のダウンロードは必要ありません。

## フィードから市町村の警報を表示する

次は1回ポーリングし、取得・解析・状態への適用後にackする例です。
実行すると気象庁にアクセスします。

```python
import logging

from pyjmaxml import ParseError, WarningState, parse
from pyjmaxml.feed import FeedClient, FeedError, FeedKind

logger = logging.getLogger(__name__)


def update_once(client: FeedClient, state: WarningState) -> None:
    for entry in client.poll():
        try:
            data = client.fetch(entry)
        except (OSError, FeedError):
            logger.exception("取得失敗（未ack・次回再取得）: %s", entry.id)
            continue
        try:
            report = parse(data)
        except ParseError:
            logger.exception("解析できない電文をackして除外: %s", entry.id)
            client.ack(entry)
            continue
        try:
            state.apply(report)
        except ValueError:
            logger.exception("状態に適用できない電文をackして除外: %s", entry.id)
        client.ack(entry)


logging.basicConfig(level=logging.INFO)
client = FeedClient(FeedKind.EXTRA, user_agent="my-signage/1.0")
state = WarningState()
update_once(client, state)
print("出典：気象庁ホームページ（https://xml.kishou.go.jp/xmlpull.html）")
print("気象庁の防災情報XMLを、このサンプルの実行者が加工して作成")
print("枚方市", sorted(kind.name for kind in state.by_city("2721000")))
```

`apply()` が `ValueError` を投げた電文は、IDと例外をログに残し、**ackして除外**します。
ackしないと同じ電文が次の `poll()` でも返り続けるためです。
この例は解析不能な電文もログに残してackします。取得失敗時はackせず、次回に再取得します。
`apply()` が対象外・訓練・重複・古い電文としてスキップした場合もackします。
それ以外の例外は呼び出し側に伝わります。実運用ではログの監視と、必要に応じた原文の保存を行ってください。

実行用の同じ処理は [examples/poll_warnings.py](examples/poll_warnings.py) にあります。
録画済みサンプルを使う次のコマンドはネットワークにアクセスしません。表示は過去のサンプルです。

```sh
python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400
```

### ポーリングと状態の保持

- `poll()` は未処理エントリーを返します。`fetch()` 自体はackしません。
  未ackの電文は304応答でも、フィードから消えた後でも返ります。
- 未処理は発見順に最大1,000件保持し、超過時は古いものを警告ログ付きで破棄します。
  処理済みIDは既定で最大10,000件です。未処理は永続化しません。
- 高頻度フィードの最小間隔は60秒、`long=True` の長期フィードは3600秒です。
  呼び出し側で次回実行をスケジュールしてください。自動待機や自動再試行は行いません。
- `FeedKind.EXTRA` はVPWW55〜61等、`FeedKind.REGULAR` はVPWS50を含みます。
  状態は受け取った電文の範囲だけです。開始時・再起動時は長期フィードも使い、両方を同じ状態に適用してください。
  空の結果だけで「警報なし」と判断することはできません。
- User-Agentの既定値は `pyjmaxml/<version>` です。`user_agent` で上書きでき、空文字は指定できません。

`WarningState` はVPWW55〜61・VPWS50・VXKO・VXSUを扱い、既定では `Control/Status="通常"` のみを受理します。
旧形式のVPWW53/54と時系列のVPWP50は対象外です。`by_city(code)` は発表中の `WarningKind` 集合、
`cities(predicate)` は条件に合う市町村コードから種別集合への読み取り専用Mappingを返します。

```python
from pathlib import Path

from pyjmaxml import WarningState

saved = Path("warning-state.json")
saved.write_text(state.to_json(), encoding="utf-8")
restored = WarningState.from_json(saved.read_text(encoding="utf-8"))
assert restored.by_city("2721000") == state.by_city("2721000")
```

JSON形式はversion 1です。状態と電文の重複除去記録を保存します。フィードの未処理記録は含みません。
分割された市町村等のコードには、氾濫の照会時だけコード表の親市町村との対応を適用します。
親コードの照会へ子の気象警報を集約しません。

### パースだけを使う

```python
from pathlib import Path

from pyjmaxml import parse

report = parse(Path("tests/data/samples/15_16_03_241226_VPWW55.xml"))
print(report.control.title, report.head.report_date_time)
```

`parse()` はXMLのbytes・文字列・Pathを受け取り、gzipも自動展開します。
既定は `strict=True` です。これは未知の要素等の解析エラーを検出する設定で、XSD検証ではありません。
未対応のBodyは `UnknownBody` として保持します。

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

[CHANGELOG](CHANGELOG.md)、[人間による公開手順](RELEASING.md)、
[実装計画](implementation-plan.md)、[検証記録](IMPLEMENTATION_STATUS.md) を参照してください。
TestPyPI・PyPIへの公開はまだ行っていません。
