"""JMA Atom feeds: a sans-IO poller with synchronous and asynchronous clients."""

from ._async import AsyncFeedClient
from ._core import (
    Entry,
    FeedError,
    FeedKind,
    FeedParseError,
    FeedPoller,
    FeedTransportError,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    SeenStore,
    TooFrequentError,
)
from ._http import (
    AsyncHttpClient,
    HttpClient,
    HttpxAsyncHttpClient,
    HttpxHttpClient,
    UrllibHttpClient,
)
from ._sync import FeedClient

__all__ = [
    "AsyncFeedClient",
    "AsyncHttpClient",
    "Entry",
    "FeedClient",
    "FeedError",
    "FeedKind",
    "FeedParseError",
    "FeedPoller",
    "FeedTransportError",
    "HttpClient",
    "HttpRequest",
    "HttpResponse",
    "HttpStatusError",
    "HttpxAsyncHttpClient",
    "HttpxHttpClient",
    "SeenStore",
    "TooFrequentError",
    "UrllibHttpClient",
]
