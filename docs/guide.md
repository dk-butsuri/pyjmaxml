# pyjmaxml 使い方ガイド

[README](../README.md) の続きです。Tracker の詳しい動作と、フィード・状態管理・各電文の正規化 API を説明します。
気象庁のコンテンツを表示する際は、README の[出典表示と利用上の注意](../README.md#出典表示と利用上の注意)に従ってください。

- [Tracker で区域名から見る](#tracker-で区域名から見る)
- [フィードから市町村の警報を表示する](#フィードから市町村の警報を表示する)
- [ポーリングと状態の保持](#ポーリングと状態の保持)
- [非同期で取得する](#非同期で取得する)
- [警報級の可能性](#警報級の可能性)
- [天気予報](#天気予報)
- [気象警報・注意報の予想時系列](#気象警報注意報の予想時系列)
- [地震情報](#地震情報)
- [パースだけを使う](#パースだけを使う)

## Tracker で区域名から見る

基本の使い方は README の[はじめに](../README.md#はじめに)の例を参照してください。

### 区域名の指定

区域名は公式コード表から生成した `AreaName`（1,805件の文字列 Literal）です。
分割されていない区域は「都道府県名 + 区域名」、分割された区域は
「都道府県名 + 親市町村名 + （区域名）」で指定します。
例えば `大阪府枚方市`、`兵庫県神戸市東灘区`、`長野県長野市（長野）`、
`長野県長野市（鬼無里戸隠）`、`神奈川県横浜市（横浜市北部）` です。
分割された区域は別々に指定します。親市町村への集約や省略形の検索は行いません。
pyright や対応エディタで名前の誤入力を検出でき、実行時にも検証します。

### 府県単位で見る

府県内すべての区域を見る場合は `prefectures=` を使います。府県名も `Prefecture` の Literal 型です。
北海道は7つの府県予報区を合わせて「北海道」1件として指定します。

```python
from pyjmaxml import Tracker

tracker = Tracker(prefectures=["大阪府"], user_agent="my-signage/1.0")
result = tracker.update()
for view in tracker.prefecture("大阪府").warned():
    print(view.name, sorted(kind.name for kind in view.warnings))
```

`prefecture().areas` は府県内すべての区域、`warned()` は警報・注意報がある区域の写しです。
`areas=` と `prefectures=` は併用でき、重複はまとめます。
`prefecture()` は `prefectures=` で指定した府県だけを返します。
区域コード順の `tracker.areas` と `AreaView`・`PrefectureView` は、更新後も取得済みの写しが変化しません。

### 取得できる情報

`AreaView` には `warnings`、`forecast`（VPFD51）、`weekly_forecast`（VPFW50）、
`possibility`（VPFD60）、`possibility_early`（VPFD61）、`possibility_weekly`（VPFW60）、
`timeseries`（VPWP50）があります。電文を受け取っていない項目は空です。
`tracker.earthquake` は最新の地震情報（VXSE51〜53）、未受信時は `None` です。

### 更新の動作

`update()` は **60秒以上空けて**呼んでください。待機・自動再試行は行いません。
最初の更新だけ EXTRA・REGULAR の長期フィードを読み、その後は通常フィードを読みます。
長期フィードの取得に失敗した場合（ネットワークにつながる前に起動したときなど）は、
最小間隔の1時間がたった後の更新で読み直します。それまでの待ちは `result.errors` に入りません。
見ている区域の都道府県に対応する電文だけを取得しますが、全国集約の VPWS50、
河川の VXKO・VXSU と地震は都道府県で絞りません。
`result.changes` は見ている区域の警報の差分、`result.applied` は使用した電文数、
`result.errors` はフィード・電文の取得エラーです。取得失敗は未ackのまま次の更新で再取得し、
他のフィードの処理は続けます。解析・適用できない電文はログに残してackします。
`updated_at` は最後に `update()` が戻った時刻（UTC）で、取得エラーの有無は `errors` で確認します。

### 注意点

空の結果だけで現在「警報なし」と判断することはできません。
再起動すると状態は消えます。警報の状態を保存する場合は `tracker.warning_state.to_json()` を使えます。
Tracker 自体の保存・復元機能はありません。
非同期版は `AsyncTracker` で、`await tracker.update()`・`await tracker.aclose()` と `async with` に対応します。
既定の非同期通信には `pyjmaxml[httpx]` が必要です。
[出典表示と利用上の注意](../README.md#出典表示と利用上の注意)も参照してください。

通信せずに使える実行例は [examples/track_areas.py](../examples/track_areas.py) にあります。

```sh
python examples/track_areas.py --offline-sample
```

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

実行用の同じ処理は [examples/poll_warnings.py](../examples/poll_warnings.py) にあります。
録画済みサンプルを使う次のコマンドはネットワークにアクセスしません。表示は過去のサンプルです。

```sh
python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400
```

## ポーリングと状態の保持

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

## 非同期で取得する

`AsyncFeedClient` は `poll()` と `fetch()` を `await` で呼べるクライアントです。
既定の通信はhttpxの `AsyncClient` で、追加の依存 `httpx`（[インストール](../README.md#インストール)を参照）が必要です。
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

## 警報級の可能性

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

## 天気予報

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

## 気象警報・注意報の予想時系列

`warning_timeseries(report)` は、regular フィードで配信される VPWP50 を、
市町村・Local（陸上・海上など）・値の種類・時間帯ごとの `WarningTimeSeriesCell` に展開します。
**発表中の警報を表すものではありません。** 発表状況の管理には `WarningState` を使います。
危険度は電文の `code`・`text` をそのまま返し、レベルには変換しません。

```python
from pathlib import Path

from pyjmaxml import parse, warning_timeseries

report = parse(Path("tests/data/timeseries/20261112075708_0_VPWP50_473000.xml"))
result = warning_timeseries(report)
for cell in result.by_city("4721400"):  # 宮古島市。市町村等コードの完全一致
    if cell.property == "波危険度":
        print(cell.start, cell.duration, cell.local, cell.code, cell.text, cell.notes)
```

数値は `number`、風向と危険度の名称は `text` に入り、値なしの数値は `None` になります。
`property` は Property/Type、`label` は値の種類で、高潮の「うちあげ高水位」と「潮位」も区別します。
`unit`・`condition`・`description` と、Part 全体への注記 `notes` を保持します。
`by_city()` は親区域への検索を行いません。状態管理や `Control/Status` の確認は行わず、
訓練・試験の電文の除外は呼び出し側で行います。

## 地震情報

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

## パースだけを使う

```python
from pathlib import Path

from pyjmaxml import parse

report = parse(Path("tests/data/samples/15_16_03_241226_VPWW55.xml"))
print(report.control.title, report.head.report_date_time)
```

`parse()` はXMLのbytes・文字列・Pathを受け取り、gzipも自動展開します。
既定は `strict=False` で、未対応のBodyは `UnknownBody` として保持します。
`strict=True` は未知の要素・値の変換失敗・未対応のBodyを `ParseError` にします。XSD検証ではありません。
