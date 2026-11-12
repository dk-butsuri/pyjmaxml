# 実装状況（2026-11-12）

> **2026-11-12：履歴を書き換えた。** 最初の push の前に、ゴールデンテストの素材作成スクリプトに含まれていたローカル PC のパスを、全コミットから取り除いた。続けて、Co-Authored-By の名前を `claude-model-2` に変えた（GitHub へは force push で反映）。このため、以下の記録に出てくるコミットのハッシュは古いものになっている。対応は次のとおり。
>
> | 古いハッシュ | 新しいハッシュ | コミット |
> |---|---|---|
> | `b5af5f6` | `9a24330` | M0〜M1: リポジトリの土台、codegen、parse、ゴールデンテストの素材 |
> | `bd96946` | `c8a4044` | M2 用に録画したフィードを追加し、検証ルールを更新 |
> | `4dd2753` | `7173cb2` | M2: フィードの取得（sans-IO の FeedPoller と同期の FeedClient） |
> | `e2556c2` | `9561fda` | 計画：フィードに ack と user_agent を追加 |
> | `1b754e7` | `feeee31` | M2 の手直し：ack と user_agent、M3 の完了条件の範囲を修正 |
> | `8cd071f` | `b14ba76` | 計画：M3 の全件分類の対象を、WarningState が扱う電文に限定 |
> | `657ec7d` | `8c34321` | M3: コード表の生成と警報種別の正規化 |
> | `a569071` | `972ff4a` | 計画：分割された市町村等と氾濫の照会を対応付ける（AREA_CITY_PARENT） |
> | `db47d38` | `756b2b9` | M4: 状態管理（WarningState） |
> | `71c42be` | `6ff9c16` | VPWS50 の高速化と M5（ドキュメント、0.1.0） |
> | `2cac749` | `f0b7075` | パッケージ名を jmadantic から pyjmaxml に改名 |

> **2026-11-12：パッケージ名を `jmadantic` から `pyjmaxml` に改名した。** 以下の記録は改名前に書かれたもので、`jmadantic` はすべて `pyjmaxml` と読み替える。

## M0

実装済み。Git 初期化、uv/hatchling、依存ロック、ruff、pyright strict、
Python 3.11 / 3.12 / 3.13 の CI 設定を追加。
ローカル検証に使用した Python は 3.13.7。CI 自体は未実行。

## M1

実装済みの範囲：

- 公式配布物のファイル名・取得日・SHA-256 を manifest に記録。
- xsdata 26.10 による生成と、nullable value 28箇所の後処理。
- 名前空間から Body 別名を生成。xsdata がパッケージ名の先頭の `_` を除去するため、
  一時ディレクトリに生成し、`jmadantic/_generated/` に配置する。
- `parse`、frozen な Report/Control/Head、gzip、未知の Body、strict モード。
  `str` は XML 本文、ファイルパスは `Path` として受け取る。
  TargetDateTime は XSD の nillable 指定に従い `datetime | None`。
- Control/Title の完全一致による電文種別判定。複数の番号付きコードが同じタイトルを
  共有する電文は、タイトルだけでは一意に判定できないため `None`。
- サンプル XML 546件と、パーサー・種別判定・生成処理のテスト。

検証結果：

- `uv run ruff check`：成功。
- `uv run ruff format --check`：成功。
- `uv run pyright`：エラー・警告0件。
- `uv run pytest -q`：587件成功。公式サンプル546件はすべて `strict=True`。
- 再生成前後の Python ソース・全サンプルを `git diff --no-index` と SHA-256 で比較：差分なし。
  `tests/golden/` は変更していない。
- `import jmadantic`：257.5 ms（この Windows / Python 3.13 環境での1回の測定）。

未決の検査方針：

指定された生成 Report の `raw` から参照する xsdata 26.10 の
`XmlDuration.asdict()` が、型引数のない `dict` を返す注釈になっている。
`uv run pyright --verifytypes jmadantic` は完全性85.3%で失敗する（最終エクスポートで再確認）。
`--ignoreexternal` を付けた診断では100%だが、計画の検査条件は変更していない。
外部型を除外するか、外部型スタブを設計して完全な検査を維持するか確認待ち。

## 次の段階

M2（フィード）、M3（コード表と正規化）、M4（状態管理）、M5（ドキュメントと公開）は未実装。
公開操作は実装計画どおり人間が行う。

## 開発コマンド

```sh
uv sync --locked --all-extras
uv run python scripts/codegen.py
uv run ruff check
uv run pyright
uv run pytest
```

codegen だけが、キャッシュに配布物がない場合にダウンロードする。
テストはローカルの素材だけを読み、気象庁へアクセスしない。
Windows の制限された実行環境では uv のキャッシュと pytest の一時領域を
書き込み可能な場所に設定する必要がある。今回の検証では
`UV_CACHE_DIR=vendor/uv-cache`、`TEMP` / `TMP` は作業ディレクトリ内の `tmp` を使用した。

## M2 着手時の停止記録（2026-11-12）

計画・録画フィード・既存実装を読み取り確認した時点で、以下の未確定点が見つかったため、
今回の依頼の「判断に迷うことがあったら、実装を進めずに記録して止まる」に従って停止した。

- 計画 §2 M2-1 は User-Agent を
  `jmadantic/<version> (+https://github.com/<repo>)` と指定しているが、
  `<repo>` に入れるリポジトリURLが未指定。
- `git remote -v` の出力は空で、`.git/config` に remote 設定がない。
  `pyproject.toml` にもプロジェクトURLの定義がない。
- URLを推測する、プレースホルダーをそのまま送る、URL部分を省略する、のいずれも
  採用せず、User-Agent に記載するURLの指定を待つ。

今回の操作と検証状況：

- 変更したファイルはこの状況記録のみ。M2 のコード・テストはまだ作成していない。
- M2 の完了条件（core/sync テスト、ネットワーク非アクセスの検証、
  `_core.py` の禁止 import 検査）は未実行。M2 は未完了。
- verifytypes の条件が `pyright --verifytypes jmadantic --ignoreexternal` で100%に
  変更されたことを確認した。上記 M1 の「検査方針の確認待ち」は、この計画変更により解消。
  今回の verifytypes 再実行は行っていない。
- 気象庁へのアクセス、録画フィード・`tests/golden/` の変更、git commit は行っていない。
- M2b および M3 以降には着手していない。

## M2 実装・検証結果（2026-11-12）

上記の停止後、ユーザーから「URLは未確定事項として残し、依存しない部分を先行する」
方針で続行する指示を受け、M2 の実装と以下の検証を実施した。

実装内容：

- `jmadantic/feed/_core.py`：FeedKind、frozen な Entry / HttpRequest / HttpResponse、
  FeedPoller、SeenStore と既定の上限10,000件の LRU。
  ヘッダーは生成時にコピーし、読み取り専用の Mapping として保持する。
- 高頻度・長期の4種別のURL、タイムゾーン付き Atom 時刻、弱いETagをそのまま使う
  条件付きGET、304、応答内・応答間のID重複除去。
- 最小間隔は高頻度60秒・長期3600秒。`min_interval` の単位は秒。
  短縮には `unsafe_min_interval=True` が必要。
  間隔は `next_request` の呼び出し間で測り、通信失敗も試行として数える。
  自動リトライや sleep は行わない。
- 不正なフィードは、全エントリーの解析に成功する前に既読IDや検証子を更新しない。
  ヘッダー名は大文字・小文字を区別しない。304では省略された検証子を維持し、
  新しい200応答にない検証子は破棄する。
- `jmadantic/feed/_sync.py`：FeedClient。poll / fetch は中核・通信・注入した時計への
  橋渡しのみ。fetch は時計を読まず、gzip の電文本体もそのまま返す。
- `jmadantic/feed/_http.py`：HttpClient Protocol、既定の UrllibHttpClient、
  選択可能な HttpxHttpClient。urllib の HTTPError（304を含む）は HttpResponse に変換し、
  HTTPステータスの判定は中核で行う。接続などの通信例外は呼び出し元に伝える。
  httpx は選択時にだけ import する。注入した httpx.Client は呼び出し元が所有し、
  アダプター自身が作ったクライアントはその `close()` で解放する。
- `jmadantic/feed/__init__.py` から計画指定の6項目と、差し替え通信層の型・例外を公開。
- CI に `uv run pyright --verifytypes jmadantic --ignoreexternal` を追加。
  CI 自体は今回実行していない。

保留事項：

- User-Agent のリポジトリURLは引き続き未確定。
  今回承認された先行実装では `jmadantic/0.1.0` を使い、URLもプレースホルダーも送らない。
  `_core.py` の `_USER_AGENT` に明記しており、URL確定後に計画の形式へ更新する必要がある。
  バージョン値は時計やファイルへのアクセスが不要な `_version.py` に置き、
  パッケージメタデータと一致することをテストした。

M2 の完了条件を実行した結果（Python 3.13.7 / Windows）：

- `uv run --offline pytest tests/test_feed_core.py tests/test_feed_sync.py tests/test_feed_http.py -q`
  ：70件成功（core 46件、同期層14件、通信アダプター10件）。
  録画200→304→新規エントリー、重複ID、間隔違反、ヘッダー、偽HTTPによる同期層の
  橋渡し、urllibの304変換、httpx MockTransportを検証した。
- `tests/conftest.py` の autouse fixture で全テストの DNS 解決・ソケット接続を禁止。
  テストの通信には偽HTTP、urlopenの置き換え、httpx MockTransportだけを使用した。
  気象庁へのアクセスは実施していない。
- `test_core_has_no_network_clock_or_thread_imports`：成功。
  ASTで `_core.py` に urllib / httpx / time / socket / threading / asyncio の import がないことと、
  now / utcnow / today / sleep の呼び出しがないことを確認した。
- `test_poll_and_fetch_contain_only_bridging_without_branches`：成功。
- `uv run --offline pytest -q`：657件成功、skip / xfail なし。
  公式サンプル546件のパースは既存の `strict=True` のまま成功。
- `uv run --offline ruff check` と `uv run --offline ruff format --check`：成功。
- `uv run --offline pyright`：エラー0件、警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：型の完全性100%。
- 着手前後の SHA-256 比較で `tests/golden/` 30ファイル、録画フィード6ファイル、
  公式サンプル素材547ファイルがすべて一致。
  `git diff --exit-code -- tests/golden tests/data/feed tests/data/samples` も差分なし。

M2b、M3以降、公開操作、git commit は行っていない。ここで作業を停止する。

## M2 手直し：ack と User-Agent（計画 e2556c2、2026-11-12）

実装済み。既読IDの記録を返却時から `ack(Entry | str)` 時に変更した。
FeedPoller は未処理を発見順に保持し、200でも304でも全未処理を返す。
フィードから消えた未処理も保持する。上限1,000件を超えると古いものから破棄して
warning を出す。未処理は永続化しない。FeedClient.ack は中核への直接の橋渡しとし、
fetch は成功・失敗にかかわらず ack しない。

User-Agent は既定 `jmadantic/<version>`、`user_agent` で上書き可能にした。
空文字を拒否し、フィード・電文本体の両方に指定値を付ける。
リポジトリURLは計画から削除されたため、従来のURL保留事項は解消した。
README に処理成功後の ack、未処理の保持・上限・再起動時の扱いを記載した。

M2 完了条件の実行結果（M3 着手前、Python 3.13.7 / Windows）：

- `uv run --offline pytest tests/test_feed_core.py tests/test_feed_sync.py tests/test_feed_http.py -q`
  ：84件成功。追加された ack の全ケース、User-Agent の既定値・上書き・空文字、
  fetch失敗後の再返却と成功時の非ackを検証した。
- 禁止 import / 時計呼び出しの AST 検査、同期層の poll / fetch / ack が
  分岐を持たないことの検査：上記テスト内で成功。
- 全テストで DNS 解決・ソケット接続を禁止する既存ガードを有効にしたまま、
  録画素材・偽HTTP・httpx MockTransportだけを使用。気象庁へのアクセスなし。
- `uv run --offline pytest -q`：671件成功、skip / xfail なし。
  公式サンプル546件はすべて既存の `strict=True` で成功。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：100%。
- `git diff --exit-code -- tests/golden tests/data/feed tests/data/samples`：差分なし。
- git commit、M2b、M4以降の実装は行っていない。次にM3のローカル資料を調査する。

## M3 調査時の停止記録（計画 e2556c2、2026-11-12）

M2の手直しの実装・検証・記録を完了した後に調査を開始した。
コード表の配布物はローカルに存在し、manifest の SHA-256 と一致することを確認した。

- `vendor/jmaxml_20261110_Code.zip`：
  `54e287e84c0f15a2ad2227dee8cb6040fdb697b0f5bd40a5affdf18ba69931e2`
- `vendor/jmaxml_20261110_code.xlsx`：
  `2ae15e0aa552b89469fcc286810b7d431a65681898d84d53f3eb46bbd7940f53`

ただし、コード生成・正規化の実装前に、分類仕様と完了条件の不整合が見つかったため停止した。

確認した事実：

- M3 は `classify_mete(code, name)` を §0.6 の表から作ると指定し、未知コードは
  `element=UNKNOWN, stage=None` とする。一方で完了条件は、サンプルと
  `tests/golden/_shared/` の Kind/Code（00・「なし」以外）をすべて UNKNOWN 以外に分類すること。
- 既存の `tests/data/samples/15_11_02_150916_VPWW54.xml` には
  `04: 洪水警報` と `18: 洪水注意報` が実在する。
  旧形式の他の VPWW50 / VPWW53 サンプルにも同じコードがある。
- これらのコードは §0.6 の表に存在しない。
  また、`WarningKind.group` として指定されている VPWW55〜61 / VXKO / VXSU のどれを
  旧形式の市町村向け洪水警報・注意報に割り当てるのかは定義されていない。
  `classify_flood` の VXKO / VXSU は指定河川洪水予報・水位周知河川の分類であり、
  それらと旧形式の市町村向け洪水警報を同じものとして扱う根拠は計画にない。

必要な仕様判断：

- M3の全件分類条件を、指定された分類表が扱う電文・Kindに限定するのか、
  または旧形式の洪水コードも正規化対象に含めて group 等の対応を追加定義するのか。
- 対象除外、コードの追加、独自の group の作成は、いずれも行っていない。

M3の実行結果：

- 調査のみ。コード生成・正規化は未実装で、全件分類テストも未作成・未実行。
  M3 の完了条件は未達。
- 気象庁へのアクセス、`tests/golden/` や録画フィード・公式サンプルの変更は行っていない。
- M2b、M4以降、git commit は行っていない。

依頼の停止条件に従い、この未確定点を記録して作業を停止する。

## M3 実装・検証結果（計画 8cd071f、2026-11-12）

計画の全件分類対象が WarningState の対応電文に限定されたため、上記の停止理由は解消した。
旧形式の04/18をUNKNOWNのまま維持し、M3を実装した。

コード表：

- manifest に記録されたローカルの ZIP と管理表の SHA-256 を再確認し、一致した。
  気象庁へのアクセスは行っていない。
- `scripts/codegen.py` にコード表生成を追加し、`--offline` と `--codes-only` を用意した。
  オフライン時に配布物がない場合は、ダウンロードを試みず FileNotFoundError で終了する。
  通常の全体生成にもコード表生成を組み込んだ。
- 生成物は `jmadantic/codes/` の型注釈付き dict 定数。
  アーカイブ名・SHA-256と、元xlsx名・SHA-256を生成ファイルに記録する。
  実行時に openpyxl を import しない。
- `AREA_CITY`：1,805件。元表の「気象警報・注意報で使用」フラグが1のコードを対象とし、
  市町村等の名称・府県予報区コード・一次細分区域コードを警報・注意報の関係表から結合した。
  他情報用のコードに所属先を推測して付与することはしていない。
  神戸市須磨区・北区のコードは元表で整数セルだったため文字列に変換した。
  先頭ゼロの補完や桁数の推測は行わない。
- `AREA_FLOOD_FORECAST`：338件。
- `AREA_WATER_LEVEL_WARNING`：0件。配布xlsxはヘッダー3行以外にデータがなく、
  空の辞書を生成した。サンプルや外部資料からコードを補完していない。

正規化：

- `jmadantic/normalize/warning.py` に Element、Stage、frozenなWarningKind、
  classify_mete / classify_flood、Predicate、3種の述語ヘルパー、rank を実装して公開した。
- 気象の要素・段階・groupは§0.6のコード表から分類する。
  大雨・土砂・高潮のlevelはNameの「レベルＮ」から取得し、他要素はNoneとする。
  正規表現はこの明示的なラベルとASCII・全角の数字だけを対象にし、名称からコードは推測しない。
- 氾濫は§0.7のコードから段階・levelを決める。旧名称も保持したまま分類する。
- 気象00・氾濫10の解除はstage / levelをNoneとする。
  気象00からは要素・groupを特定できないため、Element.UNKNOWN・空のgroupとして返す。
  解除コードに未知コードの警告は出さない。
- 未知の気象コードはElement.UNKNOWN・stage / level=None・空のgroupで、
  未知の氾濫コードは指定されたgroupを保持して同様に返し、warningを出す。
  Predicateの `&` / `|` は短絡評価し、欠けた段階・levelは閾値を満たすものとして扱わない。

完了条件・関連検証の実行結果（Python 3.13.7 / Windows）：

- `uv run --offline pytest tests/test_normalize.py tests/test_codes.py -q`：116件成功。
  `tests/data/samples/` と `tests/golden/` 全体から選んだ対応電文46ファイルを
  `strict=True` でパースし、公開data_type_codeで対象種別を確認した上で、
  計画指定のXPathにあるKind/Codeを分類した。対象コード31種類を確認。
  00・氾濫10の解除扱いを除き、すべてUNKNOWN以外となった。
  CodeのないKindは計画どおり対象外。旧形式04/18がUNKNOWNを維持するテストも成功。
- `uv run --offline pytest tests/test_codegen.py tests/test_code_tables_codegen.py -q`：18件成功。
  コード表の結合、使用フラグ、整数セル、先頭ゼロ、重複・不正形式の拒否、
  ヘッダーだけの表、オフライン時の取得禁止、コード表単独生成と再現性を確認した。
- `uv run --offline python scripts/codegen.py --offline` と
  `uv run --offline python scripts/codegen.py --offline --codes-only` を実行。
  再生成前後の全パッケージPythonソースがバイト単位で一致した。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：100%。
- `uv run --offline pytest -q`：801件成功、skip / xfailなし。
  全テストのDNS・ソケット接続禁止ガードを有効にしたまま実行した。
  公式サンプル546件のパーステストもstrict=Trueのまま成功。
- 着手前後のSHA-256比較で、`tests/golden/` 30ファイル、録画フィード6ファイル、
  公式サンプル素材547ファイルはすべて一致。
  これらのディレクトリと `jmadantic/_generated/` にgit diffがないことも確認した。

M4以降・M2bの実装、公開操作、git commitは行っていない。M3の作業をここで終了する。

## M4 実装・検証結果（計画 a569071、2026-11-12）

§3の状態管理と、§3.5に追加された分割区域の照会を実装した。

実装内容：

- `jmadantic/state/base.py` に共通Protocol、SkipReason、ApplyResult、ChangeType、
  frozenなChangeと、情報単位・電文キーの記録を追加した。
  スキップ理由は STATUS → UNSUPPORTED → DUPLICATE → STALE の順に判定する。
  情報単位の新旧判定にはControl/DateTimeを使い、等しい時刻の未記録キーもSTALEとする。
- `jmadantic/state/warning.py` にWarningState、frozenなCell・Riverを追加した。
  VPWWのセルはReportDateTime、VPWS50の各グループはKind/DateTimeの最大値で更新する。
  VPWS50に現れない既存グループは、全Kind/DateTimeの最大値W以下のセルだけを空にする。
  Itemにない市町村は変更せず、Wより新しいセルは保持する。
  解除後も空セルとas_ofを保持し、古い内容の復活を防ぐ。
- 氾濫は対象HeadlineのKindとBody内のCityCodeから状態を作り、取消・コード10で河川を削除する。
  種別集合の比較はname/codeで行い、Changeをscope・area・group順に返す。
  種別が同じで対象市町村だけが変わった場合は、照会結果を更新するがChangeは出さない。
- by_city、述語で種別を絞るcities、rivers、last_updatedを実装した。
  last_updatedは全体の最大時刻ではなく、最後に適用した電文のControl/DateTimeを表す。
  スキップでは更新しない。照会のMappingは読み取り専用のスナップショットとして返す。
- version=1のJSONにセル・河川・受理Status・last_updated・最新時刻・電文キーを保存する。
  電文キーは適用順に最大10,000件とし、古いものから捨てる。
  情報単位の最新時刻は別に保持するので、記録から外れた古い電文もSTALEとして除外できる。
  WarningKindはname/code/groupだけを保存し、読み込み時に再分類する。
  datetimeはタイムゾーン付きISO 8601で保存・復元する。
- Codeや必要な時刻の欠落など、更新根拠を作れない入力はValueErrorとし、状態・履歴を更新しない。
  市町村等Warningが存在するのにWを決めるKind/DateTimeが全くない場合も、時刻を推測しない。
  市町村等Warning自体がない場合は、計画指定のReportDateTimeによる全セル消去分岐を実装し、
  人工入力で検証した。この形の実電文を新たに確認したという意味ではない。

AREA_CITY_PARENT：

- ローカルのmanifest登録済みコード表ZIPをSHA-256確認後に使用した。
  `scripts/codegen.py` にAREA_CITY_PARENTの生成を追加し、166件を生成した。
- 使用フラグを問わずAreaInformationCityの全コードを読み、下2桁が00でないコードについて、
  同じシート内に親候補が存在する場合だけ対応を作る。存在しない親は補完しない。
- 氾濫の照会だけに親対応を適用する。親コードの照会に子の気象セルを混ぜる逆方向の集約は行わない。
  cities()も、河川が親コードを含む場合の分割区域を照会対象に含める。

完了条件・関連検証の実行結果（Python 3.13.7 / Windows）：

- `tests/test_golden.py` をREADMEのランナー要件どおり作成した。
  ケースごとに新規状態を作り、各stepをstrict=Trueでパースして適用する。
  expectに存在する項目だけを検査し、roundtrip_beforeではJSONの文字列一致も確認する。
  全12ケースが成功した。期待値の変更やケース名・ファイル名による実装側の分岐はない。
- `tests/test_warning_state.py` の27テストが成功。
  指定のVXSU素材を適用後、0442101・0442102の両方でレベル２氾濫注意報を取得できる。
  親へ気象セルを集約しないこと、照会フィルター、スキップ優先順位、同時刻、
  独立情報単位、VPWS50のグループ時刻・全体W、空セルの永続化、履歴の上限、
  受理Status設定の復元、無効入力で状態を壊さないことも確認した。
- コード表生成テストに、親が同シートに存在することと使用フラグ非依存の検証を追加した。
  公開辞書166件と大和町・薩摩川内市の対応も検証した。
- `uv run --offline pytest -q`：842件成功、skip / xfailなし。
  公式サンプル546件のstrict=Trueパースと、従来のM2・M3検証も成功した。
  DNS・ソケット接続を禁止する共通ガードは有効のまま。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：100%。
- `uv run --offline python scripts/codegen.py --offline --codes-only` を再実行し、
  全パッケージPythonソースが生成前後でバイト単位で一致することを確認した。
- 着手前後のSHA-256比較で、`tests/golden/` 30ファイル、録画フィード6ファイル、
  公式サンプル素材547ファイルがすべて一致。
  `git diff --exit-code -- tests/golden tests/data/feed tests/data/samples jmadantic/_generated`
  も差分なし。

気象庁へのアクセス、M2b・M5の実装、公開操作、git commitは行っていない。
M4の作業をここで終了する。

## VPWS50 性能改善（2026-11-12）

M5に着手する前に、性能改善と以下の検証を完了した。

- 市町村 → グループ → Cell のメモリー内索引を追加した。
  `_snapshot_item` は当該市町村のセルだけを参照し、全セルを走査しない。
  by_city / cities の気象部分も同じ索引を使用する。
- セルを置き換える経路を一箇所にまとめ、VPWW・VPWS50・JSON復元のすべてで索引を更新する。
  索引は永続化せず、`to_json` のversion 1の形式・フィールドは変更していない。
- `benchmarks/benchmark_vpws50.py` を追加。
  全1,805市町村×7要素＝12,635セルを埋め、録画済みのVPWS50（1,805 Item）を適用する。
  XMLパース・満杯状態の復元・結果のJSON化は計測区間に含めない。
  毎回新しく復元した状態に適用し、DUPLICATEの短絡時間を測ることがないようにした。

同じ入力・環境で各7回を測定した結果：

| Python / OS | 適用時間の中央値 | 最小～最大 |
|---|---:|---:|
| 改善前：Python 3.13.7 / Windows 11 | 0.883198秒 | 0.844488～0.898943秒 |
| 改善後：同上 | 0.079703秒 | 0.047332～0.109617秒 |

この測定での短縮率は約91.0%、速度比は約11.1倍。
各試行のChange件数は改善前後とも12,582件で、適用後のversion 1 JSONのSHA-256は
いずれも `ced6ca6238598eeea526f014fd48fce80e34ecf698bb7bf59938fa38f97cd5d0` だった。
測定値はこの環境での実測であり、CIの時間制限テストには使用しない。

再実行コマンド：

```sh
uv run --offline python benchmarks/benchmark_vpws50.py --repeat 7
```

完了条件の実行結果：

- 全セルのitems走査を禁止した辞書を使う回帰テストを追加し、JSON復元後のVPWS50・
  VPWW更新・市町村照会が索引だけで動くことを確認した。version 1のフィールド集合も不変。
- `uv run --offline pytest -q`：843件成功、skip / xfailなし。ゴールデン12ケースもすべて成功。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：100%。
- git commit・公開操作は行っていない。続いてM5の一次資料確認と文書整備に進む。

## M5 ドキュメントと0.1.0の配布検証（2026-11-12）

依頼された範囲（README・CHANGELOG・バージョン0.1.0・人間向け公開手順）を完了した。

- READMEを日本語で整備し、インストール、poll → fetch → parse → apply → ack、市町村照会、
  JSON version 1の保存・復元、出典、加工主体、免責、開発コマンドを記載した。
  `apply()` のValueErrorは電文IDと例外をログに残してackする。未ackなら同じ電文が返り続けることを説明した。
  取得失敗は未ackのまま再取得し、解析不能な電文もログ付きでackする例とした。
- 同じ処理の実行用サンプル `examples/poll_warnings.py` を追加。
  `--offline-sample` はローカルの録画XMLと合成Atom応答だけで動作し、過去サンプルである旨も表示する。
- `CHANGELOG.md` と、人間がTestPyPI → PyPIの順にTrusted Publishingを行う `RELEASING.md` を追加した。
  公開用ワークフローの作成・登録・実行は行っていない。
- `pyproject.toml` にREADMEを配布メタデータとして指定した。
  既存の `pyproject.toml` と `jmadantic/_version.py` はともに0.1.0で、一致を確認した。

出典表示の一次資料確認：

- [気象庁「ご利用にあたって」](https://www.jma.go.jp/jma/kishou/info/coment.html) と、
  同ページが指定する[公共データ利用規約（第1.0版）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)
  をブラウジングで確認できた。文言を推測していない。
- 出典の記載例「出典：気象庁ホームページ（当該ページのURL）」に沿った表示を記載した。
  加工した場合は加工した旨と加工主体を別途表示し、気象庁が加工物を作成したかのように示さない条件も反映した。
  免責は気象庁の利用上の責任に関する記載と、本ソフトウェアの保証に関する説明を区別した。
  防災判断は公式発表で確認する旨を記載した。
- この確認は文書作成のための一次資料参照である。テスト・ベンチマーク・配布検証から気象庁への通信は行っていない。

完了条件の実行結果（Windows / Python 3.13.7）：

- `uv build --offline --no-sources`：sdistとwheelの作成に成功。
  wheel内の生成クラス・コード表・状態管理・`py.typed`・READMEメタデータ、
  sdist内のREADME・CHANGELOG・公開手順・実行例を確認した。vendor・tmp・開発用venvの混入はない。
- `python -m venv tmp/m5-clean-3l00wra5` で新規venvを作成し、
  そのPythonで `pip install --no-index --find-links tmp/m5-dependency-wheels dist/jmadantic-0.1.0-py3-none-any.whl`
  を実行、成功した。依存のxsdata 26.10・lxml 6.1.3・typing-extensions 4.16.0は、
  ローカルuvキャッシュの展開済みファイルを検証用wheelに再梱包して使った。
  uvのオフライン索引解決では取得できなかったための措置で、ネットワークからの依存取得は行っていない。
  `jmadantic` 本体は上記ビルドで生成したwheelをインストールした。
- 新規venvのPythonを `-I` で実行し、READMEのPythonブロック3つをそのまま実行した。
  HTTPだけを録画XMLの偽応答に置き換え、DNS・ソケット接続を禁止した状態で成功。
  解析・適用・JSON復元後に0121400の警報集合を検証した。
  import元が新規venvのsite-packagesであり、openpyxlが入っていないことも確認した。
- 同じvenvでREADME記載の `examples/poll_warnings.py --offline-sample ... --city 0121400` を実行し、
  レベル４大雨危険警報、過去サンプルの注意書き、出典と加工主体が表示された。`pip check` も成功。
- `tests/test_readme_example.py` の7テスト成功。
  READMEそのものの実行、実行例との処理関数の一致、成功時・applyのValueError時・解析エラー時のack、
  取得失敗時の次回再返却、オフライン実行を確認した。
- `uv run --offline pytest -q`：850件成功（39.13秒）。skip / xfailなし。
  ゴールデン12ケースと、公式サンプル546件のstrict=Trueでの解析を含む。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功（46ファイル整形済み）。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes jmadantic --ignoreexternal`：100%。
- 着手前とのSHA-256比較で `tests/golden/` 30ファイル、フィード素材6ファイル、
  公式サンプル素材547ファイルはすべて一致。これらのgit diffもない。
- ローカルで実行したPythonは3.13.7のみ。Python 3.11・3.12とリモートCIの実行結果は今回確認していない。

M2b、git commit、TestPyPI・PyPIへの公開操作は行っていない。依頼された作業はここで終了する。

## 正規化 API の追加と非同期クライアント（2026-11-12）

M5の後に、次の4つを追加した。いずれも計画（M0〜M5）の範囲外で、利用者の依頼で実装した。

| コミット | 内容 |
|---|---|
| `7fec6db` | 警報級の可能性（VPFD60・VPFD61・VPFW60）の `warning_possibility()`。README の strict の既定値の誤記も修正 |
| `112de8c` | 天気予報（VPFD51・VPFW50・VPFD50）の `weather_forecast()` |
| `cc8d070` | 地震情報（VXSE51・VXSE52・VXSE53）の `earthquake_info()` |
| `999ea84` | 非同期クライアント `AsyncFeedClient` と、通信エラーの `FeedTransportError` への統一 |

### 正規化 API の共通方針

- 電文1通を受け取り、区域（または地点・市町村・観測点）× 要素 × 時間帯の平らなセルの列に展開する。
  状態は持たず、`Control/Status` も確認しない。訓練・試験の電文の除外は呼び出し側の責任とする。
- 未知の値・要素は捨てずに `None` / `UNKNOWN` とし、警告ログを出す。元の文字列はセルに残す。
- 対象外の電文と、`refID` が未定義などの構造の矛盾は `ValueError` にする。
- `TimeDefines` の変換（タイムゾーン必須、年・月を含む期間は拒否）は `normalize/_time.py` に共通化した。

### 実電文で確認したこと

テスト用の実電文は、2026-11-12 にフィードから1回だけ取得した。テストと CI から気象庁へはアクセスしない。
出典は各ディレクトリの README に記載した。

- `tests/data/possibility/`（3通、東京都）：2026年の電文は、1つの府県に複数の一次細分区域が並ぶ。
  公式サンプルは香川県の1区域だけで、この形を確かめられなかった。VPFW60 の `TimeDefine` には `Name` がない。
- `tests/data/forecast/`（4通、東京・鹿児島・釧路）：天気・降水確率は区域、気温は地点（アメダス番号）ごとで、
  電文に区域と地点の対応はない。VPFW50 の区域は、鹿児島県（奄美地方除く）460100、
  釧路・根室・十勝地方014000 のように一次細分区域より粗いことがある。
  `by_city()` は一次細分区域、府県予報区、上位区域（上3桁＋000）の順に探す。
- `tests/data/earthquake/`（5通）：2026-11-08 01:04 静岡県西部（最大震度5強）の震度速報・震源・震源震度の第1〜2報と、
  深さ「ごく浅い」の地震。「震度５弱以上未入電」は、観測点では `Int` の値そのものになる。
  市町村では、`MaxInt` と並ぶ `Condition` の場合もある。後者を見落とさないよう `unreceived` に残す。
- `Intensity` は順位の値（震度5強は6）を持つため、`str()` とf文字列は「震度5強」を返すようにした。
- 緊急地震速報：eqvol 長期フィード（2026-11-05〜11-12 分）に VXSE43〜45 は1件もなかった。
  PULL型フィードには配信されないと判断し、対象外とした。

### 非同期クライアントと通信エラー

- `AsyncFeedClient` は `FeedPoller` に非同期の通信部品をつなぐ薄い層で、同時リクエストは既定で4件まで。
  通信部品は `AsyncHttpClient`（`async def send()`）で差し替えられる。
  httpx は従来どおりオプションで、既定の `HttpxAsyncHttpClient` を作るときだけ必要。
- 同梱のアダプター（urllib・httpx 同期・httpx 非同期）は、接続・タイムアウト・読み込み途中の切断を
  `FeedTransportError`（`FeedError` の一種、元の例外は `__cause__`）に変換する。
  以前の README の例は `(OSError, FeedError)` しか捕まえていなかった。
  このため、httpx の通信エラーと urllib の `http.client.IncompleteRead` が漏れていた。
- テストのネットワーク遮断で、Windows の asyncio がイベントループ用に作る `socketpair()`（ループバック接続）だけを許可した。
  外部への接続と名前解決が禁止されたままであることを確かめるテストも追加した。

### 完了条件の実行結果（Windows / Python 3.13.7、httpx 0.28.1）

各コミットの時点で実行した。

| コミット | pytest |
|---|---|
| `7fec6db` | 866件成功 |
| `112de8c` | 893件成功（地震の変更を除いた状態で実行） |
| `cc8d070` | 954件成功 |
| `999ea84` | 976件成功 |

- skip / xfail はない。ゴールデン12ケースと、公式サンプル546件の strict=True での解析を含む。
- `uv run ruff check` / `uv run ruff format --check`：成功。
- `uv run pyright`：エラー0件・警告0件。
- `uv run pyright --verifytypes pyjmaxml --ignoreexternal`：100%。
- README の正規化 API の例（警報級の可能性・天気予報・地震情報）は、手元で実行して出力を確認した。
  自動テストで実行される README のブロックは、最初の例と非同期の例だけである。
- `examples/poll_warnings.py --offline-sample ...` の実行に成功した。
- ローカルで実行したのは Python 3.13.7 のみ。Python 3.11・3.12 とリモート CI の結果は確認していない。

### その他

- CI に `ruff format --check` を追加した。README の開発コマンドには記載があったが、CI では実行していなかった。
- push・公開操作は行っていない。

## フィードの返却順：古い順に並べ替え（2026-11-12）

気象庁の Atom フィードは新しい順に並ぶ。これまで `poll()` はその順のまま未処理を返していた。
そのため例のとおり順に `apply()` すると、1回のポーリングに同じ情報の電文が複数あった場合、
古い方が `stale` になり、途中の発表・切り替えの `Change` が出なかった。最終状態は正しかった。

- `FeedPoller.handle_response` は、応答内の新規エントリーを `updated` の古い順に未処理へ積む。
  時刻が同じものはフィード上で後ろ（古い側）を先にする。
- 返却は全未処理を `updated` の古い順に並べる（安定ソート）。後の応答でより古いエントリーが現れても古い順になる。
- 上限1,000件の超過時は、発見順ではなく `updated` が最も古いものを破棄する。
  従来は1回の応答内で最も新しいものを破棄していた。
- テスト用の `feed()` に `updated` 引数を追加した。既存テストの期待値は、気象庁と同じ新しい順のフィードを前提に直した。
- README・CHANGELOG に返却順と、逆順適用で `Change` が欠ける旨を記載した。

検証：`uv run pytest` 978件成功、`uv run ruff check` / `ruff format --check` 成功、
`uv run pyright` エラー0件、`--verifytypes` 100%。

## 受信順序と電文の時刻範囲（2026-11-12）

`ordering-plan.md` に従って実装した。

- VPWS50の「発表なし」を、市町村別の `cleared` と全国の `cleared_all` に時刻つきで保持する。
  セルがない組み合わせでも過去のVPWWによる警報の復活を防ぐ。既存セルがある場合はその時刻を優先し、
  同時刻・新しい内容は従来どおり適用する。更新は準備後にまとめて反映する。
- JSONはversion 1のまま2項目を追加した。項目がない既存JSONの読み込み、型とタイムゾーンの検査、
  JSON往復による時刻の保持を検証した。
- `WarningState.apply()` と `State.apply()` に `now` / `max_age` / `max_future` を追加した。
  `now` を渡すとControl/DateTimeを既定で過去24時間・未来10分の範囲に制限する。
  境界は受理し、範囲外は `too_old` / `future` として処理履歴へ記録せずスキップする。
  `now` 省略時の動作、基準の変更・無効化、引数検証、既存スキップ理由の優先順位も検証した。
- 実行例はオンライン時だけ現在時刻を渡し、オフラインサンプルでは時刻判定をしない。
  READMEの最初の例と非同期の例は着手時の内容を維持した。
  実行例とのAST比較テストは、追加した `now` の受け渡しを除いた処理本体を比較する形に更新し、
  オンライン・オフラインでの引数と、時刻でスキップした電文のackを別途検証した。
- g06dを追加した。既存12ケースのcase.json・XMLにはgit差分がない。
  フィード側の既存未コミット変更は保持し、今回その実装・素材には変更を加えていない。

### 順序入れ替えと性能

- 新規の `tests/test_state_order.py` は、共有8電文を一度だけ解析し、固定シードの30通りと
  「VPWS50 → 稚内VPWW55 2通」の再現順序を確認する。
  修正前は稚内に古い警報が残るアサーションで失敗（1件失敗、1.25秒）、
  修正後は市町村の警報名集合・河川状態が時系列順の結果と一致（1件成功、1.54秒）した。
- `uv run --offline python benchmarks/benchmark_vpws50.py --repeat 7` を修正前後で実行した。
  Windows 11 / Python 3.13.7、1,805市町村・12,635セル・VPWS50の1,805 Item。
  中央値は **0.077410秒 → 0.088104秒（約1.14倍、約13.8%増）** で、2倍未満。
  Change件数は両方とも12,582件。保存JSONには時刻記録が加わるためチェックサムは変わる。

### 完了条件の検証

- `uv run --offline pytest`：**1,022件成功（46.49秒）**。skip / xfailなし。goldenは13ケース。
- `uv run --offline ruff check` / `uv run --offline ruff format --check`：成功（61ファイル）。
- `uv run --offline pyright`：エラー0件・警告0件。
- `uv run --offline pyright --verifytypes pyjmaxml --ignoreexternal`：**100%**。
- `uv run --offline python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400`：
  レベル４大雨危険警報、録画サンプルの注意、出典と加工主体を表示して成功。
- `git diff --check` 成功。変更した `pyjmaxml/state/*.py` はLF改行。

実行環境の制約により、`UV_CACHE_DIR` は作業ディレクトリの `tmp/uv-cache` に設定した。
最初の全体テストは既定の一時ディレクトリへのアクセス拒否で1,013件成功・9件setup errorになったため、
`PYTEST_DEBUG_TEMPROOT` を作業ディレクトリの `tmp` に設定して全体を再実行した。
pyrightもNode.jsのパス解決がサンドボックス内で拒否されたため、同じコマンドをサンドボックス外で実行した。
仕様上の計画変更はない。

今回変更・追加したファイル：

- `pyjmaxml/state/base.py`
- `pyjmaxml/state/warning.py`
- `examples/poll_warnings.py`
- `tests/test_warning_state.py`
- `tests/test_state_order.py`（新規）
- `tests/test_golden.py`
- `tests/test_readme_example.py`
- `tests/golden/g06d_vpws50_then_old_vpww/case.json`（新規）
- `tests/golden/README.md`
- `README.md`
- `CHANGELOG.md`
- `IMPLEMENTATION_STATUS.md`

実電文のオンライン取得、全順列の網羅、Python 3.11・3.12、リモートCIは今回検証していない。
git commit・push・公開操作は行っていない。

## 気象警報・注意報の予想時系列（2026-11-12）

`vpwp50-plan.md` に従い、VPWP50 の正規化 API を追加した。

- `WarningTimeSeriesCell`・`WarningTimeSeries`・`warning_timeseries()` を
  `normalize.timeseries`、`normalize`、パッケージ直下から公開した。
- TimeSeriesInfo ごとの TimeDefine を refID で参照し、市町村・Local・値の種類・期間ごとに展開する。
  危険度はコードと名称を保持し、Stage・レベルへの変換は行わない。
  風雪は STORM のまま condition を残し、高潮の「うちあげ高水位」と「潮位」もそれぞれ保持する。
- 数値の空要素は `None`、Part 全体の Base/Addition/Note は Local 内のセルにも同じ tuple として保持する。
  `by_city()` は市町村等コードの完全一致で、親区域への検索は行わない。
- 未知の Property/Type は UNKNOWN と元の名称を保持して警告し、対応 Part がない場合も警告する。
  対象外の電文・不正な Body・未定義の refID・Area/Code の欠落は ValueError にする。
  Control/Status、Kind/Status、Kind/DateTime は判定に使わない。
- 指定された実電文3通を `tmp/vpwp50/x/` からコピーし、SHA-256 が原本と一致することを確認した。
  公式サンプル4通と合わせ、ElementTree で値の個数・出現順・TimeDefine の参照先を独立に確認した。
  Local ごとの風危険度、高潮の2種類の値、欠測値、注記、例外と警告、README の新しい例もテストした。
- WarningState、既存のテスト、golden、forecast.py、possibility.py に変更はない。
- 計画の構造説明と異なり、生成型 TypeLocalSignificancy にも addition フィールドがある。
  今回の notes は公開仕様で指定された Base/Addition/Note を対象とする。

### 完了条件の検証

- `uv run pytest -q`：**1,044件成功（55.62秒）**。追加した22件を含む。skip / xfailなし。
- `uv run ruff check` / `uv run ruff format --check`：成功（66ファイル）。
- `uv run pyright`：エラー0件・警告0件。
- `uv run pyright --verifytypes pyjmaxml --ignoreexternal`：**100%**。
- `git diff --check` 成功。新規の Python 2ファイルは LF 改行。

`UV_CACHE_DIR` を `tmp/uv-cache`、`PYTEST_DEBUG_TEMPROOT` を `tmp` に設定した。
pyright はサンドボックス内の Node.js がユーザーディレクトリの参照で EPERM となったため、
同じコマンドをサンドボックス外で実行した。
ruff が未追跡の計画書内の Python ブロックにも整形を要求したため、ユーザーの承認を受け、
`vpwp50-plan.md` と `tracker-plan.md` のコードブロックも整形した。

今回変更・追加したファイル：

- `pyjmaxml/normalize/timeseries.py`（新規）
- `pyjmaxml/normalize/__init__.py`
- `pyjmaxml/__init__.py`
- `tests/test_timeseries.py`（新規）
- `tests/data/timeseries/`（指定XML 3通とREADME、新規）
- `README.md`
- `CHANGELOG.md`
- `IMPLEMENTATION_STATUS.md`
- `vpwp50-plan.md`・`tracker-plan.md`（コードブロックの整形のみ）

実電文のオンライン再取得、未同梱の実電文55通での正規化、Python 3.11・3.12、リモートCIは今回検証していない。
tracker の実装、git commit・push・公開操作は行っていない。

## Tracker（2026-11-12、実装完了・性能条件の例外承認あり）

`tracker-plan.md` の Tracker・AsyncTracker と名前の型を追加した。
ユーザーから、生成・README 関連の既存テストの更新と、§2.4 の性能停止条件を一時解除して
原因調査・修正を続ける承認を得た。全体 pyright の時間は依然2倍を超えており、
この性能条件は承認された例外として残る。型エラーを無視して完了扱いにはしていない。

### 実装と互換性

- 公式の固定コード表から AreaName（1,805区域）と Prefecture（47都道府県）を生成し、
  codes とパッケージ直下から公開した。分割区域は独立した名前・コードのまま保持する。
  逆引き・府県別一覧は生成したコード順の辞書から構築し、名前の重複定義を減らした。
  Archive・Workbook と各 SHA-256 のヘッダーを付け、生成前に名前・件数・府県対応を検証する。
- 通信しない共通コアと同期・非同期ラッパーを分けた。指定区域・府県の重複を除き、
  不変な AreaView・PrefectureView を返す。名前は実行時にも確認する。
- 最初だけ EXTRA・REGULAR の長期フィード、その後に通常の3フィードを読む。
  （レビュー後の修正）長期フィードの poll が失敗した場合は、成功するまで予定に残し、
  最小間隔（3600秒）の経過後に読み直す。経過前の TooFrequentError は errors に含めない。
  修正前は、オフラインで起動すると長期フィードを二度と読まなかった。
  電文の選択は既存のタイトル対応表を共有し、計画の対象だけを取得する。
  府県の照合は URL の6桁コードの頭2桁。VPWS50・河川・地震は府県で絞らない。
- 警報は既存 WarningState に同じ clock の now を渡し、差分は指定区域の city に絞る。
  正規化結果は種類・URL の6桁コード別、地震は全体で、Control/DateTime の最新を保持する。
- poll/fetch の FeedError を UpdateResult.errors に返し、他のフィードの処理を続ける。
  取得失敗は未ack、解析・適用エラーはログとack。その他の例外は呼び出し側に伝える。
  長期フィードで失敗した取得も次回に再試行し、通常フィードで取得済みなら重複取得しない。
  長期・通常フィード間で種類別に最大10,000件の処理済みIDを共有する。
  待機・自動再試行はせず、次の update 呼び出しは利用者が行う。
- AsyncTracker は単一の既定 HTTP アダプターを所有し、aclose / async with で閉じる。
  注入されたアダプターは閉じない。同期版と同じ順序で処理する。
- updated_at は update が正常に戻った時刻（UTC）。FeedError を含むかは errors で確認する。
- README の最初に Tracker と府県指定の例を置き、従来の本文は低レベル API の下に保持した。
  `examples/track_areas.py --offline-sample` と CHANGELOG を追加した。
- FeedClient・WarningState・既存正規化関数のコードと golden は変更していない。
  kinds.py の既存公開関数は同じ対応表を使い、公開シグネチャ・結果は維持した。
  既存テストの変更は生成関連2ファイルと README 例の1ファイルで、承認された範囲内。

### オフライン検証

- 録画済みフィードと保存電文16組（REGULAR 7組、EXTRA 9組）のタイトルが一致した。
  継続検証用には REGULAR 7組と EXTRA 1組をテストし、EXTRA の原電文を改変せず同梱した。
  コピー元との SHA-256 一致も確認した。オンライン取得は行っていない。
- 低レベル API と各 View の一致、府県フィルタ、全国集約、対象外のack、長期の初回取得、
  取得・poll失敗、再取得、古い電文の排除、区域名検証、府県の重複排除、写しの不変性、
  同期・非同期の結果と通信順序の一致、HTTP 所有権、README・実行例を確認した。
  forecast / possibility の保存7電文では、区域コードと URL の頭2桁の一致も検証した。
- `uv run pytest -q`：**1,085件成功（66.33秒）**。skip / xfail なし。
  既存のネットワーク禁止 fixture を維持し、気象庁へのアクセスは行っていない。
- `uv run ruff check`：成功。`uv run ruff format --check`：成功（78ファイル）。
- `uv run pyright`：61ファイル、エラー0件・警告0件。
- `uv run pyright --verifytypes pyjmaxml --ignoreexternal`：**100%**。
  公開シンボル532件が既知の型、曖昧・不明な型は0件。
- `uv run python scripts/codegen.py --offline --codes-only`：成功。
  生成直後にも ruff の検査・整形チェックが成功することを確認した。
- `git diff --check`：成功。今回追加した Python 11ファイルはすべて LF。

### pyright の測定と遅延への対応

Python 3.13.7、pyright 1.1.414 の既存環境で測定した。
Node のサンドボックス内パス検査を避け、pyright は通常環境で実行した。
以下は uv・プロセス起動を含む実時間。最終値は3対象を順番に実行して取得した。

| 対象 | 変更前 | 最終実装 |
|---|---|---|
| `uv run pyright` 全体 | 5.2347338秒、成功 | 14.1343607秒、エラー0件 |
| 正しい区域名の確認ファイル | 0.867秒、1エラー（Tracker 未実装） | 1.081秒、エラー0件 |
| 誤った区域名の確認ファイル | 0.849秒、1エラー（Tracker 未実装） | 1.103秒、引数の型エラー1件 |

変更前の未実装エラーはユーザー了承のうえで記録した。
初期実装の全体解析は90秒を超えて未完了となり、計画どおり一度停止した。
再開承認後、一時コピーでメソッド群・式を除く比較を行い、Tracker.area の入力検証が
大きな遅延に関係することを確認した。その検証を、名前の辞書キーによる条件分岐から
dict.get でコードを取り出す判定へ置き換えた。公開型と実行時の受理条件は維持した。
型推論で str に広がっていた areas 属性には tuple[AreaName, ...] を明示した。
全体解析は約18秒で完了するようになり、生成辞書の重複を減らした後は約14秒となった。
内部の型検査処理をプロファイルしたわけではなく、Literal 一般の性能を保証するものではない。

変更前の2倍は約10.47秒。最終値は約2.70倍で、この基準は満たしていない。
停止条件の解除はユーザー承認済みだが、性能差は制限として明記する。

（レビュー後の修正）ファイルごとに測ると、`pyjmaxml/tracker/_core.py` だけで約10.5秒かかり、
そのうち約6秒が `TrackerCore.__init__` の `if name not in AREA_CODE_BY_NAME:` 1行だった
（AreaName の各リテラルについて `in` による型の絞り込みが行われるため）。
`AREA_CODE_BY_NAME.get(name) is None` に変えた後の `uv run pyright` 全体は
3回で 9.19秒・8.79秒・8.41秒（約1.6〜1.8倍）となり、計画 §2.4 の2倍以内に収まった。
pytest は 1,087件成功（長期フィード再試行のテスト2件を追加）。

確認ソースは `tests/typecheck/tracker_valid.py` と `tracker_invalid.py.txt`。
`tests/test_tracker_types.py` が一時ファイルと専用設定を作り、CI の既存 pytest から
両方を pyright にかけ、解析ファイル数・診断数・誤入力の行と診断種類を検査する。
`# pyright: ignore` は使用していない。測定JSONは `tmp/tracker-typecheck/` の作業データに保存した。
ファイル数0となった除外設定の試行や、無効な include 設定の試行は測定値から除外した。

全体 pytest の最初の実行では、既存の一時ディレクトリのアクセス拒否で
1,068件成功・17件 setup エラーとなった。既存領域を削除せず、ワークスペースの tmp 内で
未作成と確認した固有の --basetemp と cache_dir を指定して再実行し、全件成功した。
UV_CACHE_DIR は tmp/uv-cache。テストコードの変更でアクセス制約を回避したわけではない。

Python 3.11・3.12、オンライン運用、リモートCIは今回実行していない。
git commit・push・公開操作は行っていない。
