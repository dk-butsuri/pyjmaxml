"""Weather cells and river warnings, updated according to implementation plan §3."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Self, cast

from .._generated.jmx import TypeArea1, TypeItem1, TypeKind1
from ..codes import AREA_CITY_PARENT
from ..kinds import data_type_code
from ..normalize import Predicate, WarningKind, classify_flood, classify_mete, rank
from ..parse import MeteBody, Report
from .base import ApplyResult, Change, ChangeType
from .base import Ledger as _Ledger

_MUNICIPAL = "気象警報・注意報（市町村等）"
_METE_GROUPS = frozenset(f"VPWW{number}" for number in range(55, 62))
_RIVER_INFO = {
    "VXKO": "指定河川洪水予報（予報区域）",
    "VXSU": "水位周知河川に関する情報（発表区間）",
}
_SUPPORTED = _METE_GROUPS | {"VPWS50"} | _RIVER_INFO.keys()
_INACTIVE = frozenset({"解除", "発表警報・注意報はなし"})


@dataclass(frozen=True)
class Cell:
    kinds: frozenset[WarningKind]
    as_of: datetime


@dataclass(frozen=True)
class River:
    group: Literal["VXKO", "VXSU"]
    kinds: frozenset[WarningKind]
    cities: frozenset[str]
    as_of: datetime


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("State timestamps must include a timezone")
    return value


def _active(kind: TypeKind1) -> bool:
    return kind.status not in _INACTIVE


def _mete_kind(kind: TypeKind1) -> WarningKind:
    if kind.code is None:
        raise ValueError("An active meteorological Kind must have a Code")
    return classify_mete(kind.code, kind.name or "")


def _city_codes(value: object) -> set[str]:
    """Find generated CityCode elements anywhere in a meteorological Body.

    CityCode is a field of TypeArea1. Traverse dataclass children and lists,
    rather than inferring cities from generic Area/Code or SubCityCode fields.
    """
    result: set[str] = set()
    if isinstance(value, TypeArea1) and value.city_code is not None:
        result.add(value.city_code)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            result.update(_city_codes(getattr(value, field.name)))
    elif isinstance(value, list):
        for child in cast(list[object], value):
            result.update(_city_codes(child))
    return result


def _change(
    scope: Literal["city", "river"],
    area: str,
    group: str,
    before: frozenset[WarningKind],
    after: frozenset[WarningKind],
    at: datetime,
) -> Change | None:
    if {(kind.name, kind.code) for kind in before} == {(kind.name, kind.code) for kind in after}:
        return None
    if not before:
        change_type = ChangeType.ISSUED
    elif not after:
        change_type = ChangeType.CANCELLED
    else:
        old_rank, new_rank = max(map(rank, before)), max(map(rank, after))
        change_type = (
            ChangeType.UPGRADED
            if new_rank > old_rank
            else ChangeType.DOWNGRADED
            if new_rank < old_rank
            else ChangeType.CHANGED
        )
    return Change(scope, area, group, change_type, before, after, at)


class WarningState:
    """Track supported city and river warnings without I/O or a system clock."""

    def __init__(self, *, accept_status: Iterable[str] = ("通常",)) -> None:
        self._ledger = _Ledger(accept_status)
        self._cells: dict[tuple[str, str], Cell] = {}
        self._rivers: dict[str, River] = {}

    @property
    def last_updated(self) -> datetime | None:
        return self._ledger.last_updated

    def apply(self, report: Report) -> ApplyResult:
        """Apply one report, with skip precedence and separate cell watermarks."""
        group = data_type_code(report)
        reason = self._ledger.skip_reason(report, group, _SUPPORTED)
        if reason is not None:
            return ApplyResult(False, reason, ())
        assert group is not None
        _aware(report.control.date_time)
        _aware(report.head.report_date_time)
        # Prepare updates before mutating the state or committing the ledger.
        cell_updates: dict[tuple[str, str], Cell] = {}
        river_updates: dict[str, River | None] = {}
        if group in _RIVER_INFO:
            river_updates[report.head.event_id] = self._river_update(report, group)
        else:
            cell_updates = self._weather_updates(report, group)
        changes: list[Change] = []
        for (city, cell_group), cell in cell_updates.items():
            previous = self._cells.get((city, cell_group))
            change = _change(
                "city",
                city,
                cell_group,
                previous.kinds if previous else frozenset(),
                cell.kinds,
                cell.as_of,
            )
            if change is not None:
                changes.append(change)
        for event_id, river in river_updates.items():
            previous_river = self._rivers.get(event_id)
            change = _change(
                "river",
                event_id,
                group,
                previous_river.kinds if previous_river else frozenset(),
                river.kinds if river else frozenset(),
                river.as_of if river else report.head.report_date_time,
            )
            if change is not None:
                changes.append(change)
        self._cells.update(cell_updates)
        for event_id, river in river_updates.items():
            if river is None:
                self._rivers.pop(event_id, None)
            else:
                self._rivers[event_id] = river
        self._ledger.commit(report)
        changes.sort(key=lambda change: (change.scope, change.area, change.group))
        return ApplyResult(True, None, tuple(changes))

    def _weather_updates(self, report: Report, group: str) -> dict[tuple[str, str], Cell]:
        if not isinstance(report.body, MeteBody):
            raise ValueError("Weather reports require a meteorological Body")
        warnings = [warning for warning in report.body.warning if warning.type_value == _MUNICIPAL]
        items = [item for warning in warnings for item in warning.item]
        updates: dict[tuple[str, str], Cell] = {}
        if group != "VPWS50":
            at = report.head.report_date_time
            for item in items:
                if item.area is None or item.area.code is None:
                    raise ValueError("Municipal warning Item must have an Area/Code")
                key = (item.area.code, group)
                previous = self._cells.get(key)
                if previous is None or at >= previous.as_of:
                    updates[key] = Cell(
                        frozenset(_mete_kind(k) for k in item.kind if _active(k)), at
                    )
            return updates
        if not warnings:
            at = report.head.report_date_time
            return {
                key: Cell(frozenset(), at) for key, cell in self._cells.items() if cell.as_of <= at
            }
        # W is global across all Kind/DateTime entries in this report.
        dates = [
            _aware(kind.date_time.value.to_datetime())
            for warning in report.body.warning
            for item in warning.item
            for kind in item.kind
            if kind.date_time is not None
        ]
        if not dates:
            raise ValueError("VPWS50 municipal warnings have no Kind/DateTime watermark")
        watermark = max(dates)
        for item in items:
            updates.update(self._snapshot_item(item, watermark))
        return updates

    def _snapshot_item(self, item: TypeItem1, watermark: datetime) -> dict[tuple[str, str], Cell]:
        if item.area is None or item.area.code is None:
            raise ValueError("Municipal warning Item must have an Area/Code")
        city = item.area.code
        kinds: dict[str, set[WarningKind]] = {}
        dates: dict[str, datetime] = {}
        for raw_kind in item.kind:
            if not _active(raw_kind):
                continue
            kind = _mete_kind(raw_kind)
            if raw_kind.date_time is None:
                raise ValueError("Active VPWS50 Kind must have a DateTime")
            at = _aware(raw_kind.date_time.value.to_datetime())
            kinds.setdefault(kind.group, set()).add(kind)
            dates[kind.group] = max(dates.get(kind.group, at), at)
        updates: dict[tuple[str, str], Cell] = {}
        for group, active in kinds.items():
            key = (city, group)
            previous = self._cells.get(key)
            if previous is None or dates[group] >= previous.as_of:
                updates[key] = Cell(frozenset(active), dates[group])
        for key, cell in self._cells.items():
            if key[0] == city and key[1] not in kinds and cell.as_of <= watermark:
                updates[key] = Cell(frozenset(), watermark)
        return updates

    def _river_update(self, report: Report, group: str) -> River | None:
        if report.head.info_type == "取消":
            return None
        kinds = [
            kind
            for info in report.raw.head.headline.information
            if info.type_value == _RIVER_INFO[group]
            for item in info.item
            for kind in item.kind
        ]
        if len(kinds) != 1 or kinds[0].code is None:
            raise ValueError("River report must have one coded headline Kind")
        raw_kind = kinds[0]
        if raw_kind.code == "10":
            return None
        if not isinstance(report.body, MeteBody):
            raise ValueError("River reports require a meteorological Body")
        assert raw_kind.code is not None
        return River(
            cast(Literal["VXKO", "VXSU"], group),
            frozenset({classify_flood(raw_kind.code, raw_kind.name, group)}),
            frozenset(_city_codes(report.body)),
            report.head.report_date_time,
        )

    def by_city(self, code: str) -> frozenset[WarningKind]:
        """Union exact weather cells with river coverage for this code or its parent."""
        result = {
            kind for (city, _), cell in self._cells.items() if city == code for kind in cell.kinds
        }
        parent = AREA_CITY_PARENT.get(code)
        for river in self._rivers.values():
            if code in river.cities or parent in river.cities:
                result.update(river.kinds)
        return frozenset(result)

    def cities(self, pred: Predicate | None = None) -> Mapping[str, frozenset[WarningKind]]:
        """Return nonempty city selections, including subdivisions covered by rivers."""
        river_cities = {city for river in self._rivers.values() for city in river.cities}
        codes = {city for city, _ in self._cells} | river_cities
        codes.update(child for child, parent in AREA_CITY_PARENT.items() if parent in river_cities)
        result: dict[str, frozenset[WarningKind]] = {}
        for code in sorted(codes):
            kinds = self.by_city(code)
            if pred is not None:
                kinds = frozenset(kind for kind in kinds if pred(kind))
            if kinds:
                result[code] = kinds
        return MappingProxyType(result)

    def rivers(self) -> Mapping[str, River]:
        """Return a read-only snapshot of river state."""
        return MappingProxyType(dict(sorted(self._rivers.items())))

    def to_json(self) -> str:
        """Serialize cells, rivers, accepted statuses, and processing history as version 1."""
        payload = {
            "version": 1,
            "accept_status": sorted(self._ledger.accept_status),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "cells": [
                {
                    "city": city,
                    "group": group,
                    "as_of": cell.as_of.isoformat(),
                    "kinds": _save_kinds(cell.kinds),
                }
                for (city, group), cell in sorted(self._cells.items())
            ],
            "rivers": [
                {
                    "event_id": event,
                    "group": river.group,
                    "as_of": river.as_of.isoformat(),
                    "cities": sorted(river.cities),
                    "kinds": _save_kinds(river.kinds),
                }
                for event, river in sorted(self._rivers.items())
            ],
            "seen": [[*key[:4], key[4].isoformat(), key[5], key[6]] for key in self._ledger.seen],
            "latest": [
                {"key": list(key), "at": at.isoformat()}
                for key, at in sorted(self._ledger.latest.items())
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, s: str) -> Self:
        """Restore version 1; warning metadata is reclassified from name/code/group."""
        value: object = json.loads(s)
        data = _object(value)
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported WarningState JSON version")
        try:
            state = cls(accept_status=[_string(v) for v in _array(data["accept_status"])])
            last = data["last_updated"]
            state._ledger.last_updated = None if last is None else _time(last)
            for value in _array(data["cells"]):
                record = _object(value)
                key = (_string(record["city"]), _string(record["group"]))
                state._cells[key] = Cell(_load_kinds(record["kinds"]), _time(record["as_of"]))
            for value in _array(data["rivers"]):
                record = _object(value)
                group = _string(record["group"])
                if group not in _RIVER_INFO:
                    raise ValueError("Invalid river group in state JSON")
                state._rivers[_string(record["event_id"])] = River(
                    cast(Literal["VXKO", "VXSU"], group),
                    _load_kinds(record["kinds"]),
                    frozenset(_string(v) for v in _array(record["cities"])),
                    _time(record["as_of"]),
                )
            for value in _array(data["seen"]):
                record = _array(value)
                if len(record) != 7:
                    raise ValueError("Invalid telegram key in state JSON")
                state._ledger.remember_seen(
                    (
                        _string(record[0]),
                        _string(record[1]),
                        _string(record[2]),
                        _string(record[3]),
                        _time(record[4]),
                        _string(record[5]),
                        _string(record[6]),
                    )
                )
            for value in _array(data["latest"]):
                record = _object(value)
                key = _array(record["key"])
                if len(key) != 4:
                    raise ValueError("Invalid information key in state JSON")
                state._ledger.latest[
                    (_string(key[0]), _string(key[1]), _string(key[2]), _string(key[3]))
                ] = _time(record["at"])
            return state
        except KeyError as exc:
            raise ValueError(f"Missing state JSON field: {exc}") from exc


def _save_kinds(kinds: frozenset[WarningKind]) -> list[dict[str, str]]:
    return [
        {"name": kind.name, "code": kind.code, "group": kind.group}
        for kind in sorted(kinds, key=lambda k: (k.group, k.code, k.name))
    ]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return cast(list[object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a JSON string")
    return value


def _time(value: object) -> datetime:
    return _aware(datetime.fromisoformat(_string(value)))


def _load_kinds(value: object) -> frozenset[WarningKind]:
    result: set[WarningKind] = set()
    for entry in _array(value):
        record = _object(entry)
        name, code, group = (
            _string(record["name"]),
            _string(record["code"]),
            _string(record["group"]),
        )
        result.add(
            classify_flood(code, name, group) if group in _RIVER_INFO else classify_mete(code, name)
        )
    return frozenset(result)
