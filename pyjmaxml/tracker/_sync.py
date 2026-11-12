"""Synchronous tracker transport orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from ..codes import AreaName, Prefecture
from ..feed import Entry, FeedClient, FeedError, FeedKind, HttpClient
from ..state import Change
from ._core import Seen, TrackerCore, UpdateResult


def utc_now() -> datetime:
    return datetime.now(UTC)


class Tracker(TrackerCore):
    """Update watched warning areas on demand; call at intervals of at least 60s."""

    def __init__(
        self,
        areas: Iterable[AreaName] = (),
        *,
        prefectures: Iterable[Prefecture] = (),
        user_agent: str | None = None,
        http: HttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(areas, prefectures)
        self._clock = clock if clock is not None else utc_now
        seen = {kind: Seen() for kind in (FeedKind.EXTRA, FeedKind.REGULAR, FeedKind.EQVOL)}
        self._seen = seen
        self._clients = {
            (kind, long): FeedClient(
                kind,
                long=long,
                user_agent=user_agent,
                http=http,
                clock=self._clock,
                seen=seen[kind],
            )
            for kind, long in (
                (FeedKind.EXTRA, True),
                (FeedKind.REGULAR, True),
                (FeedKind.EXTRA, False),
                (FeedKind.REGULAR, False),
                (FeedKind.EQVOL, False),
            )
        }
        self._retry_long: list[tuple[FeedKind, FeedClient, Entry]] = []

    def update(self) -> UpdateResult:
        changes: list[Change] = []
        errors: list[FeedError] = []
        applied = 0
        retry, self._retry_long = self._retry_long, []
        batches: list[tuple[FeedKind, FeedClient, bool, list[Entry] | None]] = [
            (kind, client, True, [entry]) for kind, client, entry in retry
        ]
        for kind, long in self._schedule():
            client = self._clients[kind, long]
            # Poll lazily below so long entries are applied before short feeds.
            batches.append((kind, client, long, None))
        for kind, client, long, pending in batches:
            try:
                entries = client.poll() if pending is None else pending
            except FeedError as exc:
                if self._poll_failed(kind, long, exc):
                    errors.append(exc)
                continue
            if pending is None:
                self._polled(kind, long)
            for entry in entries:
                if pending is not None and entry.id in self._seen[kind]:
                    continue
                if not self._wants(kind, entry):
                    client.ack(entry)
                    continue
                try:
                    data = client.fetch(entry)
                except FeedError as exc:
                    errors.append(exc)
                    if long:
                        self._retry_long.append((kind, client, entry))
                    continue
                delta, count = self._consume(entry, data, self._clock())
                changes.extend(delta)
                applied += count
                client.ack(entry)
        return self._finish(changes, errors, applied, self._clock())
