"""JMA Atom feeds: a sans-IO poller and interchangeable synchronous transports."""

from ._core import (
    Entry,
    FeedError,
    FeedKind,
    FeedParseError,
    FeedPoller,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    SeenStore,
    TooFrequentError,
)
from ._http import HttpClient, HttpxHttpClient, UrllibHttpClient
from ._sync import FeedClient

__all__ = [
    "Entry",
    "FeedClient",
    "FeedError",
    "FeedKind",
    "FeedParseError",
    "FeedPoller",
    "HttpClient",
    "HttpRequest",
    "HttpResponse",
    "HttpStatusError",
    "HttpxHttpClient",
    "SeenStore",
    "TooFrequentError",
    "UrllibHttpClient",
]
