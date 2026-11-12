# 計画：気象警報・注意報時系列情報（VPWP50）の正規化 API

作成 2026-11-12。実装担当向けの指示書。**このファイルに書いていないことを決める必要が出たら、実装を止めて報告すること。**

## 0. 前提と作業ルール

- `git commit`・push はしない。
- `tests/golden/` は触らない。VPWP50 は今後も `WarningState` の入力にしない（golden g07 で無視されることを確認済み。README の「時系列のVPWP50は対象外」の記述もそのまま）。
- コマンドはすべて `uv run` で実行する（`.venv/Scripts/python` を直接使うと pyright が誤ったエラーを出す）。
- `pyjmaxml/**/*.py` は LF 改行（`.gitattributes`）。
- 既存の正規化モジュール（特に `pyjmaxml/normalize/possibility.py` と `forecast.py`）の書き方・命名・ログの出し方に合わせる。`forecast.py`・`possibility.py` 自体は変更しない。
- テストや CI から気象庁にはアクセスしない。
- 完了条件は §7。
- この計画のあとに `tracker-plan.md` を実装する。そこで `AreaView.timeseries` としてこの API を使う。

## 1. 背景

- VPWP50（Title `気象警報・注意報時系列情報（Ｒ０６）`）は regular フィードで配信される。2026-11-05〜12 の長期フィードに1,664件あった。
  `pyjmaxml/kinds.py` の対応表には登録済みで、`parse()` でも読める。足りないのは、中身を使いやすく展開する正規化 API だけ。
- 気象庁の解説資料では、VPWP50 は「発表状況を示すものではない」とされている。この API は**予想の時系列を展開するだけ**にして、警報が出ているかどうかの判定には使わない。

## 2. 電文の構造（調査済み。推測ではない）

調べた電文：サンプル `tests/data/samples/81_01_0[1-4]_*_VPWP50.xml`（4件）と、2026-11-12 に長期フィードから府県ごとに最新1件ずつ取った実電文58件（`tmp/vpwp50/x/`、約47MB）。
62件すべて `parse(path, strict=True)` が通る。

```
Body/MeteorologicalInfos[@type="量的予想時系列（市町村等）"]   … 1個
  TimeSeriesInfo                                               … 3個（下の表）
    TimeDefines/TimeDefine(timeId, DateTime, Duration, Name)
    Item
      Area/Code, Area/Name     … 市町村等コード（7桁）。例 0121400 稚内市
      Kind                     … 1 Item に 1〜16個。1 Kind に Property 1個
        Status                 … 全件「発表」
        DateTime type="発表時刻"
        Property
          Type                 … 下の表の「Property/Type」
          ○○Part/Base          … 値の並び。値の refID が TimeDefine の timeId
```

| TimeSeriesInfo | Duration | Property/Type |
|---|---|---|
| 1個目 | PT3H（8〜14個） | 大雨浸水危険度, 雨, 土砂災害危険度, 風危険度, 風, 雪危険度, 雪, 波危険度, 波, 高潮危険度, 高潮, 雷危険度, 融雪危険度, 濃霧危険度, 着氷危険度, 着雪危険度 |
| 2個目 | PT24H（2個） | 雨, 雪 |
| 3個目 | PT6H〜PT24H（2〜3個） | 乾燥危険度, 乾燥, なだれ危険度, 低温危険度, 霜危険度 |

TimeSeriesInfo が何番目か、で区別してはいけない。必ず refID → TimeDefine で時刻を引くこと。

### 2.1 Part の種類（生成クラス `TypeProperty1` のフィールド）

| フィールド | 値の要素（`type_value`） | 値 |
|---|---|---|
| `significancy_part`（list） | `Significancy`（`○○危険度`） | `code`（"00" "01" "11" "20" を確認）と `name`（値なし／注意報級未満／警戒レベル２未満／注意報級） |
| `precipitation_part` | `Precipitation`（１時間最大雨量, ２４時間最大雨量） | 数値, unit mm |
| `snowfall_depth_part` | `SnowfallDepth`（６時間最大降雪量, ２４時間最大降雪量） | 数値, unit cm |
| `wind_direction_part` | `WindDirection`（風向） | 文字（"南" など）, unit ８方位漢字 |
| `wind_speed_part` | `WindSpeed`（最大風速） | 数値, unit m/s |
| `wave_height_part` | `WaveHeight`（波高、**うちあげ高水位**） | 数値, unit m |
| `tidal_level_part` | `TidalLevel`（潮位） | 数値, unit m |
| `humidity_part`（list、1 Property に2個） | `Humidity`（実効湿度, 最小湿度） | 数値, unit %。空要素＋`condition="値なし"` が多い |

- 1つの Property に Part が2つ並ぶことがある：`風` = WindDirectionPart＋WindSpeedPart、`乾燥` = HumidityPart×2、`高潮` = TidalLevelPart（富山 `160000` の3件だけ WaveHeightPart「うちあげ高水位」＋TidalLevelPart）。
- 実際に使うフィールドが list か単体かは、`pyjmaxml/_generated/jmx.py` で必ず確認すること（`significancy_part` は list だった）。
- 各 `○○Part.base` には、値が直接並ぶ場合と、`local`（list）の中に `area_name` と値が並ぶ場合がある。
  - Local の AreaName の例：陸上、海上、宗谷海峡、山間部、黒部市区間
  - 実電文では、Local は SignificancyPart・WindDirection/SpeedPart・SnowfallDepthPart・WaveHeightPart・TidalLevelPart に出る
- `SignificancyPart.base.addition.note`（list[str]）：その Part 全体への注記。期間ごとではない。例 `("竜巻", "ひょう")`、`("突風",)`、`("うねり",)`。生成クラスでは Local 側に addition はない。
- 値の `condition`：`風雪`（風向・最大風速）、`値なし`（湿度・潮位、値は空）。
- 値の `description`：`"１５メートル"`、`"標高　０．３メートルの高さ"` など。そのまま保持する。
- 空の数値は、xsdata では `NullablefloatValue` などの Enum になる。`forecast.py` の `_number()` と同じく、Enum と None を `None` にする。

### 2.2 危険度コードの意味は確定させない

実電文で見たコードは `00` 値なし／`01` 注意報級未満／`11` 警戒レベル２未満／`20` 注意報級 だけ。
警報級以上のコードの公式な定義は手元にない（`vendor/jmaxml_20261110_code.xlsx` は「気象警報・注意報（Ｒ０６）及び気象警報・注意報時系列情報（Ｒ０６）XML電文解説資料を参照」としか書いていない）。
**このため、コードを Stage やレベルに変換しない。`code` と `name` をそのまま渡す。** 変換表は、解説資料の別表を確認してから別の作業で足す。

## 3. 公開 API

新しいモジュール `pyjmaxml/normalize/timeseries.py` に置く。

```python
@dataclass(frozen=True)
class WarningTimeSeriesCell:
    """One city, local subarea, value type and period."""

    area_code: str  # Item/Area/Code（市町村等コード）
    area_name: str  # Item/Area/Name
    local: str  # Local/AreaName。Local がなければ ""
    element: Element  # Property/Type から（§3.1）
    property: str  # Property/Type。例 "風危険度", "風", "高潮"
    label: str  # 値の @type。例 "風危険度", "最大風速", "うちあげ高水位"
    start: datetime  # TimeDefine/DateTime（タイムゾーンつき）
    duration: timedelta | None
    period_name: str  # TimeDefine/Name。なければ ""
    code: str | None  # Significancy/Code。危険度以外は None
    text: str | None  # Significancy/Name、または風向の値。数値の値は None
    number: float | None  # 数値の値。危険度・風向・値なしは None
    unit: str  # 値の @unit。なければ ""
    condition: str  # 値の @condition。なければ ""
    description: str  # 値の @description。なければ ""
    notes: tuple[str, ...]  # SignificancyPart/Base/Addition/Note。なければ ()


@dataclass(frozen=True)
class WarningTimeSeries:
    report_date_time: datetime
    cells: tuple[WarningTimeSeriesCell, ...]

    def by_city(self, code: str) -> tuple[WarningTimeSeriesCell, ...]:
        """Cells whose Area/Code equals the city code; no parent or fallback lookup."""


def warning_timeseries(report: Report) -> WarningTimeSeries:
    """Flatten a VPWP50 report; Control/Status is not checked."""
```

- セルの並びは電文の出現順（TimeSeriesInfo → Item → Kind → Property → Part → Local → 値）。
- `notes` は、その SignificancyPart のすべてのセル（Local の中のセルも含む）に同じ値を付ける。
- `data_type_code(report) != "VPWP50"` なら `ValueError("Not a warning time series report: <Control/Title>")`。Body が `MeteBody` でなければ `ValueError`。
- refID が TimeDefine にない、Item に Area/Code がない場合は `ValueError`（メッセージに refID を含める。`possibility.py` と同じ）。
- `Kind/Status` と `Kind/DateTime` は使わない（全件「発表」で、発表状況を表すものではないため）。
- `group` フィールドは付けない（VPWP50 しかないため）。

### 3.1 Property/Type → Element

| Property/Type | Element |
|---|---|
| 大雨浸水危険度, 雨 | HEAVY_RAIN |
| 土砂災害危険度 | LANDSLIDE |
| 風危険度, 風 | STORM（風雪は `condition="風雪"` で区別できる。SNOWSTORM には分けない） |
| 雪危険度, 雪 | HEAVY_SNOW |
| 波危険度, 波 | HIGH_WAVE |
| 高潮危険度, 高潮 | STORM_SURGE |
| 雷危険度, 融雪危険度, 濃霧危険度, 着氷危険度, 着雪危険度, 乾燥危険度, 乾燥, なだれ危険度, 低温危険度, 霜危険度 | OTHER |

表にない Property/Type は `Element.UNKNOWN` にして `_LOGGER.warning("Unknown warning time series type %r", ...)` を出す。
§2.1 の表にない Part だけを持つ Property も warning を出す（`forecast.py` の「has no supported part」と同じ）。

### 3.2 公開

- `pyjmaxml/normalize/__init__.py` と `pyjmaxml/__init__.py` の import と `__all__`（アルファベット順）に、`WarningTimeSeries`・`WarningTimeSeriesCell`・`warning_timeseries` を足す。
- `pyright --verifytypes` で 100% を保つ（公開するものすべてに型注釈）。

## 4. テストデータ

`tests/data/timeseries/` を作り、`tmp/vpwp50/x/` から次の3件をそのままコピーする（中身を書き換えない）。

| ファイル | 大きさ | 使う理由 |
|---|---|---|
| `20261112075502_0_VPWP50_011000.xml` | 316KB | 宗谷地方。風危険度が Local（陸上・宗谷海峡 など）で、注意報級（20）がある |
| `20261112075543_0_VPWP50_160000.xml` | 496KB | 富山県。高潮の WaveHeightPart「うちあげ高水位」と TidalLevelPart が Local（黒部市区間 など） |
| `20261112075708_0_VPWP50_473000.xml` | 45KB | 宮古島地方。波危険度が注意報級で、Addition/Note「うねり」、Local 陸上・海上 |

`tests/data/timeseries/README.md` を `tests/data/possibility/README.md` と同じ形式で書く（取得日 2026-11-12、長期 regular フィードから1回だけ取得、表、出典「気象庁防災情報XML（気象庁）」）。

## 5. テスト（`tests/test_timeseries.py`）

`tests/test_possibility.py`・`tests/test_forecast.py` の形に合わせる。期待値は**実装の出力から写さず、XML を読んで書く**こと。

1. サンプル4件＋実電文3件のパラメータ化テスト（`strict=True`）
   - セルが空でない、`Element.UNKNOWN` がない、WARNING 以上のログがない、`start` がタイムゾーンつき
   - `code is not None` のセルは `text` もある。`label` が「危険度」で終わるセルは `code` がある
   - **セル数が、ElementTree で数えた値の要素（Significancy・Precipitation・SnowfallDepth・WindDirection・WindSpeed・WaveHeight・TidalLevel・Humidity）の数と一致する**（取りこぼし・二重計上の検出）
2. `81_01_01_260129_VPWP50.xml`
   - 3時間・24時間・日ごとの3系列が、それぞれ正しい `duration` と `period_name` で出る（例：24時間系列は PT24H、`"２３日０６時まで"`）
   - `乾燥` の湿度が `number is None`、`condition == "値なし"`
   - `高潮危険度` に `code == "00"`、`text == "値なし"` がある
3. `011000`：ある市町村の `風危険度` を `local` ごとに取り出し、期間ごとの `code` の並び（`"20"` と `"01"`）が XML と一致する。`local == ""` のセルと Local 付きのセルが両方ある
4. `160000`：`property == "高潮"`、`label == "うちあげ高水位"`、`local == "黒部市区間"` のセルが `element is Element.STORM_SURGE`、`unit == "m"`、`number` と `description` が XML どおり。同じ Local の `潮位` も出る
5. `473000`：`波危険度` のセルの `notes == ("うねり",)`、注記のない Part のセルは `notes == ()`
6. `by_city`：Item にある市町村コードはそのコードのセルだけを返す。存在しないコードは `()`
7. 未知の Property/Type：XML 文字列を置き換えて（例 `<Type>霜危険度</Type>` → `<Type>霜害危険度</Type>`）、UNKNOWN になりログが出る
8. 未定義の refID は `ValueError`、メッセージに refID
9. VPWS50・VPFD60 などは `ValueError("Not a warning time series report")`

## 6. ドキュメント

- `README.md`：`weather_forecast` の節の近くに `warning_timeseries(report)` の節を足す。書くこと：
  - VPWP50 を市町村・Local・値の種類・時間帯ごとの `WarningTimeSeriesCell` に展開する。regular フィードに配信される
  - **発表中の警報を表すものではない**（それは `WarningState`）
  - 危険度は `code`・`text` をそのまま返し、レベルへの変換はしない
  - `tests/data/timeseries/20261112075708_0_VPWP50_473000.xml` を使う短いコード例
  - `test_readme_example.py` が README のコード例を検査する仕組みになっていれば、それに合わせる
- `CHANGELOG.md`：0.1.0 の箇条書きに1行足す。
- `IMPLEMENTATION_STATUS.md`：既存の節と同じ形式で、変更したファイル・テスト結果・未検証のことを追記する。

## 7. 完了条件

- `uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pyright --verifytypes pyjmaxml --ignoreexternal`（100%）、`uv run pytest` がすべて成功
- `git diff --check` 成功、新しい `.py` が LF
- 既存のテスト・golden に変更なし

## 8. やらないこと

- 危険度コードを Stage・レベルに変換すること（§2.2）
- `WarningState` に VPWP50 をつなぐこと
- Local の AreaName を地域コードに対応させること
- 府県・一次細分区域コードでの `by_city` の繰り上げ検索（Item は市町村等コードだけなので不要）
- `Kind/DateTime`（発表時刻）の保持
