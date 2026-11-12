# ゴールデンテスト（WarningState）

**このディレクトリの `case.json` と XML は仕様そのもの。実装に合わせて書き換えてはいけない。**
テストが通らないときは実装を直す。期待値が間違っていると思ったら、変更せずに報告する。

期待値は、電文の中身と気象庁の一次資料（下記）から手で決めた。実装の出力をコピーしたものではない。

## ファイル構成
```
_shared/                 複数のケースで使う電文
<case>/case.json         手順と期待値
<case>/NN.xml            そのケース用に書き換えた電文
_build_fixtures.py       書き換えた電文を作ったスクリプト（記録用。実行には /tmp/jma の作業ファイルが必要）
```

## case.json の形式
```jsonc
{
  "description": "...",
  "steps": [
    {
      "file": "02.xml",               // case.json からの相対パス
      "roundtrip_before": true,       // 省略時は false。true なら、apply の前に state = WarningState.from_json(state.to_json()) を行う
      "expect": {
        "applied": true,              // ApplyResult.applied
        "skip_reason": null,          // applied=false のときの理由："status" | "unsupported" | "duplicate" | "stale" | "too_old" | "future"
        "cities": {                   // state.by_city(code) を Kind 名の集合にしたもの。完全一致で比べる（[] は「何も発表されていない」）
          "0121400": ["レベル４大雨危険警報"]
        },
        "rivers": {                   // state.rivers()[key] の中身。完全一致で比べる
          "840410000100": {"group": "VXKO", "kinds": ["レベル２氾濫注意報"], "cities": ["1620200", "..."]}
        },
        "rivers_absent": ["..."],     // state.rivers() にキーがないこと
        "changes": {
          "count": 10,                // len(result.changes)（省略時は数を確認しない）
          "contains": [               // この (scope, area, group, type) を持つ Change が含まれること
            {"scope": "city", "area": "0121400", "group": "VPWW55", "type": "ISSUED"}
          ],
          "excludes_areas": ["..."]   // この area の Change が1つもないこと
        }
      }
    }
  ]
}
```
`cities` / `rivers` に書いていない市町村や河川は確認しない。

### ランナーの要件（`tests/test_golden.py`）
- ケースごとに新しい `WarningState()` を作り、steps を順に `apply(parse(file))` する
- `roundtrip_before` が true のときは、`to_json()` → `from_json()` を行い、`from_json(s).to_json() == s` であることも確認する
- 各ステップで、`expect` のキーがあるものだけを確認する

## 素材の出典
- `_shared/vpww55_*`、`vxko_*`、`vxsu_*`、`vpww54_h27.xml`、`vpwp50.xml`：気象庁防災情報XML サンプル電文（`jmaxml_20260917_Samples.zip`）
  - 15_16_03_241226_VPWW55 / 16_08_01_260312_VXKOii / 91_01_01_241031_VXSUii / 15_15_01_220314_VPWW54 / VPWP50 のサンプル
- `_shared/vpws50_20261112T0000.xml`、`_shared/vpww61_kagoshima_20261111T2122.xml`：気象庁 PULL型フィードで 2026-11-11 に実際に配信された電文
  - `20261111150121_0_VPWS50_010000.xml`、`20261111122220_0_VPWW61_460100.xml`
- 各ケースの `NN.xml`：上の電文の Control/DateTime・Status・ReportDateTime・InfoType・Kind を `_build_fixtures.py` で書き換えたもの。すべて公式 XSD（2024-10-31 版）で検証済み

出典：気象庁防災情報XML（気象庁）を加工して作成
