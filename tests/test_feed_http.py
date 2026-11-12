import sys
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from pyjmaxml.feed import (
    FeedClient,
    FeedKind,
    HttpRequest,
    HttpResponse,
    HttpxHttpClient,
    UrllibHttpClient,
)

REQUEST = HttpRequest(
    "GET",
    "https://example.test/feed.xml",
    {"User-Agent": "pyjmaxml/test", "If-None-Match": 'W/"cached"'},
)


def test_urllib_adapts_request_and_closes_response(monkeypatch):
    class Response(BytesIO):
        status = 200

        def __init__(self):
            super().__init__(b"XML bytes")
            self.headers = Message()
            self.headers["ETag"] = 'W/"new"'

    response = Response()
    calls = []

    def fake_urlopen(request, *, timeout):
        calls.append((request, timeout))
        return response

    monkeypatch.setattr("pyjmaxml.feed._http.urlopen", fake_urlopen)
    result = UrllibHttpClient(timeout=12).send(REQUEST)
    assert result == HttpResponse(200, {"ETag": 'W/"new"'}, b"XML bytes")
    request, timeout = calls[0]
    assert request.full_url == REQUEST.url
    assert request.get_method() == "GET"
    assert {k.lower(): v for k, v in request.header_items()} == {
        k.lower(): v for k, v in REQUEST.headers.items()
    }
    assert timeout == 12
    assert response.closed


@pytest.mark.parametrize("status", [304, 404, 500])
def test_urllib_returns_http_error_responses_for_core_to_interpret(status, monkeypatch):
    headers = Message()
    headers["ETag"] = 'W/"unchanged"'
    body = BytesIO(b"" if status == 304 else b"error body")
    error = HTTPError(REQUEST.url, status, "response", headers, body)

    def fake_urlopen(request, *, timeout):
        raise error

    monkeypatch.setattr("pyjmaxml.feed._http.urlopen", fake_urlopen)
    result = UrllibHttpClient().send(REQUEST)
    assert result.status == status
    assert result.headers["ETag"] == 'W/"unchanged"'
    assert result.body == (b"" if status == 304 else b"error body")
    assert body.closed


def test_urllib_transport_errors_are_not_hidden(monkeypatch):
    error = URLError("connection failed")

    def fake_urlopen(request, *, timeout):
        raise error

    monkeypatch.setattr("pyjmaxml.feed._http.urlopen", fake_urlopen)
    with pytest.raises(URLError) as caught:
        UrllibHttpClient().send(REQUEST)
    assert caught.value is error


@pytest.mark.parametrize("status", [200, 304, 500])
def test_httpx_adapts_status_headers_and_body_without_network(status):
    httpx = pytest.importorskip("httpx")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"ETag": 'W/"reply"'}, content=b"response")

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        adapter = HttpxHttpClient(client)
        result = adapter.send(REQUEST)
        assert result.status == status
        assert result.headers["etag"] == 'W/"reply"'
        assert result.body == b"response"
        assert len(calls) == 1
        assert str(calls[0].url) == REQUEST.url
        assert calls[0].method == "GET"
        assert calls[0].headers["User-Agent"] == REQUEST.headers["User-Agent"]
        assert calls[0].headers["If-None-Match"] == REQUEST.headers["If-None-Match"]
        adapter.close()
        assert not client.is_closed


def test_httpx_owned_client_is_closed():
    pytest.importorskip("httpx")
    adapter = HttpxHttpClient()
    adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        adapter.send(REQUEST)


def test_httpx_is_optional_and_has_actionable_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    # The default client still constructs without the optional dependency.
    FeedClient(FeedKind.EXTRA)
    with pytest.raises(ImportError, match=r"pyjmaxml\[httpx\]"):
        HttpxHttpClient()
