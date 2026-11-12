import logging
from datetime import timedelta
from pathlib import Path

import pytest

from pyjmaxml import ForecastCell, ForecastElement, WeatherForecast, parse, weather_forecast

TESTS = Path(__file__).parent
SAMPLES = TESTS / "data" / "samples"
REAL = TESTS / "data" / "forecast"
FILES = sorted(SAMPLES.glob("*_VPF[DW]5[01].xml")) + sorted(REAL.glob("*.xml"))
TOKYO = REAL / "20261111073453_0_VPFD51_130000.xml"
TOKYO_WEEK = REAL / "20261111073607_0_VPFW50_130000.xml"


def load(path: Path) -> WeatherForecast:
    return weather_forecast(parse(path, strict=True))


def values(cells: tuple[ForecastCell, ...], element: ForecastElement, attr: str) -> list[object]:
    return [getattr(cell, attr) for cell in cells if cell.element is element]


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_every_value_is_classified(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = load(path)
    assert result.group in path.name
    assert result.cells
    assert all(cell.element is not ForecastElement.UNKNOWN for cell in result.cells)
    assert all(cell.start.utcoffset() is not None for cell in result.cells)
    # Only explicitly missing values lack both text and number.
    assert {
        cell.condition for cell in result.cells if cell.text is None and cell.number is None
    } <= {"値なし"}
    assert not caplog.records


def test_vpfd51_area_forecast() -> None:
    area = load(TOKYO).by_area("130010")
    assert values(area, ForecastElement.WEATHER, "period_name") == ["今夜", "明日", "明後日"]
    assert values(area, ForecastElement.WEATHER, "text") == ["晴れ", "晴れ", "晴れ時々くもり"]
    assert values(area, ForecastElement.WEATHER_DETAIL, "text")[1] == "晴れ　明け方　まで　くもり"
    assert values(area, ForecastElement.WEATHER_CODE, "text") == ["100", "100", "101"]
    assert values(area, ForecastElement.WIND, "text")[1] == "北の風　後　南の風"
    assert values(area, ForecastElement.WAVE, "text")[0] == "０．５メートル"
    assert values(area, ForecastElement.WEATHER, "duration") == [
        timedelta(hours=7),
        timedelta(days=1),
        timedelta(days=1),
    ]
    assert values(area, ForecastElement.PRECIPITATION_PROBABILITY, "number") == [0.0] * 5
    assert set(values(area, ForecastElement.PRECIPITATION_PROBABILITY, "condition")) == {"雨"}
    assert set(values(area, ForecastElement.PRECIPITATION_PROBABILITY, "label")) == {
        "６時間降水確率"
    }


def test_vpfd51_station_and_three_hourly_forecast() -> None:
    result = load(TOKYO)
    station = result.by_station("44132")
    assert values(station, ForecastElement.MORNING_MIN_TEMPERATURE, "number") == [8.0]
    assert values(station, ForecastElement.DAYTIME_MAX_TEMPERATURE, "number") == [17.0]
    hourly = [c for c in station if c.element is ForecastElement.THREE_HOURLY_TEMPERATURE]
    assert [(c.start.hour, c.number) for c in hourly[:3]] == [(18, 12.0), (21, 11.0), (0, 11.0)]
    # 3-hourly temperature TimeDefines are instants without Duration.
    assert {c.duration for c in hourly} == {None}
    area = result.by_area("130010")
    assert values(area, ForecastElement.THREE_HOURLY_WIND_DIRECTION, "text")[:2] == ["南東", "北西"]
    speed = [c for c in area if c.element is ForecastElement.THREE_HOURLY_WIND_SPEED_LEVEL][0]
    assert (speed.number, speed.description) == (2.0, "毎秒３から５メートル")
    assert all(not cell.station for cell in area)


def test_whole_day_and_daytime_maximum_are_kept_apart() -> None:
    station = load(SAMPLES / "24_11_01_190925_VPFD51.xml").by_station("44132")
    assert [(c.element, c.period_name, c.number) for c in station if c.duration] == [
        (ForecastElement.DAYTIME_MAX_TEMPERATURE, "今日日中", 12.0),
        (ForecastElement.MAX_TEMPERATURE, "今日", 15.0),
        (ForecastElement.MORNING_MIN_TEMPERATURE, "明日朝", 1.0),
        (ForecastElement.DAYTIME_MAX_TEMPERATURE, "明日日中", 3.0),
    ]


def test_vpfw50_weekly_forecast() -> None:
    result = load(TOKYO_WEEK)
    area = result.by_area("130010")
    assert values(area, ForecastElement.WEATHER, "label") == ["基本天気"] * 7
    assert values(area, ForecastElement.PRECIPITATION_PROBABILITY, "number") == [
        None,
        10.0,
        20.0,
        50.0,
        30.0,
        50.0,
        50.0,
    ]
    assert values(area, ForecastElement.RELIABILITY, "text") == [
        None,
        None,
        "A",
        "C",
        "A",
        "C",
        "C",
    ]
    assert values(area, ForecastElement.RELIABILITY, "condition")[:3] == ["値なし", "値なし", ""]
    station = result.by_station("44132")
    assert values(station, ForecastElement.MAX_TEMPERATURE, "number")[:3] == [None, 21.0, 21.0]
    assert values(station, ForecastElement.MAX_TEMPERATURE_UPPER, "number")[1] == 23.0
    assert values(station, ForecastElement.MAX_TEMPERATURE_LOWER, "number")[1] == 19.0
    assert values(station, ForecastElement.MAX_TEMPERATURE_NORMAL, "number")[0] == 17.3
    assert {c.start.day for c in station} == set(range(12, 19))


def test_by_city_falls_back_to_coarser_weekly_areas() -> None:
    tokyo = load(TOKYO)
    # 千代田区 is in 東京地方, 八丈町 in 伊豆諸島南部.
    assert tokyo.by_city("1310100") == tokyo.by_area("130010")
    assert tokyo.by_city("1340100") == tokyo.by_area("130030")
    assert tokyo.by_city("4620100") == ()
    assert tokyo.by_city("9999999") == ()
    kagoshima = load(REAL / "20261111073534_0_VPFW50_460100.xml")
    # 鹿児島市 (薩摩地方) is covered by 鹿児島県（奄美地方除く）; 奄美市 keeps its own area.
    assert {c.code for c in kagoshima.by_city("4620100")} == {"460100"}
    assert {c.code for c in kagoshima.by_city("4622200")} == {"460040"}
    kushiro = load(REAL / "20261111073838_0_VPFW50_014100.xml")
    # 帯広市 (十勝地方 014030) is covered by 釧路・根室・十勝地方 014000.
    assert {c.code for c in kushiro.by_city("0120700")} == {"014000"}


def test_unknown_element_and_property_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    text = TOKYO_WEEK.read_text(encoding="utf-8")
    text = text.replace('type="信頼度階級"', 'type="信頼度ランク"')
    with caplog.at_level(logging.WARNING):
        result = weather_forecast(parse(text, strict=True))
    unknown = [c for c in result.cells if c.element is ForecastElement.UNKNOWN]
    assert unknown and {c.label for c in unknown} == {"信頼度ランク"}
    assert caplog.records


def test_undefined_ref_id_is_rejected() -> None:
    text = TOKYO_WEEK.read_text(encoding="utf-8")
    text = text.replace('type="信頼度階級" refID="7"', 'type="信頼度階級" refID="9"', 1)
    with pytest.raises(ValueError, match="refID 9"):
        weather_forecast(parse(text, strict=True))


def test_other_reports_are_rejected() -> None:
    with pytest.raises(ValueError, match="Not a weather forecast report"):
        weather_forecast(parse(SAMPLES / "15_16_03_241226_VPWW55.xml", strict=True))
