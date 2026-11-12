import logging
from datetime import timedelta
from pathlib import Path

import pytest

from pyjmaxml import (
    Element,
    Possibility,
    WarningPossibility,
    parse,
    warning_possibility,
)

TESTS = Path(__file__).parent
SAMPLES = TESTS / "data" / "samples"
REAL = TESTS / "data" / "possibility"
FILES = sorted(SAMPLES.glob("*_VPF[DW]6[01].xml")) + sorted(REAL.glob("*.xml"))


def load(path: Path) -> WarningPossibility:
    return warning_possibility(parse(path, strict=True))


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_every_rank_is_classified(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = load(path)
    assert result.group in path.name
    assert result.cells
    assert all(cell.element is not Element.UNKNOWN for cell in result.cells)
    assert all(cell.possibility is not None for cell in result.cells)
    assert all(cell.start.utcoffset() is not None for cell in result.cells)
    assert not caplog.records


def test_vpfw60_periods_and_ranks() -> None:
    result = load(SAMPLES / "69_01_01_241031_VPFW60.xml")
    rain = [cell for cell in result.by_area("370000") if cell.element is Element.HEAVY_RAIN]
    assert [cell.possibility for cell in rain] == [
        Possibility.HIGH,
        Possibility.NONE,
        Possibility.HIGH,
        Possibility.MEDIUM,
    ]
    assert [cell.raw for cell in rain] == ["高", "値なし", "高", "中"]
    assert [cell.start.day for cell in rain] == [16, 17, 18, 19]
    assert {cell.duration for cell in rain} == {timedelta(days=1)}
    # VPFW60 TimeDefine has no Name.
    assert {cell.period_name for cell in rain} == {""}


def test_vpfd60_uses_only_the_possibility_series() -> None:
    result = load(SAMPLES / "68_01_01_220831_VPFD60.xml")
    # 5 elements x 3 periods; the 6-hourly rainfall and wind series are skipped.
    assert len(result.cells) == 15
    surge = [cell for cell in result.cells if cell.element is Element.STORM_SURGE]
    assert [cell.period_name for cell in surge] == [
        "２０日昼過ぎから夕方",
        "２０日夜のはじめ頃から２１日明け方",
        "２１日朝から夜遅く",
    ]
    assert [cell.duration for cell in surge] == [
        timedelta(hours=6),
        timedelta(hours=12),
        timedelta(hours=18),
    ]
    assert [cell.possibility for cell in surge] == [
        Possibility.NONE,
        Possibility.MEDIUM,
        Possibility.HIGH,
    ]


def test_snow_none_value_is_kept_apart_from_missing_value() -> None:
    result = load(SAMPLES / "68_01_01_220831_VPFD60.xml")
    snow = [cell for cell in result.cells if cell.element is Element.HEAVY_SNOW]
    assert {(cell.possibility, cell.raw) for cell in snow} == {(Possibility.NONE, "なし")}


def test_vpfd61_names_heavy_rain_and_landslide() -> None:
    result = load(SAMPLES / "90_01_01_241031_VPFD61.xml")
    names = {cell.name: cell.element for cell in result.cells}
    assert names["大雨の警報級の可能性"] is Element.HEAVY_RAIN
    assert names["土砂災害の警報級の可能性"] is Element.LANDSLIDE
    assert names["風（風雪）の警報級の可能性"] is Element.STORM


def test_real_report_has_every_primary_subdivision() -> None:
    result = load(REAL / "20261111073453_0_VPFD61_130000.xml")
    assert {cell.area_code for cell in result.cells} == {"130010", "130020", "130030", "130040"}
    assert len(result.by_area("130010")) == len(result.cells) // 4


def test_by_city_resolves_the_primary_subdivision() -> None:
    result = load(REAL / "20261111073453_0_VPFD61_130000.xml")
    # 千代田区 is in 東京地方, 八丈町 in 伊豆諸島南部.
    assert result.by_city("1310100") == result.by_area("130010")
    assert result.by_city("1340100") == result.by_area("130030")
    assert result.by_city("9999999") == ()


def test_unknown_type_and_value_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    text = (SAMPLES / "69_01_01_241031_VPFW60.xml").read_text(encoding="utf-8")
    text = text.replace("潮位の警報級の可能性", "霧の警報級の可能性")
    text = text.replace('type="雨の警報級の可能性">中<', 'type="雨の警報級の可能性">低<')
    with caplog.at_level(logging.WARNING):
        result = warning_possibility(parse(text, strict=True))
    fog = [cell for cell in result.cells if cell.name == "霧の警報級の可能性"]
    assert fog and {cell.element for cell in fog} == {Element.UNKNOWN}
    assert [cell.raw for cell in result.cells if cell.possibility is None] == ["低"]
    assert len(caplog.records) == 2


def test_undefined_ref_id_is_rejected() -> None:
    text = (SAMPLES / "69_01_01_241031_VPFW60.xml").read_text(encoding="utf-8")
    text = text.replace('refID="4" type="雨', 'refID="9" type="雨')
    with pytest.raises(ValueError, match="refID 9"):
        warning_possibility(parse(text, strict=True))


def test_other_reports_are_rejected() -> None:
    with pytest.raises(ValueError, match="Not a warning possibility report"):
        warning_possibility(parse(SAMPLES / "15_16_03_241226_VPWW55.xml", strict=True))
