"""A thin synchronous bridge between the poller, a clock, and a transport."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ._core import Entry, FeedKind, FeedPoller, SeenStore, entry_response
from ._http import HttpClient, UrllibHttpClient


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FeedClient:
    """Poll and fetch synchronously. Inject http and clock for offline operation."""

    def __init__(
        self,
        kind: FeedKind,
        *,
        long: bool = False,
        http: HttpClient | None = None,
        seen: SeenStore | None = None,
        clock: Callable[[], datetime] | None = None,
        min_interval: float | None = None,
        unsafe_min_interval: bool = False,
        user_agent: str | None = None,
    ) -> None:
        self._poller = FeedPoller(
            kind,
            long=long,
            seen=seen,
            min_interval=min_interval,
            unsafe_min_interval=unsafe_min_interval,
            user_agent=user_agent,
        )
        self._http = http if http is not None else UrllibHttpClient()
        self._clock = clock if clock is not None else _utc_now

    def poll(self) -> list[Entry]:
        request = self._poller.next_request(self._clock())
        response = self._http.send(request)
        return self._poller.handle_response(response, self._clock())

    def fetch(self, entry: Entry) -> bytes:
        request = self._poller.entry_request(entry)
        return entry_response(self._http.send(request))

    def ack(self, entry: Entry | str) -> None:
        self._poller.ack(entry)
