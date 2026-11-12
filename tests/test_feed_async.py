import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from feed_helpers import DATA, feed, recorded

from pyjmaxml import WarningState, parse
from pyjmaxml.feed import (
    AsyncFeedClient,
    Entry,
    FeedKind,
    FeedTransportError,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    HttpxAsyncHttpClient,
    TooFrequentError,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
SAMPLE = Path(__file__).parent / "data" / "samples" / "15_16_03_241226_VPWW55.xml"
REQUEST = HttpRequest("GET", "https://example.test/feed.xml", {"User-Agent": "pyjmaxml/test"})


class FakeAsyncHttpClient:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self.responses = iter(responses)
        self.requests: list[HttpRequest] = []

    async def send(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def client_for(http: FakeAsyncHttpClient, **options: object) -> AsyncFeedClient:
    return AsyncFeedClient(FeedKind.EXTRA, http=http, clock=lambda: NOW, **options)  # type: ignore[arg-type]


def test_recorded_poll_roundtrip():
    http = FakeAsyncHttpClient([recorded("extra"), recorded("extra", 304)])
    times = iter([NOW, NOW, NOW + timedelta(seconds=60), NOW + timedelta(seconds=60)])
    client = AsyncFeedClient(FeedKind.EXTRA, http=http, clock=lambda: next(times))

    async def run() -> tuple[list[Entry], list[Entry]]:
        return await client.poll(), await client.poll()

    first, second = asyncio.run(run())
    assert len(first) == 104 and second == first
    assert http.requests[0].url.endswith("/extra.xml")
    assert "If-None-Match" in http.requests[1].headers or "If-Modified-Since" in (
        http.requests[1].headers
    )


def test_minimum_interval_is_enforced():
    http = FakeAsyncHttpClient([recorded("extra")])
    client = client_for(http)

    async def run() -> None:
        await client.poll()
        with pytest.raises(TooFrequentError):
            await client.poll()

    asyncio.run(run())
    assert len(http.requests) == 1


def test_fetch_does_not_ack_and_failures_are_returned_again():
    http = FakeAsyncHttpClient(
        [
            HttpResponse(200, {}, feed("a", "b")),
            FeedTransportError("no response"),
            HttpResponse(200, {}, b"<Report/>"),
            HttpResponse(304, {}, b""),
        ]
    )
    client = client_for(http, min_interval=0, unsafe_min_interval=True)

    async def run() -> list[Entry]:
        entries = await client.poll()
        with pytest.raises(FeedTransportError):
            await client.fetch(entries[0])
        assert await client.fetch(entries[1]) == b"<Report/>"
        client.ack(entries[1])
        return await client.poll()

    remaining = asyncio.run(run())
    assert [entry.id for entry in remaining] == ["a"]
    assert http.requests[1].url == "https://example.test/a.xml"
    assert "If-None-Match" not in http.requests[1].headers


@pytest.mark.parametrize("status", [304, 404, 500])
def test_fetch_uses_core_status_validation(status):
    http = FakeAsyncHttpClient([HttpResponse(status, {}, b"")])
    client = client_for(http)
    entry = Entry("id", "title", NOW, "author", "https://example.test/report.xml")
    with pytest.raises(HttpStatusError):
        asyncio.run(client.fetch(entry))


def test_concurrency_is_limited():
    active = peak = 0

    class SlowClient:
        async def send(self, req: HttpRequest) -> HttpResponse:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return HttpResponse(200, {}, req.url.encode())

    client = AsyncFeedClient(FeedKind.EXTRA, http=SlowClient(), max_concurrency=3)
    entries = [Entry(str(i), "t", NOW, "a", f"https://example.test/{i}.xml") for i in range(10)]

    async def run() -> list[bytes]:
        return await asyncio.gather(*(client.fetch(entry) for entry in entries))

    bodies = asyncio.run(run())
    assert bodies == [entry.url.encode() for entry in entries]
    assert peak == 3


def test_invalid_concurrency_is_rejected():
    with pytest.raises(ValueError, match="max_concurrency"):
        AsyncFeedClient(FeedKind.EXTRA, http=FakeAsyncHttpClient([]), max_concurrency=0)


def test_end_to_end_with_httpx_mock_transport():
    httpx = pytest.importorskip("httpx")
    feed_body = (DATA / "extra.xml").read_bytes()
    report = SAMPLE.read_bytes()

    def handler(request):
        if request.url.path.endswith("/extra.xml"):
            return httpx.Response(200, content=feed_body)
        return httpx.Response(200, content=report)

    async def run() -> WarningState:
        state = WarningState()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = AsyncFeedClient(FeedKind.EXTRA, http=HttpxAsyncHttpClient(http_client))
            entries = await client.poll()
            bodies = await asyncio.gather(*(client.fetch(entry) for entry in entries))
            for entry, body in zip(entries, bodies, strict=True):
                state.apply(parse(body))
                client.ack(entry)
            assert not http_client.is_closed
        return state

    state = asyncio.run(run())
    assert {kind.name for kind in state.by_city("0121400")} == {"レベル４大雨危険警報"}


def test_httpx_async_errors_become_feed_errors_with_cause():
    httpx = pytest.importorskip("httpx")
    error = httpx.ReadTimeout("timed out")

    def handler(request):
        raise error

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            with pytest.raises(FeedTransportError) as caught:
                await HttpxAsyncHttpClient(http_client).send(REQUEST)
            assert caught.value.__cause__ is error

    asyncio.run(run())


def test_default_transport_is_owned_and_closed():
    pytest.importorskip("httpx")

    async def run() -> AsyncFeedClient:
        async with AsyncFeedClient(FeedKind.EXTRA) as client:
            assert isinstance(client._http, HttpxAsyncHttpClient)  # pyright: ignore[reportPrivateUsage]
        return client

    client = asyncio.run(run())
    with pytest.raises(RuntimeError, match="closed"):
        asyncio.run(client._http.send(REQUEST))  # pyright: ignore[reportPrivateUsage]


def test_injected_transport_is_not_closed():
    httpx = pytest.importorskip("httpx")

    async def run() -> None:
        async with httpx.AsyncClient() as http_client:
            async with AsyncFeedClient(FeedKind.EXTRA, http=HttpxAsyncHttpClient(http_client)):
                pass
            assert not http_client.is_closed

    asyncio.run(run())


def test_httpx_is_required_only_for_the_default_transport(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    AsyncFeedClient(FeedKind.EXTRA, http=FakeAsyncHttpClient([]))
    with pytest.raises(ImportError, match=r"pyjmaxml\[httpx\]"):
        AsyncFeedClient(FeedKind.EXTRA)
