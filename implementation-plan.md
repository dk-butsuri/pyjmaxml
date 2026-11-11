# jmadantic 実装計画

仕様・方針は [plan.md](plan.md) を正とする。この文書は、それを**実装の手順・判断・完了条件**に落としたもの。
一次資料の調査は 2026-11-11〜12 に実施した。資料が更新されたら、この文書も更新する。

---

## 実装担当者（AI を含む）への作業ルール

1. **`tests/golden/` の `case.json` と XML は変更禁止。** テストが通らないときは実装を直す。期待値が間違っていると思ったら、作業を止めて報告する
2. **サンプル全件パースのテストは `strict=True` で通すこと。** `strict=False` に切り替える、テストを skip / xfail にする、対象からファイルを外す、例外を握りつぶす、といった方法で通してはいけない
3. この文書と、実際の電文や一次資料が矛盾したら、**自分で設計を変えずに止まって報告する**。「どちらでもよい」と書いてあるところだけは、自分で判断してよい
4. 公開 API（`jmadantic/__init__.py` から見えるもの）に `Any` / `object` を出さない。`pyright --verifytypes jmadantic --ignoreexternal` で確認する（外部ライブラリの型の不備は対象外。理由は §4）
5. 1つのマイルストーンが終わるたびに、完了条件をすべて実行した結果を報告する
6. 気象庁のサーバーに、テストや CI からアクセスしない（M2 で使うフィードは `tests/data/feed/` に用意済み）

---

## 0. 調査結果（一次資料で確認済み）

### 0.1 配布物（https://xml.kishou.go.jp/tec_material.html）
| 種類 | ファイル | 更新日 |
|---|---|---|
| XSD 一式 | `jmaxml_20241031_Schema(xsd).zip`（jmx / jmx_ib / jmx_eb / jmx_eb_nullable / jmx_add / jmx_mete / jmx_seis / jmx_volc の8本） | 2024-10-31 |
| 辞書 | `jmaxml_20260129_dictionary.xlsx` | 2026-01-29 |
| コード表 | `jmaxml_20261110_code.xlsx`（管理表）、`jmaxml_20261110_Code.zip`（個別表 15本） | 2026-11-10 |
| サンプル電文 | `jmaxml_20260917_Samples.zip`（XML 546件） | 2026-09-17 |
| 解説資料 | `jmaxml_20261104_Manual(pdf).zip` | 2026-11-04 |
| 運用指針 | `jmaxml_guide_20130412.pdf`、`jmaxml_guide_20260430_head_control_list.pdf`（管理部・ヘッダ部の運用整理表） | |

- ダウンロード URL は `https://xml.kishou.go.jp/<ファイル名>`。ファイル名の `(` と `)` は `%28` と `%29` にエンコードする
- ファイル名に日付が入っているので、URL は固定できない

### 0.2 PULL型フィード（https://xml.kishou.go.jp/xmlpull.html）
- 高頻度（毎分更新、直近10分以上を掲載）：`https://www.data.jma.go.jp/developer/xml/feed/{regular,extra,eqvol,other}.xml`
- 長期（毎時更新、数日分を掲載）：同じ場所の `{regular,extra,eqvol,other}_l.xml`
- 電文の URL：`https://www.data.jma.go.jp/developer/xml/data/<YYYYMMDDhhmmss>_0_<データ種類コード>_<コード>.xml`
- 利用上の注意：**1日に10GB以上ダウンロードしたアクセス元はIPを遮断する**
- 実測（2026-11-11 の長期フィード）
  - VPWS50 は **regular** に配信される。約10分ごと（9〜10分間隔が大半）で、7日間に1011件。著者は「気象庁」。1件あたり約1MB
  - VPWW55〜61 は **extra** に配信される
  - 旧形式の VPWW53（気象特別警報・警報・注意報）と VPWW54（Ｈ２７）も、extra に**まだ並行して配信されている**
  - extra_l.xml は約3MB、regular_l.xml は約4.5MB

### 0.3 XSD と xsdata の実験結果（xsdata 26.10、Python 3.13）
- `Report` の Body は `xs:any namespace="##other" processContents="lax"` で、生成されたクラスでは `other_element: None | object` になる。xsdata は名前空間から Body を自動で解決し、`Body1`（火山）/ `Body2`（気象）/ `Body3`（地震）を返す
- サンプル 546件中 445件はそのまま通る。**101件は nullable 型（`jmx_eb_nullable.xsd`、`float | ""` の union）の空要素で失敗する**
  - 例：`<jmx_eb:Speed type="風速" unit="m/s"/>`。生成された `value: float | NullablefloatValue = field()` は必須なので、`TypeError: Speed.__init__() missing 1 required keyword-only argument: 'value'` になる
- `--structure-style namespaces` では `jmaxml1.py` と `jmaxml1/` のパッケージが衝突する。**`single-package` を使う**（約1.5万行の1ファイル）
- Windows では、xsdata が整形のために `ruff` をサブプロセスで呼ぶので、venv の `Scripts` を PATH に入れておかないと `FileNotFoundError` になる

### 0.4 新しい防災気象情報（R06 形式）の運用
- **2026-05-28 の午後に切り替わった**（法律上の運用開始は 5/29）。それ以降、VPWW55〜61・VPWS50・VPWP50 と、新しい名称の VXKO / VXSU が実際に配信されている
- VPWW53/54 は経過措置として並行配信が続いている。WarningState では扱わない（plan.md の非目標どおり）

### 0.5 電文の新旧と「取消」の扱い（運用指針 2.1.3）
- **独立した情報単位** ＝ `(Control/Title, Control/EditorialOffice, Control/Status, Head/EventID)` の組み合わせ（EventID が空なら空文字）
- 情報単位の中で有効な電文は、**`Control/DateTime` が最も新しいもの**だけ（Serial の順ではない）
- 「訂正」：その情報単位の直前の電文を訂正する。Control/DateTime は新しくなり、ReportDateTime は元の電文と同じことがある
- 「取消」：**その情報単位全体を取り消す**（1つ前の状態に戻すのではない）

### 0.6 警報系電文の構造（「気象警報・注意報（Ｒ０６）解説資料」と別表類、2026-11-11 の実電文）
- 電文種別：VPWW55 大雨 / 56 土砂 / 57 高潮 / 58 暴風（雪） / 59 波浪 / 60 大雪 / 61 その他注意報、VPWS50 集約通報、VPWP50 時系列
- VPWP50 は「発表状況を示すものではない」と明記されている → WarningState の入力にしない
- InfoType：VPWW55〜61 と VPWS50 は「発表／訂正」。VXKO / VXSU は「発表／訂正／取消」
- 市町村ごとの状態は、`Body/Warning[@type="気象警報・注意報（市町村等）"]/Item` にある（`Area/Code` が市町村等コード、`Kind` が0個以上）
- `Kind/Status` のとりうる値：発表、継続、特別警報から危険警報、特別警報から警報、特別警報から注意報、危険警報から警報、危険警報から注意報、警報から注意報、解除、発表警報・注意報はなし
  - **「解除」と「発表警報・注意報はなし」は、発表中ではない**。それ以外は発表中
  - 「発表警報・注意報はなし」の Kind には Name と Code がない
- VPWW の市町村等 Item には、その府県予報区等の**すべての市町村**が並ぶ（発表がない市町村も「なし」で並ぶ）
- **VPWS50 の市町村等 Item**
  - 発表中の Kind ごとに `DateTime type="発表時刻"` が付く。**この値は、その要素の VPWW の ReportDateTime と一致する**（実電文で確認済み。東京 VPWW59 の 22:06、鹿児島 VPWW61 の 21:22）
  - 発表がない市町村は、**Name も Code もない「発表警報・注意報はなし」の Kind が1つだけ**になる。どの要素についての「なし」なのかは区別できない
- Kind/Code → 電文種別の対応（別表1・別表3）

| 電文種別 | Kind/Code |
|---|---|
| VPWW55 大雨 | 10（レベル２注意報）, 03（レベル３警報）, 43（レベル４危険警報）, 33（レベル５特別警報） |
| VPWW56 土砂 | 29, 09, 49, 39（同じ順） |
| VPWW57 高潮 | 19, 08, 48, 38（同じ順） |
| VPWW58 暴風（雪） | 15 強風注意報, 13 風雪注意報, 05 暴風警報, 02 暴風雪警報, 35 暴風特別警報, 32 暴風雪特別警報 |
| VPWW59 波浪 | 16 注意報, 07 警報, 37 特別警報 |
| VPWW60 大雪 | 12 注意報, 06 警報, 36 特別警報 |
| VPWW61 その他 | 14 雷, 17 融雪, 20 濃霧, 21 乾燥, 22 なだれ, 23 低温, 24 霜, 25 着氷, 26 着雪, 27 その他の注意報 |
| （解除） | 00 |
| （予約） | 42, 45, 46, 47 → 未知のコードとして扱う |

### 0.7 氾濫（VXKO / VXSU）の構造
- 情報単位のキー：`Head/EventID`（VXKO は予報区域コード 例 `840410000100`、VXSU は発表区間コード 例 `8201813100`）
- 警報の種別：`Head/Headline/Information[@type="指定河川洪水予報（予報区域）"]`（VXSU では `"水位周知河川に関する情報（発表区間）"`）の `Item/Kind/Name` と `Code`
- コード（解説資料 表2）：10 ＝ レベル２氾濫注意報**解除**、20/21/22 ＝ レベル２氾濫注意報、30/31 ＝ レベル３氾濫警報、40/41 ＝ レベル４氾濫危険警報、51/53 ＝ レベル５氾濫特別警報
  - 令和8年度の出水期より前の旧名称（氾濫注意情報など）も、コードは同じ
- 対象の市町村：Body の中にある `CityCode` 要素（VXKO は浸水想定地区の Item、VXSU は `Warning[@type="水位周知河川に関する情報（浸水想定地区）"]`）。重複を除いて使う
- 予告されている新しい電文 **VXKPii** は運用日が未定 → 対象外。ディスパッチ表に1行足せば対応できる構造にしておく

---

## 1. 決めたこと

| 項目 | 決定 |
|---|---|
| パッケージ名 | `jmadantic`（PyPI 未使用。2026-11-11 に確認） |
| Python | 3.11 以上（CI は 3.11 / 3.12 / 3.13） |
| ツール | uv、hatchling、ruff、pyright（strict）、pytest、GitHub Actions |
| 生成 | xsdata 26.10 に固定、`single-package`、出力先は `jmadantic/_generated/jmx.py` |
| Body の型 | 公開 API では `MeteBody \| SeisBody \| VolcBody \| UnknownBody` |
| strict | `parse(data, *, strict=False)`。strict のときは `ParserConfig(fail_on_unknown_properties=True, fail_on_converter_warnings=True)` |
| 時刻 | 公開 API では `datetime`（tz 付き）にする。xsdata の `XmlDateTime` を外に出さない |
| HTTP | `HttpClient` Protocol。デフォルトは `urllib.request`、extra で `jmadantic[httpx]` |
| 同期 / 非同期 | フィードは sans-IO（`FeedPoller`）＋ 薄い同期層（`FeedClient`）。非同期の `AsyncFeedClient` は M2b として後から足す。`parse` と状態管理は I/O なしなので、どちらからでも使える |
| `apply` の戻り値 | `ApplyResult(applied: bool, skip_reason: SkipReason \| None, changes: tuple[Change, ...])`。plan.md の `list[Change]` から変更（スキップの理由をテストするため） |
| 永続化 | `to_json() -> str` / `from_json(s) -> Self`。トップレベルに `"version": 1` を入れる。重複除去と新旧判定の記録も含める |

---

## 2. マイルストーン

### M0. リポジトリの土台
1. `git init`。`.gitignore` に `vendor/`、`.venv/`、`__pycache__/`、`dist/`
2. `pyproject.toml`
   - `[project]` name=jmadantic、requires-python=">=3.11"、dependencies=["xsdata>=26.10,<27", "lxml>=5"]
   - optional：`httpx = ["httpx>=0.27"]`
   - dev（dependency-groups）：pytest、pyright、ruff、openpyxl、`xsdata[cli]`
3. pyright：`strict = ["jmadantic"]`、`exclude = ["jmadantic/_generated"]`
4. ruff：`extend-exclude = ["jmadantic/_generated"]`
5. `.github/workflows/ci.yml`：`uv sync` → `ruff check` → `pyright` → `pytest`（3.11 / 3.12 / 3.13）
6. `jmadantic/__init__.py`（空）と `jmadantic/py.typed`
- **完了条件**：ローカルで `uv run ruff check && uv run pyright && uv run pytest` が通る（テスト0件で OK）

### M1. codegen と parse
1. `scripts/manifest.toml`：§0.1 の XSD・サンプル・コード表のファイル名と SHA-256（初回ダウンロード時に記録する）
2. `scripts/codegen.py`（`uv run python scripts/codegen.py` で動くこと）
   - manifest のファイルを `vendor/` にダウンロードする（既にあり、SHA-256 が一致すれば取得しない）。展開も行う
   - `xsdata generate vendor/schema/jmx.xsd --package jmadantic._generated.jmx --structure-style single-package` を実行する
   - **後処理**（生成された `jmx.py` を書き換える）：注釈に `Nullable` を含む `value` フィールドを、`value: <元の注釈> | None = field(default=None)` に変える。正規表現でも libcst でもよい
     - 書き換えた箇所の数を出力する。0件ならエラー終了にする（xsdata の出力形式が変わったことに気づくため）
   - `Body1/2/3` などの連番クラスについて、`Meta.namespace` を見て、`jmadantic/_generated/aliases.py` に `MeteBody = Body2` のような別名を出力する（連番がずれても名前空間で対応付けるようにし、番号を決め打ちしない）
   - 生成ファイルの先頭に、生成元のファイル名・SHA-256・xsdata のバージョンをコメントで入れる
   - サンプル zip を `tests/data/samples/` に展開する（XML だけ。コミットする）
3. `jmadantic/parse.py`
   - `parse(data: bytes | str | os.PathLike[str], *, strict: bool = False) -> Report`
   - bytes の先頭が `1f 8b` なら gzip として展開する
   - `Report` は自前の frozen dataclass：`control: Control`、`head: Head`、`body: Body`、`raw: <生成された Report クラス>`
     - `Control`：title, date_time(datetime), status, editorial_office, publishing_office
     - `Head`：title, report_date_time, target_date_time, event_id(str、空なら ""), info_type, serial(str、空なら ""), info_kind, info_kind_version, headline_text
   - Body の名前空間が未知なら、strict=False のときは `UnknownBody(namespace: str, xml: bytes)`、strict=True のときは `ParseError`
4. `jmadantic/kinds.py`：`data_type_code(report) -> str | None`
   - 対応表は `jmaxml_guide_20260430_head_control_list.pdf` から作る（Control/Title → データ種類コード）。少なくとも次の電文は必ず含める
     - `気象警報・注意報（Ｒ０６）（大雨）` → VPWW55 …（その他注意報）→ VPWW61
     - `気象警報・注意報（Ｒ０６）（集約通報）` → VPWS50
     - `気象警報・注意報時系列情報（Ｒ０６）` → VPWP50
     - `指定河川洪水予報` → VXKO
     - `水位周知河川に関する情報` → VXSU
     - `気象警報・注意報（Ｈ２７）` → VPWW54
     - `気象特別警報・警報・注意報` → VPWW53
   - 全角の「Ｒ０６」はそのまま比べる（正規化しない）
5. `tests/test_samples.py`：`tests/data/samples/*.xml` を parametrize し、`parse(path, strict=True)` が成功すること、Body が `UnknownBody` でないことを確認する
- **完了条件**
  - `pytest tests/test_samples.py` で 546件すべて成功
  - `codegen.py` をもう一度実行しても `git diff` が空
  - pyright strict でエラー 0（`_generated` は除く）

### M2. フィード
I/O を持たない中核（`FeedPoller`）と、通信だけを担当する薄い層（`FeedClient`）に分ける（sans-IO）。非同期版は、通信層を1つ足すだけで作れるようにしておく。

1. `jmadantic/feed/_core.py`（**I/O なし**。ネットワーク・時計・スレッドに触らない）
   - `FeedKind`（REGULAR / EXTRA / EQVOL / OTHER）と `long: bool` から URL を組み立てる
   - `Entry`（frozen）：id, title, updated(datetime), author, url
   - `HttpRequest`（frozen）：method, url, headers。`HttpResponse`（frozen）：status, headers, body(bytes)
   - `FeedPoller(kind, *, long=False, seen=None, min_interval=None, unsafe_min_interval=False)`
     - `next_request(now: datetime) -> HttpRequest`：ETag / Last-Modified を付けた条件付きGETを組み立てる。前回から最小間隔が経っていなければ `TooFrequentError`
     - `handle_response(resp: HttpResponse, now: datetime) -> list[Entry]`：304 なら `[]`。200 なら Atom を解析し、ETag / Last-Modified を記録して、まだ見ていない id のエントリーだけを返す（返したものは seen に記録する）
     - `entry_request(entry) -> HttpRequest`：電文本体を取得するリクエストを組み立てる
   - 最小間隔：高頻度 60秒、長期 3600秒。`min_interval` で長くはできるが、短くするには `unsafe_min_interval=True` が必要
   - `SeenStore` Protocol（`__contains__`、`add`）。デフォルトは上限 10,000件の LRU
   - User-Agent：`jmadantic/<version> (+https://github.com/<repo>)`。ヘッダーは `next_request` / `entry_request` で付ける
2. `jmadantic/feed/_sync.py`：`FeedClient(kind, *, long=False, http=None, seen=None, clock=None, ...)`
   - `HttpClient` Protocol：`send(req: HttpRequest) -> HttpResponse`。デフォルトは `urllib.request` の実装。`jmadantic[httpx]` が入っていれば httpx の実装も選べる
   - `poll() -> list[Entry]`：`next_request` → `http.send` → `handle_response` を行うだけ
   - `fetch(entry) -> bytes`：`entry_request` → `http.send` → body を返す（gzip のままでもよい。`parse` が対応している）
   - **ロジックを書かない**。分岐が必要になったら `_core.py` に入れる
3. `jmadantic/feed/__init__.py`：`FeedKind`、`Entry`、`FeedPoller`、`FeedClient`、`SeenStore`、`TooFrequentError` を再エクスポートする
4. テスト
   - `tests/test_feed_core.py`：`FeedPoller` を直接テストする（200 → 304 → 新しいエントリーあり、重複 id、間隔違反、ヘッダー）。`now` は引数で渡す
   - `tests/test_feed_sync.py`：偽の `HttpClient` で `FeedClient` が `FeedPoller` に正しく橋渡ししていることだけ確認する
   - 録画したフィードは **`tests/data/feed/` に用意済み**（2026-11-12 取得。本文・レスポンスヘッダー・304 のヘッダー。詳細は同じ場所の README）。新たに取得しない
   - 実測：ETag は弱い ETag（`W/"..."`）、`Last-Modified` あり、`Cache-Control: max-age=60`、条件付き GET には 304 が返る
- **完了条件**：上のテストが通る。ネットワークにアクセスするテストはない。`_core.py` が `urllib`・`httpx`・`time`・`socket` を import していない（テストで確認する）

#### M2b. 非同期（今は作らない。必要になったら追加）
- `jmadantic/feed/_async.py`：`AsyncFeedClient`。`AsyncHttpClient` Protocol（`async def send(req) -> HttpResponse`）、デフォルト実装は `httpx.AsyncClient`（extra 必須）
- `poll()` / `fetch()` を `async def` にして、中身は `_sync.py` と同じ橋渡しだけにする。`FeedPoller` は共有する
- テストは `tests/test_feed_async.py` で橋渡しだけ確認する（`FeedPoller` のテストは使い回す）
- `parse` と `WarningState` は I/O をしないので、非同期版は不要

### M3. コード表と正規化
1. `scripts/codegen.py` に追加：コード表の xlsx から `jmadantic/codes/_area_city.py` などを生成する（中身は dict 定数。**実行時に openpyxl を使わない**）
   - `AreaInformationCity-AreaForecastLocalM`：市町村等コード → (名称, 府県予報区コード, 一次細分区域コード)
   - `AreaFloodForecast`、`AreaWaterLevelWarning`：予報区域・発表区間コード → 名称
2. `jmadantic/normalize/warning.py`
   - `Element`：HEAVY_RAIN, LANDSLIDE, STORM_SURGE, STORM, SNOWSTORM, HIGH_WAVE, HEAVY_SNOW, FLOOD, OTHER, UNKNOWN
   - `Stage`（IntEnum、この順に大きい）：ADVISORY, WARNING, DANGER_WARNING, EMERGENCY
   - `WarningKind`（frozen dataclass）：`name: str`、`code: str`、`group: str`（"VPWW55"…"VPWW61"、"VXKO"、"VXSU"）、`element: Element`、`stage: Stage | None`、`level: int | None`
   - `classify_mete(code, name) -> WarningKind`：§0.6 の表から作る。レベルは Name の「レベルＮ」から取る。暴風（雪）・波浪・大雪・その他は level=None
   - `classify_flood(code, name, group) -> WarningKind`：§0.7 の表から作る
   - 未知のコードは例外にせず、`element=UNKNOWN, stage=None` にして `logging` で warning を出す
   - 述語：`Predicate` は `Callable[[WarningKind], bool]` をラップしたクラスで、`&`・`|`・`~` が使える。`level_at_least(n)`、`stage_at_least(stage)`、`element_in(*elements)` を用意する
   - `rank(kind) -> tuple[int, int]` ＝ `(stage の値 または -1, level または 0)`
- **完了条件**：サンプルと `tests/golden/_shared/` に出てくる Kind/Code（00 と「なし」を除く）がすべて UNKNOWN 以外に分類される。これをテストにする

### M4. 状態管理
§3 の設計どおりに実装する。
- **完了条件**：`tests/test_golden.py`（ランナーの要件は `tests/golden/README.md`）で 12ケースすべてが通る。pyright strict でエラー 0。**`tests/golden/` に差分がない**

### M5. ドキュメントと公開
- README（日本語）：インストール、最小の使用例（フィードをポーリングして、ある市町村の警報を表示する）、出典表示、免責（気象庁は内容を保証しない。防災判断は公式の発表で行うこと）
- 出典表示の文言は、気象庁ホームページの「ご利用にあたって」（https://www.jma.go.jp/jma/kishou/info/coment.html）に従う
- `CHANGELOG.md`、バージョン 0.1.0
- TestPyPI に出してから PyPI に出す（Trusted Publishing）。**公開の操作は人間が行う**
- **完了条件**：clean な venv で `pip install` してから README の例が動く

---

## 3. 状態管理層の設計（M4）

### 3.1 共通
```python
class SkipReason(StrEnum):
    STATUS = "status"  # Control/Status が受け付け対象外
    UNSUPPORTED = "unsupported"  # この State の対象外の電文
    DUPLICATE = "duplicate"  # 同じ電文を既に適用した
    STALE = "stale"  # 同じ情報単位で、より新しい電文を既に適用した


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    skip_reason: SkipReason | None
    changes: tuple[Change, ...]
```
`apply(report)` は、上から順に判定する。
1. `control.status` が `accept_status`（デフォルト `{"通常"}`）にない → STATUS
2. `data_type_code(report)` が対象外 → UNSUPPORTED
3. 電文キー `(title, editorial_office, status, event_id, control.date_time, info_type, serial)` を既に見ている → DUPLICATE
4. 情報単位 `(title, editorial_office, status, event_id)` の最後の `control.date_time` 以前 → STALE
5. 適用する。電文キーを記録し、情報単位の最新時刻を更新する

### 3.2 WarningState の内部状態
- **気象セル**：`(市町村等コード, 電文種別)` → `Cell(kinds: frozenset[WarningKind], as_of: datetime)`
  - `as_of` は、その中身の根拠になった **VPWW の ReportDateTime**（VPWS50 から来た場合は Kind/DateTime）
- **河川**：`EventID` → `River(group: "VXKO" | "VXSU", kinds: frozenset[WarningKind], cities: frozenset[str], as_of: datetime)`

### 3.3 更新ルール
**VPWW55〜61（電文種別 g、ReportDateTime T）**
- `Warning[@type="気象警報・注意報（市町村等）"]` の各 Item（市町村 c）について：
  - 発表中の Kind（§0.6 の Status による）を `WarningKind` にした集合を K とする
  - 既存セルがない、または `T >= cell.as_of` なら、`cell(c, g) = Cell(K, T)` にする（K が空でもセルは作る）
  - `T < cell.as_of` なら変更しない

**VPWS50**
- W ＝ 電文に含まれるすべての `Kind/DateTime` の最大値（取り込み済みの最新の VPWW の時刻）
- 各 Item（市町村 c）について：
  - 発表中の Kind を、Code から電文種別 g ごとにまとめる（Kind/DateTime はグループの中で同じ。違っていたら最大値を使う）→ `{g: (K_g, d_g)}`
  - 現れた g について：既存セルがないか `d_g >= cell.as_of` なら、`cell(c, g) = Cell(K_g, d_g)` にする
  - 既存セルがあるのに現れなかった g について：`cell.as_of <= W` なら `Cell(∅, W)` にする。`cell.as_of > W`（VPWS50 の集約より後の VPWW が先に届いている）なら変更しない
- Item に出てこない市町村は変更しない
- `Warning[@type="気象警報・注意報（市町村等）"]` そのものがない場合（全国で発表なし。サンプルがないため推定）：`as_of <= ReportDateTime` の全セルを空にする

**VXKO / VXSU（キー e ＝ EventID）**
- InfoType が「取消」：河川 e を削除する
- それ以外：§0.7 の Kind を分類する。Code が 10（解除）なら河川 e を削除する。それ以外なら `River(group, {kind}, CityCode の集合, ReportDateTime)` で置き換える

### 3.4 Change
```python
class ChangeType(StrEnum):
    ISSUED, UPGRADED, DOWNGRADED, CHANGED, CANCELLED


@dataclass(frozen=True)
class Change:
    scope: Literal["city", "river"]
    area: str  # 市町村等コード、または EventID
    group: str  # "VPWW55"…"VPWW61"、"VXKO"、"VXSU"
    type: ChangeType
    before: frozenset[WarningKind]
    after: frozenset[WarningKind]
    at: datetime  # 根拠になった時刻（as_of）
```
- 気象：更新したセルごとに、前後の kinds を比べる（セルがなかった場合は前を ∅ とする）。河川：河川ごとに比べる（削除した場合は後を ∅ とする）
- 分類
  - 前と後が同じ（Kind の name と code の集合で比べる） → Change を出さない
  - 前 ∅ → 後 ≠∅：ISSUED
  - 前 ≠∅ → 後 ∅：CANCELLED
  - 両方 ≠∅：`max(rank)` を比べて、上がれば UPGRADED、下がれば DOWNGRADED、同じなら CHANGED
- 並び順：scope → area → group の昇順

### 3.5 照会 API
```python
state.by_city(code: str) -> frozenset[WarningKind]           # 全電文種別の気象セル ∪ その市町村を cities に含む河川の kinds
state.cities(pred: Predicate | None = None) -> Mapping[str, frozenset[WarningKind]]  # 空集合の市町村は含めない
state.rivers() -> Mapping[str, River]
state.last_updated -> datetime | None                         # 最後に適用した電文の Control/DateTime
```

### 3.6 永続化
`to_json()` には、セル・河川・電文キーの記録（上限 10,000件、古いものから捨てる）・情報単位ごとの最新時刻を含める。`WarningKind` は name・code・group だけを保存し、読み込み時に分類し直す。datetime は ISO 8601（tz 付き）。

---

## 4. テスト
- `tests/test_samples.py`：M1
- `tests/test_feed.py`：M2
- `tests/test_normalize.py`：M3
- `tests/test_golden.py`：M4。**ケースと期待値は `tests/golden/` に作成済み（12ケース）**。形式とランナーの要件は `tests/golden/README.md`
  | ケース | 確認すること |
  |---|---|
  | g01 | 発表 → 切替（DOWNGRADED）→ 解除（CANCELLED） |
  | g02 | 訂正（ReportDateTime が同じで、Control/DateTime が新しい） |
  | g03 | 訓練・試験の電文を無視する |
  | g04 | 逆順に届いた古い電文を STALE として捨てる |
  | g05 | 二重に届いた電文を DUPLICATE として捨てる |
  | g06a / g06b | VPWW と VPWS50 の併用。順番が逆でも同じ状態になる（実電文） |
  | g06c | VPWS50 より新しい VPWW を、VPWS50 の「なし」で消さない（W のルール） |
  | g07 | 対象外の電文（VPWW54、VPWP50）を UNSUPPORTED として捨てる |
  | g08 | VXKO の発表 → 引上げ（UPGRADED）→ 取消 |
  | g09 | VXSU の発表 → 解除 |
  | g10 | to_json / from_json の往復と、重複除去の記録の引き継ぎ |
- `pyright --verifytypes jmadantic --ignoreexternal` で、公開 API の型の完全性を 100% にする
  - `--ignoreexternal` を付ける理由：`Report.raw`（xsdata の生成クラス）から、xsdata 26.10 の `XmlDuration.asdict()` が見える。この戻り値の注釈が型引数なしの `dict` なので、外部の型を含めると 85.3% になる（2026-11-12 に確認）。jmadantic 自身のコードに `Any` を出さないことが目的で、外部ライブラリの注釈の不備は対象外とする。外部の型のスタブは自前で書かない

---

## 5. 未確定事項
| # | 内容 | 状態 |
|---|---|---|
| U1 | R06 への運用切替日 | **確定**：2026-05-28 午後（§0.4） |
| U2 | VPWS50 の配信間隔と Kind/DateTime の意味 | **確定**：約10分ごと。Kind/DateTime ＝ その要素の VPWW の ReportDateTime（§0.2、§0.6） |
| U3 | 取消の意味 | **確定**：情報単位全体の取消（§0.5） |
| U4 | Control/Title → データ種類コードの対応表（全電文） | M1 で `head_control_list.pdf` から作る。§2 M1-4 の7種類は確定済み |
| U5 | フィードのポーリング間隔の推奨値 | 明記なし。毎分更新なので最小 60秒とする（§2 M2） |
| U6 | 出典表示の文言 | M5 で確認する |
| U7 | VPWS50 で、市町村等の Warning が丸ごと省略されることがあるか | サンプルなし。§3.3 の推定で実装し、実電文で見つけたらテストを追加する |

---

## 6. リスク
- **XSD の更新**：zip の名前が日付入りなので、更新に気づけない → 月に1回 CI で `tec_material.html` のリンクと manifest を比べ、違えば Issue を立てる（M5 以降）
- **xsdata の出力形式が変わる**：後処理が効かなくなる → xsdata のバージョンを固定し、後処理の対象が0件ならエラーにする（M1）
- **VPWS50 の W ルールの前提**（VPWS50 は、W 以前の VPWW をすべて取り込んでいる）が崩れる → 崩れても、次の VPWW か次の VPWS50（約10分後）で正しい状態に戻る。影響は最大10分程度
- **生成コードが巨大**（1.5万行）：import 時間を測る（目安は 300ms 以内）
