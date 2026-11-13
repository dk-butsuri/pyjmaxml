import logging
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pyjmaxml import Element, WarningTimeSeries, parse, warning_timeseries

TESTS = Path(__file__).parent
SAMPLES = TESTS / "data" / "samples"
REAL = TESTS / "data" / "timeseries"
FILES = sorted(SAMPLES.glob("81_01_0[1-4]_*_VPWP50.xml")) + sorted(REAL.glob("*.xml"))
SAMPLE = SAMPLES / "81_01_01_260129_VPWP50.xml"
SOYA = REAL / "20261112075502_0_VPWP50_011000.xml"
TOYAMA = REAL / "20261112075543_0_VPWP50_160000.xml"
MIYAKO = REAL / "20261112075708_0_VPWP50_473000.xml"
NS = {"m": "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/"}
VALUE_TAGS = {
    "Significancy",
    "Precipitation",
    "SnowfallDepth",
    "WindDirection",
    "WindSpeed",
    "WaveHeight",
    "TidalLevel",
    "Humidity",
}


def load(path: Path) -> WarningTimeSeries:
    return warning_timeseries(parse(path, strict=True))


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_every_value_is_classified(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = load(path)
    assert result.cells
    assert all(cell.element is not Element.UNKNOWN for cell in result.cells)
    assert all(cell.start.utcoffset() is not None for cell in result.cells)
    assert all(cell.text is not None for cell in result.cells if cell.code is not None)
    assert all(cell.code is not None for cell in result.cells if cell.label.endswith("危険度"))
    assert not caplog.records
    root = ET.parse(path).getroot()
    xml_values = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in VALUE_TAGS]
    assert len(result.cells) == len(xml_values)
    # Traverse the XML itself to check source order and TimeDefine scoping, including
    # the two Part types in 風 / 高潮 and the repeated HumidityPart in 乾燥.
    expected = []
    for series in root.findall(".//m:TimeSeriesInfo", NS):
        starts = {
            node.attrib["timeId"]: datetime.fromisoformat(node.findtext("m:DateTime", "", NS))
            for node in series.findall("m:TimeDefines/m:TimeDefine", NS)
        }
        for item in series.findall("m:Item", NS):
            for node in item.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag not in VALUE_TAGS:
                    continue
                value = (
                    node.findtext("m:Code", namespaces=NS)
                    if tag == "Significancy"
                    else node.text
                    if tag == "WindDirection"
                    else float(node.text)
                    if node.text
                    else None
                )
                expected.append(
                    (
                        item.findtext("m:Area/m:Code", namespaces=NS),
                        node.attrib["type"],
                        starts[node.attrib["refID"]],
                        value,
                    )
                )
    assert [
        (
            cell.area_code,
            cell.label,
            cell.start,
            cell.code if cell.code is not None else cell.text or cell.number,
        )
        for cell in result.cells
    ] == expected


def test_sample_periods_and_missing_values() -> None:
    result = load(SAMPLE)
    assert result.report_date_time == parse(SAMPLE, strict=True).head.report_date_time
    rain = [cell for cell in result.by_city("0121400") if cell.property == "雨"]
    hourly = [cell for cell in rain if cell.label == "１時間最大雨量"]
    assert len(hourly) == 14
    assert {cell.duration for cell in hourly} == {timedelta(hours=3)}
    assert (hourly[0].start.isoformat(), hourly[0].period_name) == (
        "2023-06-22T06:00:00+09:00",
        "２２日朝",
    )
    daily = [cell for cell in rain if cell.label == "２４時間最大雨量"]
    assert [cell.duration for cell in daily] == [timedelta(days=1)] * 2
    assert [cell.period_name for cell in daily] == ["２３日０６時まで", "２３日"]
    assert [cell.number for cell in daily] == [80.0, 80.0]
    assert {cell.unit for cell in daily} == {"mm"}
    dryness = [cell for cell in result.by_city("0121400") if cell.property == "乾燥危険度"]
    assert [cell.duration for cell in dryness] == [
        timedelta(hours=18),
        timedelta(days=1),
        timedelta(days=1),
    ]
    assert [cell.period_name for cell in dryness] == ["２２日", "２３日", "２４日"]
    humidity = [
        cell
        for cell in result.by_city("0121400")
        if cell.property == "乾燥" and cell.start.day == 24
    ]
    assert {cell.label for cell in humidity} == {"実効湿度", "最小湿度"}
    assert all(cell.number is None and cell.condition == "値なし" for cell in humidity)
    surge = [cell for cell in result.cells if cell.property == "高潮危険度"]
    assert any(cell.code == "00" and cell.text == "値なし" for cell in surge)
    wind = [cell for cell in result.by_city("0121400") if cell.property == "風"]
    direction = next(cell for cell in wind if cell.label == "風向")
    assert (direction.text, direction.number, direction.unit) == ("北西", None, "８方位漢字")
    assert direction.condition == "風雪"
    assert all(cell.element is Element.STORM for cell in wind)


def test_soya_local_wind_significancy() -> None:
    result = load(SOYA)
    wind = [cell for cell in result.by_city("0121400") if cell.property == "風危険度"]
    assert list(dict.fromkeys(cell.local for cell in wind)) == ["陸上", "宗谷海峡"]
    for local in ("陸上", "宗谷海峡"):
        cells = [cell for cell in wind if cell.local == local]
        assert [cell.code for cell in cells] == ["20"] * 4 + ["01"] * 6
        assert [cell.text for cell in cells] == ["注意報級"] * 4 + ["注意報級未満"] * 6
        assert all(cell.area_name == "稚内市" for cell in cells)
    assert any(cell.local == "" for cell in result.cells)
    assert any(cell.local != "" for cell in result.cells)


def test_toyama_runup_water_level_is_storm_surge() -> None:
    surge = [
        cell
        for cell in load(TOYAMA).by_city("1620700")
        if cell.property == "高潮" and cell.local == "黒部市区間"
    ]
    assert [cell.label for cell in surge] == ["うちあげ高水位"] * 10 + ["潮位"] * 10
    assert all(cell.element is Element.STORM_SURGE and cell.unit == "m" for cell in surge)
    assert [cell.number for cell in surge[:10]] == [
        0.3,
        0.2,
        0.3,
        0.3,
        0.3,
        0.2,
        0.2,
        0.2,
        0.2,
        0.2,
    ]
    assert [cell.number for cell in surge[10:]] == [
        0.0,
        0.1,
        0.1,
        0.1,
        0.1,
        0.0,
        0.0,
        0.1,
        0.1,
        0.1,
    ]
    assert [cell.description for cell in surge[:3]] == [
        "標高　０．３メートルの高さ",
        "標高　０．２メートルの高さ",
        "標高　０．３メートルの高さ",
    ]
    assert all(cell.code is None and cell.text is None for cell in surge)


def test_miyako_part_notes() -> None:
    result = load(MIYAKO)
    waves = [cell for cell in result.cells if cell.property == "波危険度"]
    assert waves and all(cell.notes == ("うねり",) for cell in waves)
    assert all(cell.notes == () for cell in result.cells if cell.property != "波危険度")


def test_part_notes_are_also_attached_to_local_cells() -> None:
    root = ET.parse(MIYAKO).getroot()
    prop = next(
        prop
        for prop in root.findall(".//m:Property", NS)
        if prop.findtext("m:Type", namespaces=NS) == "波危険度"
    )
    base = prop.find("m:SignificancyPart/m:Base", NS)
    assert base is not None
    local = ET.Element(f"{{{NS['m']}}}Local")
    ET.SubElement(local, f"{{{NS['m']}}}AreaName").text = "海上"
    for node in list(base.findall("m:Significancy", NS)):
        base.remove(node)
        local.append(node)
    base.append(local)
    result = warning_timeseries(parse(ET.tostring(root), strict=True))
    waves = [cell for cell in result.by_city("4721400") if cell.property == "波危険度"]
    assert waves and all(cell.local == "海上" and cell.notes == ("うねり",) for cell in waves)


def test_by_city_uses_exact_codes() -> None:
    result = load(SOYA)
    assert result.by_city("0121400") == tuple(
        cell for cell in result.cells if cell.area_code == "0121400"
    )
    assert result.by_city("0121400")
    assert result.by_city("011000") == ()
    assert result.by_city("9999999") == ()


def test_unknown_type_is_preserved_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    text = SAMPLE.read_text(encoding="utf-8").replace(
        "<Type>霜危険度</Type>", "<Type>霜害危険度</Type>"
    )
    with caplog.at_level(logging.WARNING):
        result = warning_timeseries(parse(text, strict=True))
    unknown = [cell for cell in result.cells if cell.element is Element.UNKNOWN]
    assert unknown and {cell.property for cell in unknown} == {"霜害危険度"}
    assert all(cell.code is not None and cell.label == "霜危険度" for cell in unknown)
    assert "Unknown warning time series type '霜害危険度'" in caplog.text


def test_unsupported_part_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    text = SAMPLE.read_text(encoding="utf-8").replace(
        "SignificancyPart>", "SubsequentSignificancyPart>"
    )
    with caplog.at_level(logging.WARNING):
        result = warning_timeseries(parse(text, strict=True))
    assert result.cells
    assert "has no supported part" in caplog.text


def test_undefined_ref_id_is_rejected() -> None:
    text = SAMPLE.read_text(encoding="utf-8").replace('refID="1"', 'refID="999"', 1)
    with pytest.raises(ValueError, match="refID 999"):
        warning_timeseries(parse(text, strict=True))


def test_missing_area_code_is_rejected() -> None:
    text = SAMPLE.read_text(encoding="utf-8").replace("<Code>0121400</Code>", "", 1)
    with pytest.raises(ValueError, match="Area/Code"):
        warning_timeseries(parse(text, strict=True))


@pytest.mark.parametrize("group", ["VPWS50", "VPFD60"])
def test_other_reports_are_rejected(group: str) -> None:
    path = next(SAMPLES.glob(f"*_{group}.xml"))
    with pytest.raises(ValueError, match="Not a warning time series report"):
        load(path)


def test_non_meteorological_body_is_rejected() -> None:
    report = parse(SAMPLE, strict=True)
    earthquake = parse(next(SAMPLES.glob("*_VXSE53.xml")), strict=True)
    with pytest.raises(ValueError, match="require a meteorological Body"):
        warning_timeseries(replace(report, body=earthquake.body))


def test_control_status_is_not_filtered() -> None:
    report = parse(SAMPLE, strict=True)
    training = replace(report, control=replace(report.control, status="訓練"))
    assert warning_timeseries(training) == warning_timeseries(report)


def test_readme_timeseries_example(capsys: pytest.CaptureFixture[str]) -> None:
    readme = (TESTS.parent / "docs/guide.md").read_text(encoding="utf-8")
    block = next(
        block.split("```", 1)[0]
        for block in readme.split("```python\n")[1:]
        if "import parse, warning_timeseries" in block.split("```", 1)[0]
    )
    namespace = {}
    exec(compile(block, "README.md", "exec"), namespace)
    assert namespace["result"].by_city("4721400")
    assert "うねり" in capsys.readouterr().out
