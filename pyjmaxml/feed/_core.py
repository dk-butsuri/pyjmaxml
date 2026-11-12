"""JMA Atom feed processing without network, clock, or thread access."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Protocol
from xml.etree import ElementTree as ET

from .._version import __version__

_ATOM = "{http://www.w3.org/2005/Atom}"
_FEED_BASE = "https://www.data.jma.go.jp/developer/xml/feed/"
_USER_AGENT = f"pyjmaxml/{__version__}"
_LOGGER = logging.getLogger(__name__)


class FeedKind(StrEnum):
    REGULAR = "regular"
    EXTRA = "extra"
    EQVOL = "eqvol"
    OTHER = "other"


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    updated: datetime
    author: str
    url: str


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]

    def __post_init__(self) -> None:
        # A caller's mutable dictionary must not change an already-built request.
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class SeenStore(Protocol):
    """Storage for acknowledged IDs; contains also counts as use."""

    def __contains__(self, entry_id: str, /) -> bool: ...

    def add(self, entry_id: str, /) -> None: ...


class _LruSeenStore:
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


class FeedError(ValueError):
    """A feed or report request failed or its response cannot be processed."""


class FeedParseError(FeedError):
    """An Atom feed is malformed or missing entry metadata."""


class HttpStatusError(FeedError):
    """An HTTP status is not supported for the requested operation."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Unexpected HTTP status: {status}")


class FeedTransportError(FeedError):
    """No complete HTTP response arrived; the transport's exception is the cause.

    The bundled adapters raise it for connection, timeout and read failures, so
    callers need not know the HTTP library. HTTP error statuses are responses.
    """


class TooFrequentError(FeedError):
    """The next feed request would violate the configured minimum interval."""


def _require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("Feed timestamps must include a timezone")


def _text(element: ET.Element, name: str) -> str:
    value = element.findtext(_ATOM + name)
    if value is None or not value.strip():
        raise FeedParseError(f"Missing Atom {name}")
    return value.strip()


def _parse_entries(body: bytes) -> list[Entry]:
    try:
        root = ET.fromstring(body)
        if root.tag != _ATOM + "feed":
            raise FeedParseError("Expected an Atom feed root")
        entries: list[Entry] = []
        for node in root.findall(_ATOM + "entry"):
            updated = datetime.fromisoformat(_text(node, "updated"))
            _require_aware(updated)
            author = node.find(_ATOM + "author")
            if author is None:
                author = root.find(_ATOM + "author")
            if author is None:
                raise FeedParseError("Missing Atom author")
            # Atom's default link relation is alternate. Ignore self/related links.
            url = next(
                (
                    link.get("href")
                    for link in node.findall(_ATOM + "link")
                    if link.get("rel", "alternate") == "alternate"
                    and link.get("type", "application/xml") in {"application/xml", "text/xml"}
                    and link.get("href")
                ),
                None,
            )
            if url is None:
                raise FeedParseError("Missing Atom report link")
            entries.append(
                Entry(
                    id=_text(node, "id"),
                    title=_text(node, "title"),
                    updated=updated,
                    author=_text(author, "name"),
                    url=url,
                )
            )
        return entries
    except FeedParseError:
        raise
    except (ET.ParseError, ValueError) as exc:
        raise FeedParseError(f"Cannot parse Atom feed: {exc}") from exc


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def entry_response(response: HttpResponse) -> bytes:
    """Validate a fetched report response without interpreting the XML body."""
    if response.status != 200:
        raise HttpStatusError(response.status)
    return response.body


class FeedPoller:
    """Build requests and consume responses using only caller-supplied time.

    min_interval is in seconds. It is measured between next_request calls,
    including requests whose transport fails. There are no automatic retries.
    Instances are intended to process one sequence of requests and responses.
    """

    def __init__(
        self,
        kind: FeedKind,
        *,
        long: bool = False,
        seen: SeenStore | None = None,
        min_interval: float | None = None,
        unsafe_min_interval: bool = False,
        user_agent: str | None = None,
    ) -> None:
        default_interval = 3600 if long else 60
        interval = default_interval if min_interval is None else min_interval
        if not isfinite(interval) or interval < 0:
            raise ValueError("min_interval must be finite and nonnegative")
        if interval < default_interval and not unsafe_min_interval:
            raise ValueError("A shorter min_interval requires unsafe_min_interval=True")
        if user_agent == "":
            raise ValueError("user_agent must not be empty")
        suffix = "_l" if long else ""
        self._url = f"{_FEED_BASE}{kind.value}{suffix}.xml"
        self._min_interval = timedelta(seconds=interval)
        self._seen: SeenStore = seen if seen is not None else _LruSeenStore()
        self._pending: OrderedDict[str, Entry] = OrderedDict()
        self._user_agent = _USER_AGENT if user_agent is None else user_agent
        self._last_request_at: datetime | None = None
        self._etag: str | None = None
        self._last_modified: str | None = None

    def next_request(self, now: datetime) -> HttpRequest:
        """Reserve a poll attempt and return a conditional GET request."""
        _require_aware(now)
        if self._last_request_at is not None:
            if now - self._last_request_at < self._min_interval:
                raise TooFrequentError("Minimum feed polling interval has not elapsed")
        headers = self._headers()
        if self._etag is not None:
            headers["If-None-Match"] = self._etag
        if self._last_modified is not None:
            headers["If-Modified-Since"] = self._last_modified
        self._last_request_at = now
        return HttpRequest("GET", self._url, headers)

    def handle_response(self, resp: HttpResponse, now: datetime) -> list[Entry]:
        """Consume a feed response; invalid feeds do not update validators or IDs.

        now must be timezone-aware, as for next_request. Response completion
        does not reset the polling interval, which starts at request creation.
        """
        _require_aware(now)
        if resp.status == 304:
            self._etag = _header(resp.headers, "ETag") or self._etag
            self._last_modified = _header(resp.headers, "Last-Modified") or self._last_modified
            return self._pending_entries()
        if resp.status != 200:
            raise HttpStatusError(resp.status)
        # Parse the entire response before committing IDs or cache validators.
        entries = _parse_entries(resp.body)
        batch: dict[str, Entry] = {}
        for entry in entries:
            batch.setdefault(entry.id, entry)
        # JMA lists entries newest first. Queue them oldest first so that state
        # updates see every transition; ties keep the feed's relative age.
        for entry in sorted(reversed(batch.values()), key=lambda e: e.updated):
            if entry.id not in self._pending and entry.id not in self._seen:
                self._pending[entry.id] = entry
                if len(self._pending) > 1000:
                    dropped_id = self._pending_entries()[0].id
                    del self._pending[dropped_id]
                    _LOGGER.warning("Pending entry limit (1000) exceeded; dropped %s", dropped_id)
        # A new representation without a validator invalidates its old value.
        self._etag = _header(resp.headers, "ETag")
        self._last_modified = _header(resp.headers, "Last-Modified")
        return self._pending_entries()

    def _pending_entries(self) -> list[Entry]:
        # A later response may still reveal an older entry; the sort is stable.
        return sorted(self._pending.values(), key=lambda entry: entry.updated)

    def ack(self, entry: Entry | str) -> None:
        """Record processing success, even if the ID is not currently pending.

        Keep the entry pending if a user-provided seen store fails to record it.
        Repeated acknowledgements are safe and refresh the default seen LRU.
        """
        entry_id = entry.id if isinstance(entry, Entry) else entry
        self._seen.add(entry_id)
        self._pending.pop(entry_id, None)

    def entry_request(self, entry: Entry) -> HttpRequest:
        """Return an unconditional GET for a report, without feed validators."""
        return HttpRequest("GET", entry.url, self._headers())

    def _headers(self) -> dict[str, str]:
        # Both adapters can accept identity. Avoid negotiating encodings that
        # urllib does not decode; a gzip XML body can still be passed to parse.
        return {"User-Agent": self._user_agent, "Accept-Encoding": "identity"}
