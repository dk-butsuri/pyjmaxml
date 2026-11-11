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
