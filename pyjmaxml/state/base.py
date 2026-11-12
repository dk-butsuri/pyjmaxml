"""Common state API, change records, and telegram ordering bookkeeping."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, Self, TypeAlias

from ..normalize import WarningKind
from ..parse import Report

__all__ = ["ApplyResult", "Change", "ChangeType", "SkipReason", "State"]


class SkipReason(StrEnum):
    STATUS = "status"
    UNSUPPORTED = "unsupported"
    DUPLICATE = "duplicate"
    STALE = "stale"
    # Optional time bounds recommended by the JMA operation guide §2.1.3.6.
    TOO_OLD = "too_old"
    FUTURE = "future"


class ChangeType(StrEnum):
    ISSUED = "ISSUED"
    UPGRADED = "UPGRADED"
    DOWNGRADED = "DOWNGRADED"
    CHANGED = "CHANGED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Change:
    scope: Literal["city", "river"]
    area: str
    group: str
    type: ChangeType
    before: frozenset[WarningKind]
    after: frozenset[WarningKind]
    at: datetime


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    skip_reason: SkipReason | None
    changes: tuple[Change, ...]


class State(Protocol):
    """An I/O-free state machine that can persist its processing history."""

    def apply(
        self,
        report: Report,
        *,
        now: datetime | None = None,
        max_age: timedelta | None = timedelta(hours=24),
        max_future: timedelta | None = timedelta(minutes=10),
    ) -> ApplyResult: ...

    def to_json(self) -> str: ...

    @classmethod
    def from_json(cls, s: str) -> Self: ...


_InformationKey: TypeAlias = tuple[str, str, str, str]
_TelegramKey: TypeAlias = tuple[str, str, str, str, datetime, str, str]


def _information_key(report: Report) -> _InformationKey:
    control = report.control
    return (control.title, control.editorial_office, control.status, report.head.event_id)


def _telegram_key(report: Report) -> _TelegramKey:
    return (
        *_information_key(report),
        report.control.date_time,
        report.head.info_type,
        report.head.serial,
    )


class Ledger:
    def __init__(self, accept_status: Iterable[str]) -> None:
        self.accept_status: frozenset[str] = frozenset(accept_status)
        self.seen: OrderedDict[_TelegramKey, None] = OrderedDict()
        self.latest: dict[_InformationKey, datetime] = {}
        self.last_updated: datetime | None = None

    def skip_reason(
        self, report: Report, group: str | None, supported: Collection[str]
    ) -> SkipReason | None:
        if report.control.status not in self.accept_status:
            return SkipReason.STATUS
        if group not in supported:
            return SkipReason.UNSUPPORTED
        if _telegram_key(report) in self.seen:
            return SkipReason.DUPLICATE
        latest = self.latest.get(_information_key(report))
        if latest is not None and report.control.date_time <= latest:
            return SkipReason.STALE
        return None

    def remember_seen(self, key: _TelegramKey) -> None:
        self.seen[key] = None
        if len(self.seen) > 10_000:
            self.seen.popitem(last=False)

    def commit(self, report: Report) -> None:
        self.remember_seen(_telegram_key(report))
        self.latest[_information_key(report)] = report.control.date_time
        # This is the last applied report's timestamp, not a global maximum.
        self.last_updated = report.control.date_time
