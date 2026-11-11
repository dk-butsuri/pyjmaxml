# 気象庁公式サンプル XML

出典：[気象庁防災情報XMLフォーマット 技術資料](https://xml.kishou.go.jp/tec_material.html)

`jmaxml_20260917_Samples.zip` から XML 546件のみを抽出したもの。
電文の内容は変更していない。アーカイブの取得日と SHA-256 は
`scripts/manifest.toml` に記録している。

`uv run python scripts/codegen.py` で展開を再現できる。
テスト・CI からのダウンロードは行わない。
