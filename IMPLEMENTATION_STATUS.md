# 実装状況（2026-11-12）

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
