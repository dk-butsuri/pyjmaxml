"""Weather forecasts from 府県天気予報 (VPFD50, VPFD51) and 府県週間天気予報 (VPFW50)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import Literal, NamedTuple, cast

from .._generated.jmx import TypeProperty1, TypeTimeSeriesInfo
from ..codes import AREA_CITY
from ..kinds import data_type_code
from ..parse import MeteBody, Report
from ._time import periods

_LOGGER = logging.getLogger(__name__)
_GROUPS = frozenset({"VPFD50", "VPFD51", "VPFW50"})


class ForecastElement(StrEnum):
    WEATHER = "weather"
    WEATHER_DETAIL = "weather_detail"
    WEATHER_CODE = "weather_code"
    WIND = "wind"
    WAVE = "wave"
    PRECIPITATION_PROBABILITY = "precipitation_probability"
    RELIABILITY = "reliability"
    MAX_TEMPERATURE = "max_temperature"
    MIN_TEMPERATURE = "min_temperature"
    DAYTIME_MAX_TEMPERATURE = "daytime_max_temperature"
    MORNING_MIN_TEMPERATURE = "morning_min_temperature"
    MAX_TEMPERATURE_UPPER = "max_temperature_upper"
    MAX_TEMPERATURE_LOWER = "max_temperature_lower"
    MIN_TEMPERATURE_UPPER = "min_temperature_upper"
    MIN_TEMPERATURE_LOWER = "min_temperature_lower"
    MAX_TEMPERATURE_NORMAL = "max_temperature_normal"
    MIN_TEMPERATURE_NORMAL = "min_temperature_normal"
    THREE_HOURLY_WEATHER = "three_hourly_weather"
    THREE_HOURLY_WIND_DIRECTION = "three_hourly_wind_direction"
    THREE_HOURLY_WIND_SPEED_LEVEL = "three_hourly_wind_speed_level"
    THREE_HOURLY_TEMPERATURE = "three_hourly_temperature"
    UNKNOWN = "unknown"


_E = ForecastElement
# Keyed by (Property/Type, value type attribute), as seen in the pinned samples and
# the 2026 telegrams. 天気 is 基本天気 in VPFW50; 最高気温 is the whole-day maximum.
_ELEMENTS: dict[tuple[str, str], ForecastElement] = {
    ("天気", "天気"): _E.WEATHER,
    ("天気", "基本天気"): _E.WEATHER,
    ("天気", "天気予報用テロップ番号"): _E.WEATHER_CODE,
    ("降水確率", "６時間降水確率"): _E.PRECIPITATION_PROBABILITY,
    ("降水確率", "日降水確率"): _E.PRECIPITATION_PROBABILITY,
    ("信頼度", "信頼度階級"): _E.RELIABILITY,
    ("最高気温", "最高気温"): _E.MAX_TEMPERATURE,
    ("最低気温", "最低気温"): _E.MIN_TEMPERATURE,
    ("日中の最高気温", "日中の最高気温"): _E.DAYTIME_MAX_TEMPERATURE,
    ("朝の最低気温", "朝の最低気温"): _E.MORNING_MIN_TEMPERATURE,
    ("最高気温予測範囲", "最高気温予測範囲（上端）"): _E.MAX_TEMPERATURE_UPPER,
    ("最高気温予測範囲", "最高気温予測範囲（下端）"): _E.MAX_TEMPERATURE_LOWER,
    ("最低気温予測範囲", "最低気温予測範囲（上端）"): _E.MIN_TEMPERATURE_UPPER,
    ("最低気温予測範囲", "最低気温予測範囲（下端）"): _E.MIN_TEMPERATURE_LOWER,
    ("最高気温平年値", "最高気温平年値"): _E.MAX_TEMPERATURE_NORMAL,
    ("最低気温平年値", "最低気温平年値"): _E.MIN_TEMPERATURE_NORMAL,
    ("３時間内卓越天気", "天気"): _E.THREE_HOURLY_WEATHER,
    ("３時間内代表風", "風向"): _E.THREE_HOURLY_WIND_DIRECTION,
    ("３時間内代表風", "風速階級"): _E.THREE_HOURLY_WIND_SPEED_LEVEL,
    ("３時間毎気温", "気温"): _E.THREE_HOURLY_TEMPERATURE,
}


@dataclass(frozen=True)
class ForecastCell:
    """One area or station, element and period.

    text holds words, codes and sentences; number holds percentages, degrees and wind
    speed levels. Both are None when the value is missing (condition '値なし').
    """

    code: str
    name: str
    station: bool
    element: ForecastElement
    label: str
    start: datetime
    duration: timedelta | None
    period_name: str
    text: str | None
    number: float | None
    condition: str
    description: str


@dataclass(frozen=True)
class WeatherForecast:
    group: Literal["VPFD50", "VPFD51", "VPFW50"]
    report_date_time: datetime
    cells: tuple[ForecastCell, ...]

    def by_area(self, code: str) -> tuple[ForecastCell, ...]:
        """Area cells (天気, 降水確率 ...) for a forecast area code, e.g. 130010."""
        return tuple(cell for cell in self.cells if not cell.station and cell.code == code)

    def by_station(self, code: str) -> tuple[ForecastCell, ...]:
        """Station cells (気温) for a station code, e.g. 44132."""
        return tuple(cell for cell in self.cells if cell.station and cell.code == code)

    def by_city(self, code: str) -> tuple[ForecastCell, ...]:
        """Area cells covering a city; stations are not linked to cities.

        Tries the primary subdivision, then the prefectural forecast area and then
        the enclosing XXX000 region, because VPFW50 areas can be coarser (460100,
        014000) than the primary subdivisions used by VPFD51.
        """
        city = AREA_CITY.get(code)
        if city is None:
            return ()
        _, prefecture, primary = city
        for candidate in (primary, prefecture, primary[:3] + "000"):
            cells = self.by_area(candidate)
            if cells:
                return cells
        return ()


class _Value(NamedTuple):
    element: ForecastElement
    label: str
    ref_id: int | None
    text: str | None
    number: float | None
    condition: str
    description: str


def _number(value: float | Enum | None) -> float | None:
    # NullableintegerValue / NullablefloatValue stand for an empty element.
    return None if value is None or isinstance(value, Enum) else float(value)


def _element(type_name: str, label: str) -> ForecastElement:
    element = _ELEMENTS.get((type_name, label))
    if element is None:
        _LOGGER.warning("Unknown forecast element %r / %r", type_name, label)
        return ForecastElement.UNKNOWN
    return element


def _values(prop: TypeProperty1) -> Iterator[_Value]:
    name = prop.type_value
    found = False
    if prop.weather_part is not None:
        found = True
        for v in prop.weather_part.weather:
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                v.value or None,
                None,
                v.condition or "",
                v.description or "",
            )
    if prop.weather_code_part is not None:
        found = True
        for v in prop.weather_code_part.weather_code:
            number = _number(v.value)
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                None if number is None else str(int(number)),
                None,
                v.condition or "",
                v.description or "",
            )
    if prop.probability_of_precipitation_part is not None:
        found = True
        for v in prop.probability_of_precipitation_part.probability_of_precipitation:
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                None,
                _number(v.value),
                v.condition or "",
                v.description or "",
            )
    if prop.reliability_class_part is not None:
        found = True
        for v in prop.reliability_class_part.reliability_class:
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                v.value or None,
                None,
                v.condition or "",
                "",
            )
    if prop.temperature_part is not None:
        found = True
        for v in prop.temperature_part.temperature:
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                None,
                _number(v.value),
                v.condition or "",
                v.description or "",
            )
    if prop.wind_direction_part is not None:
        found = True
        for v in prop.wind_direction_part.wind_direction:
            yield _Value(
                _element(name, v.type_value),
                v.type_value,
                v.ref_id,
                v.value or None,
                None,
                v.condition or "",
                v.description or "",
            )
    if prop.wind_speed_part is not None:
        found = True
        for v in prop.wind_speed_part.wind_speed_level:
            label = v.type_value.value
            yield _Value(
                _element(name, label),
                label,
                v.ref_id,
                None,
                _number(v.value),
                "",
                v.description or "",
            )
    if prop.detail_forecast is not None:
        found = True
        detail = prop.detail_forecast
        sentences = (
            [(_E.WEATHER_DETAIL, part) for part in detail.weather_forecast_part]
            + [(_E.WIND, part) for part in detail.wind_forecast_part]
            + [(_E.WAVE, part) for part in detail.wave_height_forecast_part]
        )
        for element, part in sentences:
            text = part.sentence.value if part.sentence is not None else ""
            yield _Value(element, name, part.ref_id, text or None, None, "", "")
    if not found:
        _LOGGER.warning("Forecast property %r has no supported part", name)


def _series_cells(series: TypeTimeSeriesInfo) -> list[ForecastCell]:
    defines = periods(series)
    cells: list[ForecastCell] = []
    for item in series.item:
        if item.area is not None and item.area.code is not None:
            code, name, station = item.area.code, item.area.name, False
        elif item.station is not None and item.station.code:
            code, name, station = item.station.code[0].value, item.station.name, True
        else:
            raise ValueError("Forecast Item must have an Area/Code or a Station/Code")
        for prop in (prop for kind in item.kind for prop in kind.property):
            for value in _values(prop):
                period = defines.get(value.ref_id) if value.ref_id is not None else None
                if period is None:
                    raise ValueError(f"Forecast refID {value.ref_id} is undefined")
                start, duration, period_name = period
                cells.append(
                    ForecastCell(
                        code,
                        name,
                        station,
                        value.element,
                        value.label,
                        start,
                        duration,
                        period_name,
                        value.text,
                        value.number,
                        value.condition,
                        value.description,
                    )
                )
    return cells


def weather_forecast(report: Report) -> WeatherForecast:
    """Flatten a VPFD50, VPFD51 or VPFW50 report; Control/Status is not checked.

    The 7-day climatological precipitation thresholds (７日間平年値) are not time
    series and are skipped.
    """
    group = data_type_code(report)
    if group not in _GROUPS:
        raise ValueError(f"Not a weather forecast report: {report.control.title}")
    if not isinstance(report.body, MeteBody):
        raise ValueError("Weather forecast reports require a meteorological Body")
    cells = [
        cell
        for infos in report.body.meteorological_infos
        for series in infos.time_series_info
        for cell in _series_cells(series)
    ]
    return WeatherForecast(
        cast(Literal["VPFD50", "VPFD51", "VPFW50"], group),
        report.head.report_date_time,
        tuple(cells),
    )
