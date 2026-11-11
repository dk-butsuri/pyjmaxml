# 録画したフィード（M2 のテスト用）

2026-11-12 00:45 JST に、気象庁 PULL型フィードの高頻度版を1回だけ取得したもの。テストや CI から気象庁にはアクセスしないこと。

| ファイル | 内容 |
|---|---|
| `regular.xml` / `regular.headers.txt` | `https://www.data.jma.go.jp/developer/xml/feed/regular.xml` の本文とレスポンスヘッダー（200） |
| `extra.xml` / `extra.headers.txt` | `.../feed/extra.xml` の本文とレスポンスヘッダー（200） |
| `extra.304.headers.txt` | 直後に `If-None-Match` と `If-Modified-Since` を付けて送った条件付き GET のレスポンスヘッダー |

わかったこと：
- ETag は弱い ETag（`W/"..."`）。`Last-Modified` も付く
- `Cache-Control: max-age=60`（最小ポーリング間隔 60秒と一致）
- 条件付き GET には **304 Not Modified** が返る（`extra.304.headers.txt`）

出典：気象庁防災情報XML（気象庁）
