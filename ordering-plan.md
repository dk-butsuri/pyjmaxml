# 計画：電文の受信順序が前後したとき・過去の電文が届いたときの扱い

作成 2026-11-12。実装担当向けの指示書。**このファイルに書いていないことを決める必要が出たら、実装を止めて報告すること。**

## 0. 前提と作業ルール

- 作業ツリーには**コミット前の変更がある**（`poll()` が `updated` の古い順で返すようにした修正。
  `pyjmaxml/feed/_core.py`、`tests/feed_helpers.py`、`tests/test_feed_*.py`、`tests/test_readme_example.py`、README・CHANGELOG・IMPLEMENTATION_STATUS）。
  これは正しい変更なので、**戻さない・上書きしない**。この計画の変更はその上に積む。
- `git commit`・push はしない。
- `tests/golden/` の既存の `case.json` と XML は仕様そのもの。**書き換えない**（`tests/golden/README.md` 参照）。新しいケースを足すのはよい。
- コマンドはすべて `uv run` で実行する（`.venv/Scripts/python` を直接使うと pyright が誤って92件のエラーを出す）。
- `pyjmaxml/**/*.py` は LF 改行（`.gitattributes`）。
- 完了条件は §5。

## 1. 背景：何が問題か

### 1.1 気象庁の指示（運用指針 `jmaxml_guide_20130412.pdf` §2.1.3）

- §2.1.3.1〜2：独立した情報単位（Title・EditorialOffice・Status・EventID）の中では、`Control/DateTime` が最も新しい電文だけが有効。Serial の順ではない。
  → **実装済み**（`pyjmaxml/state/base.py` の `Ledger`、`SkipReason.STALE`。golden g04）。
- §2.1.3.6：「時刻管理が適正なシステムにおいては、**基準以上の過去、及び未来時刻により入電した電文を破棄するような機能を付けることを推奨する**。この場合の基準値は**可変**とすることが望ましい。」
  → **未実装**。§3 で実装する。
- VPWS50（集約通報）と VPWW55〜61 は Title が違うので別の情報単位。両者を1つの状態にまとめるときの新旧の扱いは、気象庁は決めていない（ライブラリの設計の範囲）。

### 1.2 見つかった不具合：VPWS50 の「発表なし」が、セルのない市町村では記録されない

再現（`tests/golden/_shared/` の電文だけで再現できる）：

```
WarningState に apply する順番                          → by_city("0121400")（稚内市）
vpww55_wakkanai_20200622T2300 → vpws50_20261112T0000   → []                         正しい
vpws50_20261112T0000 → vpww55_wakkanai_20200622T2300   → [レベル４大雨危険警報]       誤り（2020年の警報が生き返る）
```

- VPWS50 の市町村等 Item には稚内市が「発表警報・注意報はなし」で載っている。
- `WarningState._snapshot_item`（`pyjmaxml/state/warning.py`）は、`self._cells_by_city.get(city, {})` にある**既存セルだけ**を空にする。稚内市のセルがまだなければ、「2026-11-11 時点で発表なし」という情報は捨てられる。
- そのあと届いた 2020 年の VPWW55 は、比べるセルがない（`previous is None`）ので適用される。`Ledger` も、VPWW55（稚内）の情報単位は初めてなので STALE にしない。
- `_shared` の8通をランダムに1000通り並べ替えて試したところ、時系列順と最終状態が違ったのは335通り。原因は**すべてこれ**（稚内の VPWW55 が2通とも VPWS50 より後に届いたケース）。河川（VXKO・VXSU）の差分は0件。golden 12ケースは全順列で一致した。
- 電文に `Warning[@type="気象警報・注意報（市町村等）"]` が1つもない VPWS50（全国で発表なし）の分岐も、同じく既存セルしか空にしない。

## 2. 修正A：VPWS50 の「発表なし」を時刻つきで記録する

### 2.1 状態の追加

`WarningState` に次を足す。

- `self._cleared: dict[str, datetime]`：市町村等コード → 時刻 C。
  意味：「時刻 C の時点で、この市町村のうちセルのない (市町村, 電文種別) は発表なし」。
- `self._cleared_all: datetime | None`：電文に市町村等の Warning が1つもない VPWS50 を適用したときの時刻。全市町村に対する C として扱う。

市町村×7グループぶんの空セルを作る方式は**採らない**（VPWS50 の Item は約3,000件あり、保存 JSON とメモリが何倍にも膨らむため）。

### 2.2 「直前のセル」の求め方

ヘルパーを1つ作り、セルを比べる箇所はすべてこれを使う。

```python
def _previous(self, key: tuple[str, str]) -> Cell | None:
    cell = self._cells.get(key)
    if cell is not None:
        return cell
    times = [t for t in (self._cleared.get(key[0]), self._cleared_all) if t is not None]
    return Cell(frozenset(), max(times)) if times else None
```

- 使う箇所：`_weather_updates` の VPWW 分岐の `previous = self._cells.get(key)`、`_snapshot_item` の `previous = self._cells.get(key)`。
- 比較の向き（`at >= previous.as_of` なら適用）は**変えない**。既存セルとの比較と同じ規則にそろえる。
- `apply()` の中で `Change` を作るときの `before` は、今までどおり `self._cells.get(...)`（仮のセルは kinds が空なので結果は同じ）でよい。

### 2.3 記録するタイミング

すべて `apply()` の「更新を準備してから最後にまとめて反映する」流れに合わせる。準備の途中で `ValueError` になったら、状態を一切変えないこと（既存テスト `test_unresolvable_snapshot_does_not_mutate_state_or_consume_telegram_key` と同じ性質）。

- `_snapshot_item`：その Item の市町村 city について、`cleared[city] = max(既存の値, watermark)` を**更新予定**に入れる。発表中の Kind がある市町村でも記録してよい（セルがあるグループはセルが優先されるため）。
- 市町村等の Warning がない VPWS50 の分岐：`cleared_all = max(既存の値, ReportDateTime)` を更新予定に入れる（既存の「`as_of <= at` のセルを空にする」処理はそのまま）。
- VPWW55〜61・VXKO・VXSU では記録しない。
- `by_city()`・`cities()`・`rivers()` の結果には影響させない。

### 2.4 JSON（version 1 のまま、項目を追加）

- `to_json()` に次を**常に**出力する。
  - `"cleared": [{"city": "0121400", "at": "<ISO 8601>"}, ...]`（city の昇順）
  - `"cleared_all": "<ISO 8601>" | null`
- `from_json()`：どちらの項目も**なくてもよい**（なければ空・null）。あれば型を検査し、不正なら既存と同じく `ValueError`。時刻はタイムゾーン必須（既存の `_time()` を使う）。
- `"version"` は 1 のまま。古い保存データはそのまま読める。
- docstring と README の「JSON形式はversion 1です」の段落に、`cleared` / `cleared_all` を追記する。

### 2.5 性能

- `uv run --offline python benchmarks/benchmark_vpws50.py --repeat 7` を修正前後で実行し、中央値を IMPLEMENTATION_STATUS に記録する。修正前の記録は 0.0797 秒（同一環境ではない可能性があるので、必ず両方を測る）。2倍を超えて遅くなるなら報告する。

## 3. 修正B：基準より古い・未来の電文を捨てる（運用指針 §2.1.3.6）

### 3.1 API

```python
def apply(
    self,
    report: Report,
    *,
    now: datetime | None = None,
    max_age: timedelta | None = timedelta(hours=24),
    max_future: timedelta | None = timedelta(minutes=10),
) -> ApplyResult: ...
```

- `now` を渡さなければ、今までどおり時刻による判定をしない（後方互換。`WarningState` は時計を持たない設計を守る）。
- `now` を渡した場合：
  - `report.control.date_time < now - max_age` なら `SkipReason.TOO_OLD`（値 `"too_old"`）でスキップ
  - `report.control.date_time > now + max_future` なら `SkipReason.FUTURE`（値 `"future"`）でスキップ
  - `max_age` / `max_future` が `None` ならその側は判定しない
- 判定に使う時刻は `Control/DateTime`（運用指針の「入電した電文の時刻」＝ jmx:DateTime）。
- 検証：`now` はタイムゾーン必須（なければ `ValueError`）。`max_age` / `max_future` が負なら `ValueError`。
- スキップの優先順位：STATUS → UNSUPPORTED → DUPLICATE → STALE → TOO_OLD → FUTURE。
- TOO_OLD / FUTURE でスキップした電文は `Ledger` に記録しない（あとで `now` なしで適用し直せる）。
- `State` Protocol（`pyjmaxml/state/base.py`）の `apply` のシグネチャも、同じキーワード引数を持つ形に更新する。
- `SkipReason` の docstring かコメントに、`TOO_OLD` / `FUTURE` は運用指針 §2.1.3.6 によるものと書く。

### 3.2 既定値の根拠（README にも書く）

- `max_age=24時間`：再起動時は長期フィード（数日分）も読むが、まだ発表中の古い要素は約10分ごとの VPWS50 に `Kind/DateTime` つきで載るので、24時間より古い VPWW を捨てても状態は回復する。保存しておいた古い電文をうっかり流し込む事故を防ぐ。
- `max_future=10分`：利用者側の時計の多少のずれを許す。
- どちらも引数で変えられる（運用指針の「基準値は可変」）。

### 3.3 README・実行例

- README の「取得から状態の更新まで」の最初の例と、非同期の例は**テストでオフライン実行され、2020年のサンプル電文を使う**（`tests/test_readme_example.py`）。ここに `now=` を足すとサンプルが TOO_OLD になってテストが落ちるので、**この2つのコードブロックは変えない**。
- 代わりに、ポーリングの節に次を文章と短いコード片で足す（テストで実行されない位置に置く。`tests/test_readme_example.py` がどのブロックを拾うかを確認すること）。
  - 実運用では `state.apply(report, now=datetime.now(UTC))` のように現在時刻を渡すと、運用指針 §2.1.3.6 に従って古すぎる・未来すぎる電文を捨てられる
  - 既定値と、その変え方
  - スキップされた電文も ack してよい（既存の「スキップした場合もackします」の段落に `too_old` / `future` を足す）
- `examples/poll_warnings.py`：オンライン実行時だけ `now=datetime.now(UTC)` を渡し、`--offline-sample` のときは渡さない。

## 4. テスト

### 4.1 golden（新しいケースを足す。既存は変えない）

`tests/golden/g06d_vpws50_then_old_vpww/case.json`：

1. `../_shared/vpws50_20261112T0000.xml` → `applied: true`, `cities: {"0121400": []}`
2. `../_shared/vpww55_wakkanai_20200622T2300.xml`, `roundtrip_before: true` → `applied: true`, `skip_reason: null`, `cities: {"0121400": []}`, `changes: {"count": 0}`

- 2 は別の情報単位なので Ledger ではスキップされない（`applied: true`）が、セルは更新されない。g06c の3手目（同じ情報単位なので `stale`）とは結果が違う点に注意。
- `roundtrip_before` で、`cleared` が JSON 経由でも保たれることを確かめる。
- `description` は日本語で、上の意図を書く。`tests/golden/README.md` のケース一覧があれば追記する。
- `tests/golden/README.md` の `skip_reason` の値の一覧に `"too_old"` / `"future"` を足す（このケースでは使わない）。

### 4.2 `tests/test_warning_state.py` に追加

- 市町村等の Warning がない VPWS50 → セルのない市町村への、それより古い VPWW が効かないこと（`cleared_all`）。既存の合成電文ヘルパー（`weather(...)` など）を使う。
- VPWS50 の watermark より**新しい** VPWW は、セルがなくても適用されること（直しすぎていないことの確認）。
- `cleared` / `cleared_all` の JSON 往復、項目がない古い JSON を読めること、不正な型で `ValueError` になること。
- 修正Bの単体テスト：
  - `now` なしなら、どんなに古い電文も今までどおり適用される
  - 境界値：ちょうど `now - max_age` は適用、1秒古いと `TOO_OLD`。ちょうど `now + max_future` は適用、1秒先だと `FUTURE`
  - `max_age=None` / `max_future=None` で判定しない
  - naive な `now`、負の `max_age` / `max_future` で `ValueError`
  - スキップの優先順位（DUPLICATE・STALE が TOO_OLD より先）
  - TOO_OLD でスキップした電文を、あとで `now` なしで適用すると適用されること（Ledger に記録されていない）

### 4.3 順序入れ替えの性質テスト（新しいファイル `tests/test_state_order.py`）

- `tests/golden/_shared/*.xml` の8通を一度だけ parse し、`random.Random(0)` で並べ替えた順で適用した最終状態（`cities()` を名前の集合にしたもの と `rivers()`）が、`Control/DateTime` の順で適用した結果と一致すること。`ValueError` を投げる電文は無視してよい（VPWW54・VPWP50 は対象外として skip される）。
- VPWS50 の適用は1回0.1秒近くかかるので、並べ替えは**30通り**に抑え、加えて上の再現ケース（VPWS50 → 稚内 VPWW55 2通）を必ず含める。テスト全体で数秒以内に収める。
- 修正A を入れる前にこのテストが落ちること、入れた後に通ることを確認し、IMPLEMENTATION_STATUS に書く。

## 5. 完了条件

- `uv run pytest`：全件成功（skip・xfail なし）
- `uv run ruff check` / `uv run ruff format --check`：成功
- `uv run pyright`：エラー0件・警告0件
- `uv run pyright --verifytypes pyjmaxml --ignoreexternal`：100%
- `uv run python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400` が今までどおり動く
- ベンチマークの前後比較（§2.5）
- CHANGELOG の 0.1.0 に1〜2行追記（VPWS50 の「発表なし」の記録、`apply(now=...)` による時刻の範囲外の電文の破棄）
- IMPLEMENTATION_STATUS の末尾に節を足す（何を直したか、テスト件数、ベンチマーク、確認したこと・していないこと）
- 終わったら、変更したファイルの一覧と、計画から外れたところ（あれば理由）を報告する

## 6. やらないこと

- 河川（VXKO・VXSU）の扱いの変更（順序入れ替えで差分が出ないことを確認済み）
- フィード側（`pyjmaxml/feed/`）の変更（コミット前の並び順の修正で完了している）
- JSON の version を 2 に上げること
- `WarningState` に時計を持たせること
