"""Warning forecast time series (気象警報・注意報時系列情報) from VPWP50."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import NamedTuple

from .._generated.jmx import (
    TypeHumidity,
    TypePrecipitation,
    TypeProperty1,
    TypeSignificancy,
    TypeSnowfallDepth,
    TypeTidalLevel,
    TypeTimeSeriesInfo,
    TypeWaveHeight,
    TypeWindDirection,
    TypeWindSpeed,
)
from ..kinds import data_type_code
from ..parse import MeteBody, Report
from ._time import periods
from .warning import Element

_LOGGER = logging.getLogger(__name__)
_ELEMENTS: dict[str, Element] = {
    "大雨浸水危険度": Element.HEAVY_RAIN,
    "雨": Element.HEAVY_RAIN,
    "土砂災害危険度": Element.LANDSLIDE,
    "風危険度": Element.STORM,
    "風": Element.STORM,
    "雪危険度": Element.HEAVY_SNOW,
    "雪": Element.HEAVY_SNOW,
    "波危険度": Element.HIGH_WAVE,
    "波": Element.HIGH_WAVE,
    "高潮危険度": Element.STORM_SURGE,
    "高潮": Element.STORM_SURGE,
    "雷危険度": Element.OTHER,
    "融雪危険度": Element.OTHER,
    "濃霧危険度": Element.OTHER,
    "着氷危険度": Element.OTHER,
    "着雪危険度": Element.OTHER,
    "乾燥危険度": Element.OTHER,
    "乾燥": Element.OTHER,
    "なだれ危険度": Element.OTHER,
    "低温危険度": Element.OTHER,
    "霜危険度": Element.OTHER,
}


@dataclass(frozen=True)
class WarningTimeSeriesCell:
    """One city, local subarea, value type and period."""

    area_code: str
    area_name: str
    local: str
    element: Element
    property: str
    label: str
    start: datetime
    duration: timedelta | None
    period_name: str
    code: str | None
    text: str | None
    number: float | None
    unit: str
    condition: str
    description: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class WarningTimeSeries:
    report_date_time: datetime
    cells: tuple[WarningTimeSeriesCell, ...]

    def by_city(self, code: str) -> tuple[WarningTimeSeriesCell, ...]:
        """Cells whose Area/Code equals the city code; no parent or fallback lookup."""
        return tuple(cell for cell in self.cells if cell.area_code == code)


_RawValue = (
    TypeSignificancy
    | TypePrecipitation
    | TypeSnowfallDepth
    | TypeWindDirection
    | TypeWindSpeed
    | TypeWaveHeight
    | TypeTidalLevel
    | TypeHumidity
)


class _Value(NamedTuple):
    local: str
    raw: _RawValue
    notes: tuple[str, ...]


def _number(value: float | Enum | None) -> float | None:
    # NullablefloatValue stands for an empty element.
    return None if value is None or isinstance(value, Enum) else float(value)


def _element(name: str) -> Element:
    element = _ELEMENTS.get(name)
    if element is None:
        _LOGGER.warning("Unknown warning time series type %r", name)
        return Element.UNKNOWN
    return element


def _located(
    values: Iterable[_RawValue],
    local_groups: Iterable[tuple[str | None, Iterable[_RawValue]]],
    notes: tuple[str, ...] = (),
) -> Iterator[_Value]:
    for value in values:
        yield _Value("", value, notes)
    for name, local_values in local_groups:
        for value in local_values:
            yield _Value(name or "", value, notes)


def _values(prop: TypeProperty1) -> Iterator[_Value]:
    # Follow the generated schema's Part order, preserving Local and value order.
    found = False
    for part in prop.significancy_part:
        found = True
        base = part.base
        notes = tuple(base.addition.note) if base.addition is not None else ()
        yield from _located(
            base.significancy,
            ((local.area_name, local.significancy) for local in base.local),
            notes,
        )
    if prop.wind_direction_part is not None:
        found = True
        direction = prop.wind_direction_part.base
        if direction is not None:
            yield from _located(
                direction.wind_direction,
                ((local.area_name, local.wind_direction) for local in direction.local),
            )
    if prop.wind_speed_part is not None:
        found = True
        speed = prop.wind_speed_part.base
        if speed is not None:
            yield from _located(
                speed.wind_speed,
                ((local.area_name, local.wind_speed) for local in speed.local),
            )
    if prop.wave_height_part is not None:
        found = True
        wave = prop.wave_height_part.base
        if wave is not None:
            yield from _located(
                wave.wave_height,
                ((local.area_name, local.wave_height) for local in wave.local),
            )
    for rain_part in prop.precipitation_part:
        found = True
        rain = rain_part.base
        if rain is not None:
            yield from _located(
                rain.precipitation,
                ((local.area_name, local.precipitation) for local in rain.local),
            )
    if prop.snowfall_depth_part is not None:
        found = True
        snow = prop.snowfall_depth_part.base
        if snow is not None:
            yield from _located(
                snow.snowfall_depth,
                ((local.area_name, local.snowfall_depth) for local in snow.local),
            )
    for humidity_part in prop.humidity_part:
        found = True
        humidity = humidity_part.base
        if humidity is not None:
            yield from _located(
                humidity.humidity,
                ((local.area_name, local.humidity) for local in humidity.local),
            )
    if prop.tidal_level_part is not None:
        found = True
        tide = prop.tidal_level_part.base
        if tide is not None:
            yield from _located(
                tide.tidal_level,
                ((local.area_name, local.tidal_level) for local in tide.local),
            )
    if not found:
        _LOGGER.warning("Warning time series property %r has no supported part", prop.type_value)


def _series_cells(series: TypeTimeSeriesInfo) -> list[WarningTimeSeriesCell]:
    defines = periods(series)
    cells: list[WarningTimeSeriesCell] = []
    for item in series.item:
        if item.area is None or item.area.code is None:
            raise ValueError("Warning time series Item must have an Area/Code")
        for prop in (prop for kind in item.kind for prop in kind.property):
            element = _element(prop.type_value)
            for value in _values(prop):
                raw = value.raw
                period = defines.get(raw.ref_id) if raw.ref_id is not None else None
                if period is None:
                    raise ValueError(f"Warning time series refID {raw.ref_id} is undefined")
                start, duration, period_name = period
                code: str | None = None
                text: str | None = None
                number: float | None = None
                unit, description = "", ""
                if isinstance(raw, TypeSignificancy):
                    code, text = raw.code, raw.name
                else:
                    unit, description = raw.unit or "", raw.description or ""
                    if isinstance(raw, TypeWindDirection):
                        text = raw.value or None
                    else:
                        number = _number(raw.value)
                cells.append(
                    WarningTimeSeriesCell(
                        item.area.code,
                        item.area.name,
                        value.local,
                        element,
                        prop.type_value,
                        raw.type_value,
                        start,
                        duration,
                        period_name,
                        code,
                        text,
                        number,
                        unit,
                        raw.condition or "",
                        description,
                        value.notes,
                    )
                )
    return cells


def warning_timeseries(report: Report) -> WarningTimeSeries:
    """Flatten a VPWP50 report; Control/Status is not checked."""
    if data_type_code(report) != "VPWP50":
        raise ValueError(f"Not a warning time series report: {report.control.title}")
    if not isinstance(report.body, MeteBody):
        raise ValueError("Warning time series reports require a meteorological Body")
    cells = [
        cell
        for infos in report.body.meteorological_infos
        for series in infos.time_series_info
        for cell in _series_cells(series)
    ]
    return WarningTimeSeries(report.head.report_date_time, tuple(cells))
