"""Asynchronous tracker with the same ordered processing as Tracker."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from types import TracebackType
from typing import Self

from ..codes import AreaName, Prefecture
from ..feed import (
    AsyncFeedClient,
    AsyncHttpClient,
    Entry,
    FeedError,
    FeedKind,
    HttpxAsyncHttpClient,
)
from ..state import Change
from ._core import Seen, TrackerCore, UpdateResult
from ._sync import utc_now


class AsyncTracker(TrackerCore):
    """Ordered asynchronous updates; injected HTTP transports remain caller-owned."""

    def __init__(
        self,
        areas: Iterable[AreaName] = (),
        *,
        prefectures: Iterable[Prefecture] = (),
        user_agent: str | None = None,
        http: AsyncHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(areas, prefectures)
        self._clock = clock if clock is not None else utc_now
        self._owned = HttpxAsyncHttpClient() if http is None else None
        transport = self._owned if self._owned is not None else http
        seen = {kind: Seen() for kind in (FeedKind.EXTRA, FeedKind.REGULAR, FeedKind.EQVOL)}
        self._seen = seen
        self._clients = {
            (kind, long): AsyncFeedClient(
                kind,
                long=long,
                user_agent=user_agent,
                http=transport,
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
        self._retry_long: list[tuple[FeedKind, AsyncFeedClient, Entry]] = []

    async def update(self) -> UpdateResult:
        changes: list[Change] = []
        errors: list[FeedError] = []
        applied = 0
        retry, self._retry_long = self._retry_long, []
        batches: list[tuple[FeedKind, AsyncFeedClient, bool, list[Entry] | None]] = [
            (kind, client, True, [entry]) for kind, client, entry in retry
        ]
        for kind, long in self._schedule():
            batches.append((kind, self._clients[kind, long], long, None))
        for kind, client, long, pending in batches:
            try:
                entries = await client.poll() if pending is None else pending
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
                    data = await client.fetch(entry)
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

    async def aclose(self) -> None:
        if self._owned is not None:
            await self._owned.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
