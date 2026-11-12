# 計画：かんたんに使える入口 `Tracker` と、区域名の Literal 型

作成 2026-11-12。実装担当向けの指示書。**このファイルに書いていないことを決める必要が出たら、実装を止めて報告すること。**

## 0. 前提と作業ルール

- **`vpwp50-plan.md` を先に終わらせてから**この計画に入る（`warning_timeseries()` を使うため）。
- `git commit`・push はしない。
- `tests/golden/` は触らない。既存の公開 API（`FeedClient`・`WarningState`・各正規化関数）は**変更しない**。この計画はその上に入口を足すだけ。
- コマンドはすべて `uv run` で実行する。`pyjmaxml/**/*.py` は LF 改行。
- テストや CI から気象庁にはアクセスしない（既存の `tests/test_offline_guard.py` の仕組みに従う）。
- 完了条件は §8。

## 1. 目的

今は、使い始めるまでに覚えることが多すぎる。フィードの種類（EXTRA・REGULAR・長期）、`poll → fetch → parse → apply → ack` の順番、例外3種類、電文の種類コード、7桁の市町村コード。
keihan_tracker の `KHTracker` のように、**オブジェクトを作って `update()` を呼び、区域名で結果を見るだけ**で使えるようにする。

```python
from pyjmaxml import Tracker

tracker = Tracker(["大阪府枚方市", "長野県長野市（鬼無里戸隠）"], user_agent="my-signage/1.0")
tracker.update()

hirakata = tracker.area(
    "大阪府枚方市"
)  # 区域名は Literal 型。打ち間違いは pyright とエディタが指摘する
print(sorted(kind.name for kind in hirakata.warnings))

# 府県ごとにまとめて見る使い方（府県内の警報一覧を出すサイネージなど）
tracker = Tracker(prefectures=["大阪府"], user_agent="my-signage/1.0")
tracker.update()
for view in tracker.prefecture("大阪府").areas:
    print(view.name, sorted(kind.name for kind in view.warnings))
```

## 2. 区域名の Literal 型 `AreaName`

### 2.1 単位は「警報の区域」（`AREA_CITY` の1,805件）。市町村ではない

- 気象庁は、一部の市町村を分割して別々に警報を出す（例：長野市 → 「長野」と「鬼無里戸隠」、横浜市 → 北部・南部）。40市町村、89区域。
- 分割された区域を親の市町村にまとめては**いけない**。鬼無里戸隠だけに出た警報が、長野市の中心部にも出ているように見えてしまう。
- 神戸市と広島市は、区ごとに区域になっている（`2810100` 神戸市東灘区 など）。これらは分割ではなく、普通の区域として扱う。

### 2.2 名前の決まり（調査済み：1,805件すべて重複なし）

元データ：`20261019_AreaInformationCity-AreaForecastLocalM.xlsx` の `AreaInformationCity` シート。B列「コードが示す地域等」、C列 `@name`。

- 都道府県名：その区域の行（分割された区域なら親の行）の B列の先頭から取る。正規表現 `^(北海道|東京都|大阪府|京都府|.{2,3}県)`。
- 分割されていない区域（`AREA_CITY_PARENT` にない）：`都道府県 + C列`
  - `2721000` → `大阪府枚方市`、`1310100` → `東京都千代田区`、`2810100` → `兵庫県神戸市東灘区`
- 分割された区域（`AREA_CITY_PARENT` にある）：`都道府県 + 親の行のC列 + "（" + 区域のC列 + "）"`
  - `2020111` → `長野県長野市（長野）`、`2020112` → `長野県長野市（鬼無里戸隠）`
  - `1410011` → `神奈川県横浜市（横浜市北部）`、`0148402` → `北海道羽幌町（天売焼尻）`、`0120601` → `北海道釧路市（釧路市釧路）`
- 「横浜市（横浜市北部）」のように重なって見えるものも、手で短くしない（決まりを機械的に保つため）。

### 2.3 生成

- `scripts/codegen.py` に生成処理を足し、`pyjmaxml/codes/_area_name.py` を作る。既存の `_area_city.py` と同じヘッダー（Archive・Workbook とその SHA-256）を付ける。
  ```python
  AreaName = Literal["北海道札幌市", ..., "沖縄県与那国町"]  # AREA_CITY のコード順
  AREA_CODE_BY_NAME: dict[AreaName, str]
  AREA_NAME_BY_CODE: dict[str, AreaName]
  ```
- 次の場合は生成を失敗させる：名前が重複する、都道府県名を取れない行がある、`AREA_CITY` のコードで名前がないものがある、件数が `AREA_CITY` と違う。
- `pyjmaxml/codes/__init__.py` と `pyjmaxml/__init__.py` から `AreaName` を公開する。
- テスト（`tests/test_code_tables_codegen.py` と `tests/test_codes.py` の形式に合わせる）：件数1,805、重複なし、§2.2 の例がすべてそのとおりになる、両方向の辞書が一致する。

### 2.4 pyright の速さを測る（止める条件あり）

1,805個の文字列からなる Literal は大きい。次の2つを、**変更前と変更後で測って `IMPLEMENTATION_STATUS.md` に記録する**。
- `uv run pyright` 全体の時間
- 小さな確認ファイル（`tracker.area("大阪府枚方市")` と、わざと間違えた `tracker.area("大阪府枚方")`）に対する pyright の時間と結果。正しい方はエラー0件、間違えた方はエラー1件になること

**全体の時間が2倍を超える、または確認ファイルが期待どおりにならなければ、実装を止めて報告する。**

### 2.5 都道府県名の Literal 型 `Prefecture`（調査済み）

- 都道府県名は §2.2 と同じ方法（B列の先頭）で取る。47件。どの府県名も、区域コードの頭2桁とちょうど1対1に対応する（2026-11-12 に確認。区域数は最多が北海道の186、最少が17）。
- `_area_name.py` に一緒に生成する。
  ```python
  Prefecture = Literal["北海道", "青森県", ..., "沖縄県"]  # 頭2桁のコード順
  PREFECTURE_CODE: dict[Prefecture, str]  # "大阪府" → "27"
  AREAS_BY_PREFECTURE: dict[Prefecture, tuple[AreaName, ...]]  # 区域コード順
  ```
- 次の場合は生成を失敗させる：1つの府県名に頭2桁が2つ以上ある、またはその逆、件数が47でない。
- `Prefecture` も `pyjmaxml` から公開する。テストは §2.3 と同じ形で、件数47・1対1・`AREAS_BY_PREFECTURE` の合計が1,805になること。
- 北海道は気象庁の府県予報区では7つ（宗谷・上川留萌 など）に分かれているが、ここでは「北海道」1つにする（利用者にとって分かりやすい単位を優先。地方ごとの単位は §7 で作らないことにする）。

## 3. 公開 API

新しいモジュール `pyjmaxml/tracker/`（`__init__.py`・`_core.py`・`_sync.py`・`_async.py`）。
既存の `feed/` と同じく、**通信しない中身（`_core.py`）を、同期版と非同期版で共有する**。

```python
class Tracker:
    def __init__(
        self,
        areas: Iterable[AreaName] = (),  # 重複は1つにまとめる
        *,
        prefectures: Iterable[
            Prefecture
        ] = (),  # その府県のすべての区域を見る。areas と両方空なら ValueError
        user_agent: str | None = None,  # FeedClient に渡す
        http: HttpClient
        | None = None,  # テスト・差し替え用。FeedClient と同じ型（非同期版は AsyncHttpClient）
        clock: Callable[[], datetime]
        | None = None,  # FeedClient と同じ。apply(now=...) にも同じ時計を使う
    ) -> None: ...

    def update(self) -> UpdateResult: ...
    def area(self, name: AreaName) -> AreaView: ...  # 見ていない区域は ValueError
    def prefecture(
        self, name: Prefecture
    ) -> PrefectureView: ...  # prefectures にない府県は ValueError
    @property
    def areas(
        self,
    ) -> tuple[AreaName, ...]: ...  # 見ている区域すべて（prefectures の分を含む）。区域コード順
    @property
    def earthquake(self) -> EarthquakeInfo | None: ...  # 最後に受け取った VXSE51〜53
    @property
    def warning_state(self) -> WarningState: ...  # 細かく使いたい人向け
    @property
    def updated_at(self) -> datetime | None: ...  # 最後に update() が成功した時刻（UTC）


class AsyncTracker:  # update() が async。aclose() と async with に対応。他は Tracker と同じ
    ...


@dataclass(frozen=True)
class UpdateResult:
    changes: tuple[Change, ...]  # 見ている区域の警報の変化だけ
    errors: tuple[FeedError, ...]  # 取得に失敗したもの。update() は FeedError を投げない
    applied: int  # 使った電文の数


@dataclass(frozen=True)
class AreaView:
    name: AreaName
    code: str  # 7桁の区域コード
    warnings: frozenset[WarningKind]  # WarningState.by_city
    forecast: tuple[ForecastCell, ...]  # VPFD51 の by_city
    weekly_forecast: tuple[ForecastCell, ...]  # VPFW50 の by_city
    possibility: tuple[PossibilityCell, ...]  # VPFD60（明日まで）
    possibility_early: tuple[PossibilityCell, ...]  # VPFD61（早期注意情報、明後日まで）
    possibility_weekly: tuple[PossibilityCell, ...]  # VPFW60（明後日以降）
    timeseries: tuple[WarningTimeSeriesCell, ...]  # VPWP50 の by_city


@dataclass(frozen=True)
class PrefectureView:
    name: Prefecture
    code: str  # 頭2桁。例 "27"
    areas: tuple[AreaView, ...]  # その府県のすべての区域。区域コード順

    def area(self, name: AreaName) -> AreaView: ...  # この府県にない区域は ValueError
    def warned(self) -> tuple[AreaView, ...]: ...  # warnings が空でない区域だけ。区域コード順
```

- `AreaView`・`PrefectureView` は呼んだ時点の写し（あとで `update()` しても変わらない）。まだ電文がなければ空のタプル・空の集合。
- `prefectures=["大阪府"]` と `areas=["大阪府枚方市"]` を両方指定してもよい（重なりは1つにまとめる）。`area()` は、どちらかで見ている区域なら使える。
- `prefecture()` は `prefectures` で指定した府県だけ。`areas` で府県内の一部だけを見ているときに府県全体を返すと、見ていない区域が空に見えて誤解を招くため。
- `AreaName` を受け取る引数でも、実行時に名前を確認する（型検査を使わない利用者のため）。

## 4. `update()` の動き

### 4.1 使うフィードと電文

| フィード | 使う電文 | 府県で絞るか |
|---|---|---|
| EXTRA | VPWW55〜61、VXKO・VXSU | VPWW は絞る。VXKO・VXSU は絞らない（URL の規則を未確認のため） |
| REGULAR | VPWS50 | **絞らない**（URL が `_010000` だが中身は全国） |
| REGULAR | VPFD51・VPFW50・VPFD60・VPFD61・VPFW60・VPWP50 | 絞る |
| EQVOL | VXSE51・VXSE52・VXSE53 | 絞らない |

- 電文の種類は `Entry.title` から判断する。**`Entry.title` が電文の `Control/Title` と同じかを、録画済みのフィード（`tests/data/feed/*.xml`）とその電文で確かめてから**使う。違っていたら止めて報告する。種類の対応表は `pyjmaxml/kinds.py` の `_TITLE_CODES` を共有する（名前で引く関数を `kinds.py` に足す。公開はしない）。
- 表にない種類の電文は**取得せずに ack する**（VPFG50・VZSA50 など）。

### 4.2 府県での絞り込み（通信量を減らすため）

- 規則：電文 URL の末尾 `_<6桁>.xml` の**頭2桁**が、見ている区域のコードの頭2桁（都道府県）のどれかと同じなら取得する。違えば取得せずに ack する。`prefectures` で指定した府県も、`areas` で指定した区域の府県も同じ扱い（取得する電文は府県単位なので、通信量は変わらない）。
- 調査結果（2026-11-12 の長期フィード）：VPWP50 の58件、VPWW55〜61 の157件（府県と種類ごとの最新）で、電文の中の市町村コードの頭2桁が URL の頭2桁と**すべて一致**した。
  北海道は URL のコード（`012000` など）と `AREA_CITY` の府県予報区コード（`012010` など）が一致しないので、6桁全体では比べないこと。
- 天気予報の系統（VPFD51・VPFW50・VPFD60・VPFD61・VPFW60）でも同じ規則が成り立つかを、`tests/data/forecast/` と `tests/data/possibility/` の電文で確かめるテストを書く（区域コードの頭2桁）。
- 参考：絞らないと、regular だけで1日あたり約0.5GBになる（VPWS50 が約1MB×10分ごと、VPWP50 が1日に約470件）。

### 4.3 順番と例外

1. **最初の `update()`** だけ、EXTRA・REGULAR の長期フィード（`long=True`）を先に読む。README の「開始時は長期フィードも使う」の指示どおり。EQVOL は長期フィードを読まない（最新の地震だけでよいため）。
2. 続けて EXTRA・REGULAR・EQVOL の通常フィードを読む。
3. 各フィードの中は `poll()` が返す順（`updated` の古い順）で処理する。
4. 1件ごとの処理は README の例と同じ：
   - `fetch` で `FeedError` → `errors` に入れて ack しない（次回また取得）
   - `parse` で `ParseError` → ログに残して ack
   - `Control/Status` が「通常」でない → 使わずに ack
   - 警報系 → `WarningState.apply(report, now=現在時刻)`。`ValueError` はログに残して ack
   - 正規化する電文 → 正規化関数の `ValueError` はログに残して ack
5. `poll()` 自体の `FeedError`（`TooFrequentError` を含む）→ `errors` に入れて、そのフィードだけ飛ばす。ほかのフィードは続ける。前回までの結果は残す。
6. `FeedError` 以外の例外は呼び出し側に伝える。
7. 呼ぶ間隔は利用者が決める（60秒以上）。`update()` は待たない・自動で再試行しない。これは README に書く。

### 4.4 正規化した結果の持ち方

- 種類ごと・URL の6桁コードごとに、**`Control/DateTime` がいちばん新しい電文の結果だけ**を持つ。古い電文が後から届いたら捨てる。
- `AreaView` を作るときは、その種類の結果を全部見て、`by_city(code)` が空でない最初のものを返す（VPFW50 の広い区域への繰り上げは、既存の `WeatherForecast.by_city` に任せる）。
- 地震は VXSE51〜53 のうち `Control/DateTime` がいちばん新しいもの1件。
- 時刻は `clock()`（省略時は `datetime.now(UTC)`）。`_core.py` は時刻を引数で受け取る形にする。

## 5. テスト（`tests/test_tracker.py`・`tests/test_tracker_async.py`）

既存の `tests/feed_helpers.py`（録画したフィードとダミーの HTTP）を使う。気象庁にはアクセスしない。

1. 録画したフィードと電文で `update()` → `area()` の警報・天気予報・可能性・時系列が、同じ電文を低レベル API で処理した結果と一致する
2. 府県での絞り込み：見ていない府県の VPWW・VPFD51 は取得されない（ダミー HTTP へのリクエストを数える）。VPWS50 は府県によらず取得される
3. 表にない種類は取得されずに ack される
4. 最初の `update()` だけ長期フィードを読む
5. 取得失敗は `errors` に入り、ack されず、次の `update()` で再取得される。ほかのフィードの結果は更新される
6. 古い `Control/DateTime` の天気予報が後から届いても、新しい方が残る
7. `area()` に見ていない名前や存在しない名前を渡すと `ValueError`。`areas` と `prefectures` が両方空なら `ValueError`
7a. `prefectures=["北海道"]` で稚内市の VPWW55 を処理すると、`prefecture("北海道").warned()` に `北海道稚内市` が入り、`area("北海道稚内市")` と同じ結果になる。`areas` だけで指定した府県に `prefecture()` を呼ぶと `ValueError`
7b. `areas` と `prefectures` が重なっても、区域は1回だけ数えられる
8. 同期版と非同期版が同じ結果になる
9. §2.4 の pyright の確認ファイルは、`tests/` の下に置いて CI で pyright にかける（間違えた方は `# pyright: ignore` を使わず、別の方法を考えて報告する）

## 6. ドキュメント

- `README.md`：**最初の使用例を `Tracker` にする**。今の「フィードから市町村の警報を表示する」以下は、「低レベルな API」という見出しの下に移す（内容は変えない）。
  `Tracker` の節に書くこと：
  - 区域名の決まり（§2.2）と、分割された区域は別々に指定すること
  - 府県ごとに見る使い方（`prefectures=` と `prefecture()`・`warned()`）
  - `update()` は60秒以上空けて呼ぶこと。待たない・再試行しないこと
  - 見ている府県の電文だけを取ること。VPWS50 と地震は全国分を取ること
  - 再起動すると状態は消えること（保存したいときは `warning_state.to_json()`）
  - 出典表示（既存の「出典表示と利用上の注意」へのリンク）
- `tests/test_readme_example.py`：README の `Tracker` の例を、録画したデータで動かすテストを足す。
- `examples/`：`Tracker` を使う短い例を1つ足す（`--offline-sample` のような、通信しないで動く方法も用意する）。
- `CHANGELOG.md`、`IMPLEMENTATION_STATUS.md`（§2.4 の測定結果を含む）。

## 7. やらないこと

- 状態の保存・復元を `Tracker` 自体に持たせること（`warning_state` で足りる）
- 自動で待つ・自動で再試行する仕組み
- 区域名の省略形やあいまい検索（「枚方市」だけで引くなど）
- 分割された区域を親の市町村にまとめること（§2.1）
- 神戸市・広島市の区をまとめた「神戸市」などの名前
- 北海道の地方（宗谷・上川留萌 など）や「近畿」などの地方単位での指定
- 府県全体の天気予報・警報級の可能性をまとめた表示（区域ごとの `AreaView` で見る）
- VXKO・VXSU と地震の府県での絞り込み
- 河川の状態を `AreaView` に入れること（`warning_state.rivers()` を使う）

## 8. 完了条件

- `uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pyright --verifytypes pyjmaxml --ignoreexternal`（100%）、`uv run pytest` がすべて成功
- §2.4 の測定結果が `IMPLEMENTATION_STATUS.md` にあり、止める条件に当たっていない
- `git diff --check` 成功、新しい `.py` が LF
- 既存のテスト・golden・公開 API に変更なし（README の並べ替えを除く）
