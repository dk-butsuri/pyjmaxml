# pyjmaxml

気象庁防災情報XMLの型付きパーサー、PULL型フィードのクライアントと警報の状態管理です。
Python 3.11以上に対応します。バージョン0.1.0は公開準備中です。

[MIERUNE の jmaxml](https://github.com/MIERUNE/jmaxml) とは別のプロジェクトです。

## ライセンス

コードは [MIT License](LICENSE) です。

ただし、次のものは気象庁のコンテンツで、[公共データ利用規約（第1.0版）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)に従います。出典はそれぞれのディレクトリの README に記載しています。

- `tests/data/`、`tests/golden/` の電文・フィードとコード表から作ったデータ
- `pyjmaxml/_generated/`（気象庁の XML スキーマから自動生成したコード）と `pyjmaxml/codes/`（気象庁のコード表から生成した辞書）
  - 出典：気象庁「気象庁防災情報XMLフォーマット 技術資料」（https://xml.kishou.go.jp/tec_material.html）の XML スキーマとコード表を、同志社香里 物理部が加工して作成

## インストール

公開前は、このリポジトリで実行してください。

```sh
python -m pip install .
# httpxの通信アダプターと非同期クライアントを使う場合
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
        except FeedError:
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
時刻の範囲外としてスキップした `too_old` / `future` も同様です。
同梱の通信アダプター（urllib・httpx）は、接続・タイムアウト・本文の読み込み途中の切断を
`FeedTransportError`（`FeedError` の一種）に変換し、元の例外を `__cause__` に残します。
このため `except FeedError` だけで、通信ライブラリによらず取得失敗を扱えます。
HTTPのエラー状態（404・500など）は `HttpStatusError` です。
`poll()` の失敗を含め、それ以外の例外は呼び出し側に伝わります。
実運用ではログの監視と、必要に応じた原文の保存を行ってください。

実行用の同じ処理は [examples/poll_warnings.py](examples/poll_warnings.py) にあります。
録画済みサンプルを使う次のコマンドはネットワークにアクセスしません。表示は過去のサンプルです。

```sh
python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400
```

### ポーリングと状態の保持

- `poll()` は未処理エントリーを返します。`fetch()` 自体はackしません。
  未ackの電文は304応答でも、フィードから消えた後でも返ります。
- `poll()` は未処理を `updated` の古い順に返します。気象庁のフィードは新しい順ですが、並べ替えて返します。
  時刻が同じものはフィード上で後ろにある方を先にします。この順のまま `apply()` してください。
  新しい電文を先に適用すると、同じ情報の古い電文は `stale` として捨てられます。
  最終的な状態は同じですが、途中の発表・切り替えの `Change` は出ません。
- 未処理は最大1,000件保持し、超過時は `updated` の最も古いものを警告ログ付きで破棄します。
  処理済みIDは既定で最大10,000件です。未処理は永続化しません。
- 高頻度フィードの最小間隔は60秒、`long=True` の長期フィードは3600秒です。
  呼び出し側で次回実行をスケジュールしてください。自動待機や自動再試行は行いません。
- `FeedKind.EXTRA` はVPWW55〜61等、`FeedKind.REGULAR` はVPWS50を含みます。
  状態は受け取った電文の範囲だけです。開始時・再起動時は長期フィードも使い、両方を同じ状態に適用してください。
  空の結果だけで「警報なし」と判断することはできません。
- User-Agentの既定値は `pyjmaxml/<version>` です。`user_agent` で上書きでき、空文字は指定できません。

実運用では現在時刻を渡すと、気象庁の運用指針 §2.1.3.6 に沿って、
`Control/DateTime` が古すぎる電文を `too_old`、未来すぎる電文を `future` としてスキップできます。
`now` はタイムゾーン必須です。省略すると時刻の範囲による判定はしません。

```python
from datetime import UTC, datetime, timedelta

result = state.apply(report, now=datetime.now(UTC))  # 既定：過去24時間、未来10分まで
result = state.apply(report, now=datetime.now(UTC), max_age=timedelta(hours=48), max_future=None)
```

`max_age` の既定値は24時間です。再起動時に読む長期フィードには数日前の電文も含まれますが、
発表中の古い要素は約10分ごとのVPWS50に `Kind/DateTime` つきで載るため、
24時間より古いVPWWを捨てても状態を回復でき、保存済みの古い電文の混入を防げます。
`max_future` の既定値は10分で、利用者側の時計の多少のずれを許容します。
両方とも非負の `timedelta` で変更でき、`None` でその側の判定を無効化できます。境界時刻は受理します。
スキップの優先順位は status → unsupported → duplicate → stale → too_old → future です。
`too_old` / `future` は処理履歴に記録しないため、後で `now` なしで適用し直せます。

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
VPWS50の「発表なし」は `cleared`（市町村別）と `cleared_all`（全国）に時刻つきで保存し、
セルがまだない市町村でも古い電文で警報が復活するのを防ぎます。この2項目がない従来のJSONも読めます。
分割された市町村等のコードには、氾濫の照会時だけコード表の親市町村との対応を適用します。
親コードの照会へ子の気象警報を集約しません。

### 非同期で取得する

`AsyncFeedClient` は `poll()` と `fetch()` を `await` で呼べるクライアントです。
既定の通信はhttpxの `AsyncClient` で、`pip install '.[httpx]'` が必要です。
未処理・ack・最小間隔などの扱いは `FeedClient` と同じです。実行すると気象庁にアクセスします。

```python
import asyncio

from pyjmaxml import ParseError, WarningState, parse
from pyjmaxml.feed import AsyncFeedClient, FeedError, FeedKind


async def update_once(client: AsyncFeedClient, state: WarningState) -> None:
    entries = await client.poll()
    # 取得だけを並行に行い、状態への適用は poll() の順（古い順）に1件ずつ行う。
    results = await asyncio.gather(
        *(client.fetch(entry) for entry in entries), return_exceptions=True
    )
    for entry, data in zip(entries, results, strict=True):
        if isinstance(data, FeedError):
            continue  # 取得失敗。ackせず次回に再取得する
        if isinstance(data, BaseException):
            raise data
        try:
            state.apply(parse(data))
        except (ParseError, ValueError):
            pass  # 実運用ではログに残す
        client.ack(entry)


async def main() -> None:
    state = WarningState()
    async with AsyncFeedClient(FeedKind.EXTRA, user_agent="my-signage/1.0") as client:
        while True:
            await update_once(client, state)
            await asyncio.sleep(60)
```

同時に送るリクエストは既定で4件までです（`max_concurrency`）。
`asyncio.gather` で多数の電文を取得しても、気象庁のサーバーへの同時接続はこの数に抑えられます。
`WarningState.apply()` は並行に呼ばないでください。
`http` には `async def send(req)` を持つ任意の通信部品（`AsyncHttpClient`）を渡せます。
自作する場合は、応答を得られない失敗を `FeedTransportError` にしてください。
自前のhttpx `AsyncClient` は `HttpxAsyncHttpClient(client)` で渡せ、その場合は呼び出し側が閉じます。
1つのクライアントは1つのイベントループの中で使ってください。

### 警報級の可能性

`warning_possibility(report)` は、VPFD60（明日まで）・VPFD61（早期注意情報、明後日まで）・VPFW60（明後日以降）を、
一次細分区域・要素・時間帯ごとの `PossibilityCell` に展開します。これらはregularフィードに配信されます。

```python
from pathlib import Path

from pyjmaxml import Possibility, parse, warning_possibility

report = parse(Path("tests/data/samples/90_01_01_241031_VPFD61.xml"))
result = warning_possibility(report)
for cell in result.by_city("3720100"):  # 高松市 → 香川県（370000）
    if cell.possibility is not None and cell.possibility >= Possibility.MEDIUM:
        print(cell.element, cell.period_name, cell.raw)
```

`possibility` は `HIGH`（高）・`MEDIUM`（中）・`NONE`（なし、または `condition="値なし"`）の順に比較できます。
未知の値は `None`、未知の要素は `Element.UNKNOWN` とし、警告ログを出します。元の文字列は `raw` と `name` に残ります。
要素は既存の `Element` を使います。「雨」と「大雨」は `HEAVY_RAIN`、「風（風雪）」は `STORM`、「潮位」は `STORM_SURGE` です。
VPFW60 の時間帯には名前がないため、`period_name` は空文字になります。
状態管理は行わず、`Control/Status` も確認しません。訓練・試験の電文は呼び出し側で除外してください。

### 天気予報

`weather_forecast(report)` は、VPFD51（府県天気予報）・VPFW50（府県週間天気予報）を、
区域または地点・要素・時間帯ごとの `ForecastCell` に展開します。旧形式のVPFD50にも対応します。
これらはregularフィードに配信されます。

```python
from pathlib import Path

from pyjmaxml import ForecastElement, parse, weather_forecast

report = parse(Path("tests/data/forecast/20261111073453_0_VPFD51_130000.xml"))
result = weather_forecast(report)
for cell in result.by_city("1310100"):  # 千代田区 → 東京地方（130010）
    if cell.element is ForecastElement.WEATHER:
        print(cell.period_name, cell.text)
    elif cell.element is ForecastElement.PRECIPITATION_PROBABILITY:
        print(cell.period_name, f"{cell.number:.0f}%")
for cell in result.by_station("44132"):  # 東京
    if cell.element is ForecastElement.DAYTIME_MAX_TEMPERATURE:
        print(cell.period_name, cell.number, "度")
```

天気・天気予報用テロップ番号・風向・信頼度・風と波の予報文は `text`、
降水確率・気温・風速階級は `number` に入ります。`condition="値なし"` の値はどちらも `None` です。
降水確率の `condition` には「雨」「雪か雨」などの降水の種類が入ります。
元の値の種類（「６時間降水確率」「日降水確率」など）は `label` に残ります。
未知の要素は `ForecastElement.UNKNOWN` とし、警告ログを出します。

天気・降水確率などは区域、気温は地点（アメダス番号）ごとの予報です。
電文に区域と地点の対応がないため、`by_city()` は区域だけを返します。気温は `by_station()` で引いてください。
VPFW50の区域は一次細分区域より粗いことがあります（鹿児島県（奄美地方除く）460100、釧路・根室・十勝地方014000など）。
`by_city()` は一次細分区域、府県予報区、上位区域（上3桁＋000）の順に探します。
VPFW50の「７日間平年値」（降水量の階級閾値）は時系列ではないため展開しません。
`Control/Status` は確認しません。

### 地震情報

`earthquake_info(report)` は、VXSE51（震度速報）・VXSE52（震源に関する情報）・VXSE53（震源・震度に関する情報、
遠地地震に関する情報）を、震源・マグニチュードと、都道府県・地域・市町村・観測点ごとの `IntensityCell` に展開します。
これらはeqvolフィードに配信されます。

```python
from pathlib import Path

from pyjmaxml import Intensity, earthquake_info, parse

report = parse(Path("tests/data/earthquake/20261107160836_0_VXSE53_010000.xml"))
info = earthquake_info(report)
if info.info_type != "取消" and info.hypocenter and info.magnitude:
    print(info.origin_time, info.hypocenter.name, info.hypocenter.depth_km, "km")
    print(info.magnitude.description, info.max_intensity, info.forecast_comment)
for cell in info.by_city("2322400"):  # 知多市
    print(cell.level, cell.name, cell.intensity)
for cell in info.intensities:
    strong = cell.intensity is not None and cell.intensity >= Intensity.FIVE_LOWER
    if cell.level == "city" and (strong or cell.unreceived):
        print(cell.name, cell.intensity or cell.raw)
```

`Intensity` は `FIVE_LOWER < FIVE_UPPER` のように比較できます。値は順位で、震度5強は `6` です。
`str()` とf文字列は「震度5強」と表示します。`int()` の値を震度として表示しないでください。
「震度５弱以上未入電」は `unreceived=True` です。観測点では `intensity` が `None`、
市町村では入電した観測点だけの最大震度か `None` になるため、強い揺れの判定では `unreceived` も確認してください。
未知の震度は `None` とし、警告ログを出します。元の文字列は `raw` に残ります。

震源の深さは `depth_km` で、「ごく浅い」は `0.0`、「深さ不明」は `None` です。
マグニチュードが決まらない場合（「Ｍ８を超える巨大地震」など）は `magnitude.value` が `None` で、
`description` に元の文が残ります。続報で追加・上方修正された値は `revise` に「追加」「上方修正」が入ります。

VXSE51は地域までしか含まないため、`by_city()` は空になります。地域は `by_area()` に地震情報用の細分区域コード
（愛知県西部は451）を渡してください。取消報（`info_type == "取消"`）は `text` だけを持ちます。
同じ地震の続報は `event_id` が共通です。状態管理は行わず、`Control/Status` も確認しません。
緊急地震速報（VXSE43〜45）は対象外です。公開のPULL型フィードにも配信されません。

### パースだけを使う

```python
from pathlib import Path

from pyjmaxml import parse

report = parse(Path("tests/data/samples/15_16_03_241226_VPWW55.xml"))
print(report.control.title, report.head.report_date_time)
```

`parse()` はXMLのbytes・文字列・Pathを受け取り、gzipも自動展開します。
既定は `strict=False` で、未対応のBodyは `UnknownBody` として保持します。
`strict=True` は未知の要素・値の変換失敗・未対応のBodyを `ParseError` にします。XSD検証ではありません。

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
