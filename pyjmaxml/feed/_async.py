"""A thin asynchronous bridge between the poller, a clock, and a transport."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from ._core import Entry, FeedKind, FeedPoller, SeenStore, entry_response
from ._http import AsyncHttpClient, HttpxAsyncHttpClient


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AsyncFeedClient:
    """Poll and fetch with await; at most max_concurrency requests run at once.

    The limit keeps asyncio.gather over many entries polite to the JMA server.
    Without http, an HttpxAsyncHttpClient is created (pyjmaxml[httpx]) and closed
    by aclose() or async with; injected transports remain owned by the caller.
    Use one instance within one event loop. ack() is synchronous, as in FeedClient.
    """

    def __init__(
        self,
        kind: FeedKind,
        *,
        long: bool = False,
        http: AsyncHttpClient | None = None,
        seen: SeenStore | None = None,
        clock: Callable[[], datetime] | None = None,
        min_interval: float | None = None,
        unsafe_min_interval: bool = False,
        user_agent: str | None = None,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._poller = FeedPoller(
            kind,
            long=long,
            seen=seen,
            min_interval=min_interval,
            unsafe_min_interval=unsafe_min_interval,
            user_agent=user_agent,
        )
        self._owned: HttpxAsyncHttpClient | None = None
        if http is None:
            self._owned = HttpxAsyncHttpClient()
            http = self._owned
        self._http: AsyncHttpClient = http
        self._clock = clock if clock is not None else _utc_now
        self._limit = asyncio.Semaphore(max_concurrency)

    async def poll(self) -> list[Entry]:
        request = self._poller.next_request(self._clock())
        async with self._limit:
            response = await self._http.send(request)
        return self._poller.handle_response(response, self._clock())

    async def fetch(self, entry: Entry) -> bytes:
        request = self._poller.entry_request(entry)
        async with self._limit:
            response = await self._http.send(request)
        return entry_response(response)

    def ack(self, entry: Entry | str) -> None:
        self._poller.ack(entry)

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
