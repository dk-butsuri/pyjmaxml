"""Warning-level possibility (警報級の可能性) from VPFD60, VPFD61 and VPFW60."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Literal, cast

from .._generated.jmx import TypeTimeSeriesInfo
from ..codes import AREA_CITY
from ..kinds import data_type_code
from ..parse import MeteBody, Report
from ._time import periods
from .warning import Element

_LOGGER = logging.getLogger(__name__)
_GROUPS = frozenset({"VPFD60", "VPFD61", "VPFW60"})
_SUFFIX = "の警報級の可能性"
# Property/Type prefixes seen in the 2026 telegrams and the pinned samples.
# 雨 (VPFD60/VPFW60) and 大雨 (VPFD61) both refer to the heavy-rain warning;
# 風（風雪） covers both storm and snowstorm warnings.
_ELEMENTS: dict[str, Element] = {
    "雨": Element.HEAVY_RAIN,
    "大雨": Element.HEAVY_RAIN,
    "土砂災害": Element.LANDSLIDE,
    "雪": Element.HEAVY_SNOW,
    "風（風雪）": Element.STORM,
    "波": Element.HIGH_WAVE,
    "潮位": Element.STORM_SURGE,
}


class Possibility(IntEnum):
    NONE = 0
    MEDIUM = 1
    HIGH = 2


# 'なし' is a value; '値なし' arrives as condition with an empty value.
_RANKS = {"高": Possibility.HIGH, "中": Possibility.MEDIUM, "なし": Possibility.NONE}


@dataclass(frozen=True)
class PossibilityCell:
    """One area, element and period; raw keeps the value or the condition text."""

    area_code: str
    area_name: str
    element: Element
    name: str
    start: datetime
    duration: timedelta | None
    period_name: str
    possibility: Possibility | None
    raw: str


@dataclass(frozen=True)
class WarningPossibility:
    group: Literal["VPFD60", "VPFD61", "VPFW60"]
    report_date_time: datetime
    cells: tuple[PossibilityCell, ...]

    def by_area(self, code: str) -> tuple[PossibilityCell, ...]:
        """Cells for a primary subdivision code (一次細分区域, e.g. 130010)."""
        return tuple(cell for cell in self.cells if cell.area_code == code)

    def by_city(self, code: str) -> tuple[PossibilityCell, ...]:
        """Cells for the primary subdivision of a city code; unknown cities match nothing."""
        city = AREA_CITY.get(code)
        return () if city is None else self.by_area(city[2])


def _element(name: str) -> Element:
    element = _ELEMENTS.get(name.removesuffix(_SUFFIX)) if name.endswith(_SUFFIX) else None
    if element is None:
        _LOGGER.warning("Unknown warning possibility type %r", name)
        return Element.UNKNOWN
    return element


def _possibility(value: str, condition: str | None) -> Possibility | None:
    if value == "" and condition == "値なし":
        return Possibility.NONE
    rank = _RANKS.get(value)
    if rank is None:
        _LOGGER.warning("Unknown warning possibility value %r (condition %r)", value, condition)
    return rank


def _series_cells(series: TypeTimeSeriesInfo) -> list[PossibilityCell]:
    defines = periods(series)
    cells: list[PossibilityCell] = []
    for item in series.item:
        if item.area is None or item.area.code is None:
            raise ValueError("Warning possibility Item must have an Area/Code")
        for prop in (prop for kind in item.kind for prop in kind.property):
            part = prop.possibility_rank_of_warning_part
            if part is None:
                continue
            element = _element(prop.type_value)
            for rank in part.possibility_rank_of_warning:
                period = defines.get(rank.ref_id) if rank.ref_id is not None else None
                if period is None:
                    raise ValueError(f"PossibilityRankOfWarning refID {rank.ref_id} is undefined")
                start, duration, period_name = period
                cells.append(
                    PossibilityCell(
                        item.area.code,
                        item.area.name,
                        element,
                        prop.type_value,
                        start,
                        duration,
                        period_name,
                        _possibility(rank.value, rank.condition),
                        rank.value or rank.condition or "",
                    )
                )
    return cells


def warning_possibility(report: Report) -> WarningPossibility:
    """Flatten a VPFD60, VPFD61 or VPFW60 report; Control/Status is not checked."""
    group = data_type_code(report)
    if group not in _GROUPS:
        raise ValueError(f"Not a warning possibility report: {report.control.title}")
    if not isinstance(report.body, MeteBody):
        raise ValueError("Warning possibility reports require a meteorological Body")
    cells = [
        cell
        for infos in report.body.meteorological_infos
        for series in infos.time_series_info
        for cell in _series_cells(series)
    ]
    return WarningPossibility(
        cast(Literal["VPFD60", "VPFD61", "VPFW60"], group),
        report.head.report_date_time,
        tuple(cells),
    )
