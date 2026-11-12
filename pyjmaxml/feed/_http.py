"""Synchronous HTTP adapters. Status interpretation belongs to the core."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ._core import HttpRequest, HttpResponse

if TYPE_CHECKING:
    import httpx


class HttpClient(Protocol):
    """A transport that returns HTTP responses, including non-success statuses."""

    def send(self, req: HttpRequest) -> HttpResponse: ...


class UrllibHttpClient:
    """Standard-library transport with a per-request timeout in seconds."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def send(self, req: HttpRequest) -> HttpResponse:
        request = Request(req.url, headers=dict(req.headers), method=req.method)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return HttpResponse(
                    response.status, dict(response.headers.items()), response.read()
                )
        except HTTPError as exc:
            # urllib raises HTTPError for 304 as well as 4xx/5xx. Pass every
            # HTTP response to the core while letting transport failures escape.
            with exc:
                return HttpResponse(exc.code, dict(exc.headers.items()), exc.read())


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

    def send(self, req: HttpRequest) -> HttpResponse:
        response = self._client.request(
            req.method, req.url, headers=req.headers, follow_redirects=True
        )
        return HttpResponse(response.status_code, dict(response.headers), response.content)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
