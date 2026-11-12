"""Tracker selection, normalization and snapshots, without transport or clocks."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from ..codes import AreaName, Prefecture
from ..codes._area_name import (
    AREA_CODE_BY_NAME,
    AREA_NAME_BY_CODE,
    AREAS_BY_PREFECTURE,
    PREFECTURE_CODE,
)
from ..feed import Entry, FeedError, FeedKind, TooFrequentError
from ..kinds import code_from_title, data_type_code
from ..normalize import (
    EarthquakeInfo,
    ForecastCell,
    PossibilityCell,
    WarningKind,
    WarningPossibility,
    WarningTimeSeries,
    WarningTimeSeriesCell,
    WeatherForecast,
    earthquake_info,
    warning_possibility,
    warning_timeseries,
    weather_forecast,
)
from ..parse import ParseError, parse
from ..state import Change, WarningState

_LOGGER = logging.getLogger(__name__)
_WARNINGS = frozenset(f"VPWW{n}" for n in range(55, 62))
_RIVERS = frozenset({"VXKO", "VXSU"})
_FORECAST = frozenset({"VPFD51", "VPFW50"})
_POSSIBILITY = frozenset({"VPFD60", "VPFD61", "VPFW60"})
_NORMALIZED = _FORECAST | _POSSIBILITY | {"VPWP50"}
_EARTHQUAKES = frozenset({"VXSE51", "VXSE52", "VXSE53"})
_GROUPS = {
    FeedKind.EXTRA: _WARNINGS | _RIVERS,
    FeedKind.REGULAR: _NORMALIZED | {"VPWS50"},
    FeedKind.EQVOL: _EARTHQUAKES,
}
_LONG = (FeedKind.EXTRA, FeedKind.REGULAR)
_SHORT = ((FeedKind.EXTRA, False), (FeedKind.REGULAR, False), (FeedKind.EQVOL, False))
_Cell = TypeVar("_Cell", covariant=True)


class _ByCity(Protocol[_Cell]):
    def by_city(self, code: str) -> tuple[_Cell, ...]: ...


@dataclass(frozen=True)
class UpdateResult:
    """Reports used and watched city changes; feed failures remain retryable."""

    changes: tuple[Change, ...]
    errors: tuple[FeedError, ...]
    applied: int


@dataclass(frozen=True)
class AreaView:
    """An immutable snapshot of one warning area."""

    name: AreaName
    code: str
    warnings: frozenset[WarningKind]
    forecast: tuple[ForecastCell, ...]
    weekly_forecast: tuple[ForecastCell, ...]
    possibility: tuple[PossibilityCell, ...]
    possibility_early: tuple[PossibilityCell, ...]
    possibility_weekly: tuple[PossibilityCell, ...]
    timeseries: tuple[WarningTimeSeriesCell, ...]


@dataclass(frozen=True)
class PrefectureView:
    """Snapshots of all warning areas in a requested prefecture."""

    name: Prefecture
    code: str
    areas: tuple[AreaView, ...]

    def area(self, name: AreaName) -> AreaView:
        for area in self.areas:
            if area.name == str(name):
                return area
        raise ValueError(f"Area is not in this prefecture: {name!r}")

    def warned(self) -> tuple[AreaView, ...]:
        return tuple(area for area in self.areas if area.warnings)


def _url_code(entry: Entry) -> str:
    match = re.search(r"_([0-9]{6})\.xml$", entry.url)
    if match is None:
        raise ValueError(f"Report URL has no six-digit area code: {entry.url!r}")
    return match[1]


def _by_city(results: Iterable[_ByCity[_Cell]], code: str) -> tuple[_Cell, ...]:
    for result in results:
        cells = result.by_city(code)
        if cells:
            return cells
    return ()


class TrackerCore:
    def __init__(self, areas: Iterable[AreaName], prefectures: Iterable[Prefecture]) -> None:
        names = set(areas)
        self._prefectures = frozenset(prefectures)
        for name in names:
            # `not in` would make pyright narrow every AreaName literal (about 6s).
            if AREA_CODE_BY_NAME.get(name) is None:
                raise ValueError(f"Unknown warning area: {name!r}")
        for prefecture in self._prefectures:
            if prefecture not in PREFECTURE_CODE:
                raise ValueError(f"Unknown prefecture: {prefecture!r}")
            names.update(AREAS_BY_PREFECTURE[prefecture])
        if not names:
            raise ValueError("Specify at least one area or prefecture")
        self._codes = frozenset(AREA_CODE_BY_NAME[name] for name in names)
        self._areas: tuple[AreaName, ...] = tuple(
            AREA_NAME_BY_CODE[code] for code in sorted(self._codes)
        )
        self._prefixes = frozenset(code[:2] for code in self._codes)
        self._warning_state = WarningState()
        self._forecasts: dict[str, dict[str, tuple[datetime, WeatherForecast]]] = {}
        self._possibilities: dict[str, dict[str, tuple[datetime, WarningPossibility]]] = {}
        self._timeseries: dict[str, tuple[datetime, WarningTimeSeries]] = {}
        self._earthquake: EarthquakeInfo | None = None
        self._earthquake_at: datetime | None = None
        self._updated_at: datetime | None = None
        # Long feeds stay scheduled until one poll succeeds, e.g. after an offline start.
        self._long_pending = set(_LONG)
        self._long_attempted: set[FeedKind] = set()

    @property
    def areas(self) -> tuple[AreaName, ...]:
        return self._areas

    @property
    def warning_state(self) -> WarningState:
        return self._warning_state

    @property
    def earthquake(self) -> EarthquakeInfo | None:
        return self._earthquake

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    def area(self, name: AreaName) -> AreaView:
        code = AREA_CODE_BY_NAME.get(name)
        if code is None or code not in self._codes:
            raise ValueError(f"Area is not watched: {name!r}")
        return AreaView(
            name,
            code,
            self._warning_state.by_city(code),
            _by_city((v for _, v in self._forecasts.get("VPFD51", {}).values()), code),
            _by_city((v for _, v in self._forecasts.get("VPFW50", {}).values()), code),
            _by_city((v for _, v in self._possibilities.get("VPFD60", {}).values()), code),
            _by_city((v for _, v in self._possibilities.get("VPFD61", {}).values()), code),
            _by_city((v for _, v in self._possibilities.get("VPFW60", {}).values()), code),
            _by_city((v for _, v in self._timeseries.values()), code),
        )

    def prefecture(self, name: Prefecture) -> PrefectureView:
        if name not in self._prefectures:
            raise ValueError(f"Prefecture is not watched as a whole: {name!r}")
        return PrefectureView(
            name,
            PREFECTURE_CODE[name],
            tuple(self.area(area) for area in AREAS_BY_PREFECTURE[name]),
        )

    def _schedule(self) -> tuple[tuple[FeedKind, bool], ...]:
        long = tuple((kind, True) for kind in _LONG if kind in self._long_pending)
        return (*long, *_SHORT)

    def _polled(self, kind: FeedKind, long: bool) -> None:
        if long:
            self._long_pending.discard(kind)

    def _poll_failed(self, kind: FeedKind, long: bool, error: FeedError) -> bool:
        """Record a poll attempt; False hides an expected wait before a long-feed retry."""
        if not long:
            return True
        retrying = kind in self._long_attempted
        self._long_attempted.add(kind)
        return not (retrying and isinstance(error, TooFrequentError))

    def _wants(self, kind: FeedKind, entry: Entry) -> bool:
        group = code_from_title(entry.title)
        if group not in _GROUPS[kind]:
            return False
        return group not in _WARNINGS | _NORMALIZED or _url_code(entry)[:2] in self._prefixes

    def _consume(self, entry: Entry, data: bytes, now: datetime) -> tuple[tuple[Change, ...], int]:
        try:
            report = parse(data)
        except ParseError:
            _LOGGER.exception("Cannot parse report; acknowledging: %s", entry.id)
            return (), 0
        if report.control.status != "通常":
            return (), 0
        group = data_type_code(report)
        at = report.control.date_time
        try:
            if group in _WARNINGS | _RIVERS | {"VPWS50"}:
                result = self._warning_state.apply(report, now=now)
                return tuple(
                    c for c in result.changes if c.scope == "city" and c.area in self._codes
                ), int(result.applied)
            if group in _EARTHQUAKES:
                if self._earthquake_at is not None and at < self._earthquake_at:
                    return (), 0
                value = earthquake_info(report)
                self._earthquake, self._earthquake_at = value, at
                return (), 1
            code = _url_code(entry)
            if group is not None and group in _FORECAST:
                forecasts = self._forecasts.setdefault(group, {})
                if code in forecasts and at < forecasts[code][0]:
                    return (), 0
                forecast = weather_forecast(report)
                forecasts[code] = (at, forecast)
            elif group is not None and group in _POSSIBILITY:
                possibilities = self._possibilities.setdefault(group, {})
                if code in possibilities and at < possibilities[code][0]:
                    return (), 0
                possibility = warning_possibility(report)
                possibilities[code] = (at, possibility)
            elif group == "VPWP50":
                if code in self._timeseries and at < self._timeseries[code][0]:
                    return (), 0
                timeseries = warning_timeseries(report)
                self._timeseries[code] = (at, timeseries)
            else:
                return (), 0
        except ValueError:
            _LOGGER.exception("Cannot apply report; acknowledging: %s", entry.id)
            return (), 0
        return (), 1

    def _finish(
        self, changes: list[Change], errors: list[FeedError], applied: int, now: datetime
    ) -> UpdateResult:
        self._updated_at = now.astimezone(UTC)
        return UpdateResult(tuple(changes), tuple(errors), applied)


class Seen:
    """Bounded acknowledgements shared by a kind's long and short clients."""

    def __init__(self) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()

    def __contains__(self, entry_id: str, /) -> bool:
        if entry_id not in self._ids:
            return False
        self._ids.move_to_end(entry_id)
        return True

    def add(self, entry_id: str, /) -> None:
        self._ids[entry_id] = None
        self._ids.move_to_end(entry_id)
        if len(self._ids) > 10_000:
            self._ids.popitem(last=False)
