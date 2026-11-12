import ast
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from feed_helpers import feed, recorded

from pyjmaxml import parse
from pyjmaxml.feed import (
    Entry,
    FeedClient,
    FeedKind,
    FeedPoller,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    TooFrequentError,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
ENTRY = Entry("id", "title", NOW, "author", "https://example.test/report.xml")


class FakeHttpClient:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self.responses = iter(responses)
        self.requests: list[HttpRequest] = []

    def send(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_poll_bridges_request_transport_response_and_explicit_clock():
    request = HttpRequest("GET", "https://example.test/feed.xml", {"X-Test": "request"})
    response = HttpResponse(200, {"X-Test": "response"}, b"response")
    http = FakeHttpClient([response])
    times = iter([NOW, NOW + timedelta(seconds=2)])
    client = FeedClient(FeedKind.EXTRA, http=http, clock=lambda: next(times))
    with (
        patch.object(FeedPoller, "next_request", autospec=True, return_value=request) as build,
        patch.object(FeedPoller, "handle_response", autospec=True, return_value=[ENTRY]) as handle,
    ):
        assert client.poll() == [ENTRY]
        assert build.call_args.args[1:] == (NOW,)
        assert http.requests == [request]
        assert handle.call_args.args[1:] == (response, NOW + timedelta(seconds=2))


def test_recorded_poll_roundtrip_with_fake_transport():
    response = recorded("extra")
    http = FakeHttpClient([response, recorded("extra", 304)])
    times = iter(
        [NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=60), NOW + timedelta(seconds=61)]
    )
    seen: set[str] = set()
    client = FeedClient(FeedKind.EXTRA, http=http, seen=seen, clock=lambda: next(times))
    entries = client.poll()
    assert len(entries) == 104
    assert seen == set()
    for entry in entries:
        client.ack(entry)
    assert len(seen) == 104
    assert client.poll() == []
    assert http.requests[1].headers["If-None-Match"] == response.headers["ETag"]
    assert http.requests[1].headers["If-Modified-Since"] == response.headers["Last-Modified"]


@pytest.mark.parametrize(("long", "minimum"), [(True, 3600), (False, 120)])
def test_constructor_forwards_long_and_minimum_interval(long, minimum):
    http = FakeHttpClient([HttpResponse(304, {}, b"")])
    current = NOW
    client = FeedClient(
        FeedKind.EQVOL, long=long, min_interval=minimum, http=http, clock=lambda: current
    )
    assert client.poll() == []
    expected = "eqvol_l.xml" if long else "eqvol.xml"
    assert http.requests[0].url.endswith(expected)
    current += timedelta(seconds=minimum - 1)
    with pytest.raises(TooFrequentError):
        client.poll()
    assert len(http.requests) == 1


def test_unsafe_interval_option_is_forwarded():
    http = FakeHttpClient([HttpResponse(304, {}, b""), HttpResponse(304, {}, b"")])
    client = FeedClient(
        FeedKind.EXTRA, http=http, clock=lambda: NOW, min_interval=0, unsafe_min_interval=True
    )
    assert client.poll() == client.poll() == []
    assert len(http.requests) == 2


def test_transport_failure_propagates_without_immediate_retry():
    error = OSError("transport failed")
    http = FakeHttpClient([error])
    client = FeedClient(FeedKind.EXTRA, http=http, clock=lambda: NOW)
    with pytest.raises(OSError) as caught:
        client.poll()
    assert caught.value is error
    with pytest.raises(TooFrequentError):
        client.poll()
    assert len(http.requests) == 1


@pytest.mark.parametrize("next_status", [200, 304])
def test_failed_fetch_is_returned_by_next_poll(next_status):
    response = HttpResponse(200, {}, feed("retry"))
    following = response if next_status == 200 else HttpResponse(304, {}, b"")
    http = FakeHttpClient([response, OSError("fetch failed"), following])
    client = FeedClient(
        FeedKind.EXTRA, http=http, clock=lambda: NOW, min_interval=0, unsafe_min_interval=True
    )
    entries = client.poll()
    with pytest.raises(OSError, match="fetch failed"):
        client.fetch(entries[0])
    assert client.poll() == entries


def test_successful_fetch_does_not_ack_and_explicit_ack_is_forwarded():
    seen: set[str] = set()
    http = FakeHttpClient(
        [
            HttpResponse(200, {}, feed("a")),
            HttpResponse(200, {}, b"report"),
            HttpResponse(304, {}, b""),
            HttpResponse(304, {}, b""),
        ]
    )
    client = FeedClient(
        FeedKind.EXTRA,
        seen=seen,
        http=http,
        clock=lambda: NOW,
        min_interval=0,
        unsafe_min_interval=True,
    )
    entries = client.poll()
    assert client.fetch(entries[0]) == b"report"
    assert seen == set()
    assert client.poll() == entries
    client.ack(entries[0])
    assert seen == {"a"}
    assert client.poll() == []


def test_ack_is_a_direct_bridge_without_clock_or_transport():
    http = FakeHttpClient([])

    def no_clock():
        raise AssertionError("ack must not read the clock")

    client = FeedClient(FeedKind.EXTRA, http=http, clock=no_clock)
    with patch.object(FeedPoller, "ack", autospec=True) as ack:
        client.ack(ENTRY)
        assert ack.call_args.args[1:] == (ENTRY,)
        client.ack(ENTRY.id)
        assert ack.call_args.args[1:] == (ENTRY.id,)
    assert http.requests == []


def test_user_agent_option_reaches_both_request_types():
    http = FakeHttpClient([HttpResponse(200, {}, feed("a")), HttpResponse(200, {}, b"body")])
    client = FeedClient(FeedKind.EXTRA, http=http, clock=lambda: NOW, user_agent="operator/2.0")
    entry = client.poll()[0]
    client.fetch(entry)
    assert [req.headers["User-Agent"] for req in http.requests] == ["operator/2.0"] * 2
    with pytest.raises(ValueError, match="user_agent"):
        FeedClient(FeedKind.EXTRA, http=http, user_agent="")


@pytest.mark.parametrize("compressed", [False, True])
def test_fetch_forwards_request_and_returns_bytes_accepted_by_parse(compressed):
    path = Path(__file__).parent / "data" / "samples" / "15_16_03_241226_VPWW55.xml"
    body = path.read_bytes()
    payload = gzip.compress(body) if compressed else body
    http = FakeHttpClient([HttpResponse(200, {}, payload)])

    def no_clock_needed():
        raise AssertionError("fetch must not read the polling clock")

    client = FeedClient(FeedKind.EXTRA, http=http, clock=no_clock_needed)
    result = client.fetch(ENTRY)
    assert result == payload
    assert parse(result, strict=True).control.title == "気象警報・注意報（Ｒ０６）（大雨）"
    assert http.requests[0].url == ENTRY.url
    assert http.requests[0].method == "GET"
    assert http.requests[0].headers["User-Agent"].startswith("pyjmaxml/")


@pytest.mark.parametrize("status", [304, 404, 503])
def test_fetch_uses_core_status_validation(status):
    http = FakeHttpClient([HttpResponse(status, {}, b"not report XML")])
    client = FeedClient(FeedKind.EXTRA, http=http)
    with pytest.raises(HttpStatusError) as error:
        client.fetch(ENTRY)
    assert error.value.status == status


def test_default_clock_supplies_aware_datetimes():
    client = FeedClient(FeedKind.EXTRA, http=FakeHttpClient([HttpResponse(304, {}, b"")]))
    assert client.poll() == []


def test_default_transport_is_created_without_sending_requests():
    with patch("pyjmaxml.feed._sync.UrllibHttpClient", autospec=True) as transport:
        FeedClient(FeedKind.EXTRA)
        transport.assert_called_once_with()
        transport.return_value.send.assert_not_called()


def test_poll_and_fetch_contain_only_bridging_without_branches():
    path = Path(__file__).parents[1] / "pyjmaxml" / "feed" / "_sync.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in {"poll", "fetch", "ack"}
    ]
    assert len(methods) == 3
    assert not any(
        isinstance(node, (ast.If, ast.IfExp, ast.Try, ast.Match, ast.For, ast.While))
        for method in methods
        for node in ast.walk(method)
    )
