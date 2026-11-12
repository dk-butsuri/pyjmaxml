"""HTTP adapters. Status interpretation belongs to the core.

Adapters return every HTTP response, including error statuses, and raise
FeedTransportError (with the library's exception as the cause) when no complete
response arrives.
"""

from __future__ import annotations

from http.client import HTTPException
from typing import TYPE_CHECKING, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ._core import FeedTransportError, HttpRequest, HttpResponse

if TYPE_CHECKING:
    import httpx


class HttpClient(Protocol):
    """A transport that returns HTTP responses, including non-success statuses."""

    def send(self, req: HttpRequest) -> HttpResponse: ...


class AsyncHttpClient(Protocol):
    """The asynchronous counterpart of HttpClient."""

    async def send(self, req: HttpRequest) -> HttpResponse: ...


def _transport_error(req: HttpRequest) -> FeedTransportError:
    return FeedTransportError(f"No HTTP response for {req.method} {req.url}")


class UrllibHttpClient:
    """Standard-library transport with a per-request timeout in seconds."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def send(self, req: HttpRequest) -> HttpResponse:
        request = Request(req.url, headers=dict(req.headers), method=req.method)
        try:
            try:
                with urlopen(request, timeout=self._timeout) as response:
                    return HttpResponse(
                        response.status, dict(response.headers.items()), response.read()
                    )
            except HTTPError as exc:
                # urllib raises HTTPError for 304 as well as 4xx/5xx. Pass every
                # HTTP response to the core.
                with exc:
                    return HttpResponse(exc.code, dict(exc.headers.items()), exc.read())
        # URLError and timeouts are OSError; a truncated body is IncompleteRead.
        except (OSError, HTTPException) as exc:
            raise _transport_error(req) from exc


class HttpxHttpClient:
    """Optional httpx transport; inject a Client to retain control of its lifetime.

    close() releases a client created by this adapter. Injected clients remain
    owned by their caller. Importing pyjmaxml.feed does not import httpx.
    """

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 30.0) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("HttpxHttpClient requires pyjmaxml[httpx]") from exc
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._request_error = httpx.RequestError

    def send(self, req: HttpRequest) -> HttpResponse:
        try:
            response = self._client.request(
                req.method, req.url, headers=req.headers, follow_redirects=True
            )
        except self._request_error as exc:
            raise _transport_error(req) from exc
        return HttpResponse(response.status_code, dict(response.headers), response.content)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class HttpxAsyncHttpClient:
    """Optional httpx AsyncClient transport with the same ownership rules.

    aclose() releases a client created by this adapter. Injected clients remain
    owned by their caller.
    """

    def __init__(self, client: httpx.AsyncClient | None = None, *, timeout: float = 30.0) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("HttpxAsyncHttpClient requires pyjmaxml[httpx]") from exc
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._request_error = httpx.RequestError

    async def send(self, req: HttpRequest) -> HttpResponse:
        try:
            response = await self._client.request(
                req.method, req.url, headers=req.headers, follow_redirects=True
            )
        except self._request_error as exc:
            raise _transport_error(req) from exc
        return HttpResponse(response.status_code, dict(response.headers), response.content)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
