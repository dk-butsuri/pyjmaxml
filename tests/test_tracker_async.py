import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from tracker_helpers import (
    BASE,
    EARTHQUAKE,
    FORECAST,
    TIMESERIES,
    WARNING,
    Clock,
    FakeAsyncHttp,
    FakeHttp,
    atom_entries,
    entry_for,
)

from pyjmaxml import AsyncTracker, Tracker, parse
from pyjmaxml.feed import FeedTransportError, HttpResponse, TooFrequentError


def configured_http():
    http = FakeHttp()
    warning = http.document(WARNING, "011000")
    forecast = http.document(FORECAST)
    timeseries = http.document(TIMESERIES)
    earthquake = http.document(EARTHQUAKE)
    http.queue(BASE + "extra_l.xml", atom_entries(warning))
    http.queue(BASE + "regular_l.xml", atom_entries(forecast, timeseries))
    http.queue(BASE + "eqvol.xml", atom_entries(earthquake))
    return http


def test_sync_async_results_and_request_order_match():
    clock = Clock(parse(WARNING).control.date_time)
    sync_http = configured_http()
    sync = Tracker(
        ["北海道稚内市", "東京都千代田区"], prefectures=["北海道"], http=sync_http, clock=clock
    )
    expected = sync.update()
    async_http = configured_http()
    transport = FakeAsyncHttp(async_http)

    async def run():
        async with AsyncTracker(
            ["北海道稚内市", "東京都千代田区"], prefectures=["北海道"], http=transport, clock=clock
        ) as tracker:
            actual = await tracker.update()
            assert actual == expected
            assert tracker.areas == sync.areas
            assert tracker.earthquake == sync.earthquake
            assert tracker.updated_at == sync.updated_at
            assert tracker.area("東京都千代田区") == sync.area("東京都千代田区")
            assert tracker.prefecture("北海道") == sync.prefecture("北海道")
            assert tracker.warning_state.to_json() == sync.warning_state.to_json()
        assert not transport.closed

    asyncio.run(run())
    assert async_http.requests == sync_http.requests


@pytest.mark.parametrize("long", [False, True])
def test_async_retry_poll_failure_and_order(long):
    http = FakeHttp()
    clock = Clock(parse(WARNING).control.date_time)
    warning = entry_for(WARNING, "011000")
    failure = FeedTransportError("retry warning")
    http.queue(warning.url, failure, HttpResponse(200, {}, WARNING.read_bytes()))
    http.queue(BASE + ("extra_l.xml" if long else "extra.xml"), atom_entries(warning))
    forecast = http.document(FORECAST)
    http.queue(BASE + "regular.xml", atom_entries(forecast))
    poll_failure = FeedTransportError("eqvol unavailable")
    http.queue(BASE + "eqvol.xml", poll_failure)
    tracker = AsyncTracker(
        ["北海道稚内市", "東京都千代田区"], http=FakeAsyncHttp(http), clock=clock
    )

    async def run():
        first = await tracker.update()
        assert first.errors == (failure, poll_failure)
        assert first.applied == 1
        assert tracker.area("東京都千代田区").forecast
        clock.now += timedelta(seconds=60)
        assert (await tracker.update()).applied == 1
        assert tracker.area("北海道稚内市").warnings
        assert http.counts[warning.url] == 2
        too_soon = await tracker.update()
        assert len(too_soon.errors) == 3
        assert all(isinstance(e, TooFrequentError) for e in too_soon.errors)
        await tracker.aclose()

    asyncio.run(run())


def test_async_failed_long_feed_poll_is_retried_after_its_interval():
    http = FakeHttp()
    clock = Clock(parse(FORECAST).control.date_time)
    http.queue(BASE + "regular_l.xml", FeedTransportError("offline"))
    tracker = AsyncTracker(["東京都千代田区"], http=FakeAsyncHttp(http), clock=clock)

    async def run():
        assert len((await tracker.update()).errors) == 1
        clock.now += timedelta(minutes=10)
        assert (await tracker.update()).errors == ()
        http.queue(BASE + "regular_l.xml", atom_entries(http.document(FORECAST)))
        clock.now += timedelta(hours=1)
        assert (await tracker.update()).applied == 1
        await tracker.aclose()

    asyncio.run(run())
    assert http.counts[BASE + "regular_l.xml"] == 2
    assert http.counts[BASE + "extra_l.xml"] == 1


def test_async_filter_parse_status_and_exceptions(monkeypatch, caplog):
    http = FakeHttp()
    valid = entry_for(WARNING, "011000")
    invalid = replace(valid, id="invalid", url=valid.url.replace("sample", "broken") + "?broken")
    training = replace(valid, id="training", url=valid.url + "?training")
    ignored = replace(valid, id="ignored", title="府県天気概況")
    other_pref = replace(valid, id="other", url=valid.url.replace("011000", "270000"))
    # The supported training report still needs a well-formed URL for pre-fetch filtering.
    invalid = replace(invalid, url="https://example.test/broken_011000.xml")
    training = replace(training, url="https://example.test/training_011000.xml")
    http.queue(invalid.url, HttpResponse(200, {}, b"<broken"))
    http.queue(
        training.url,
        HttpResponse(
            200,
            {},
            WARNING.read_bytes().replace(
                "<Status>通常</Status>".encode(), "<Status>訓練</Status>".encode()
            ),
        ),
    )
    http.queue(BASE + "extra.xml", atom_entries(invalid, training, ignored, other_pref))
    clock = Clock(parse(WARNING).control.date_time)
    tracker = AsyncTracker(["北海道稚内市"], http=FakeAsyncHttp(http), clock=clock)

    async def run():
        result = await tracker.update()
        assert not result.applied and not result.errors
        assert not tracker.area("北海道稚内市").warnings
        clock.now += timedelta(seconds=60)
        await tracker.update()
        assert http.counts[invalid.url] == http.counts[training.url] == 1
        assert not http.counts[other_pref.url]
        clock.now += timedelta(seconds=60)
        http.queue(BASE + "regular.xml", RuntimeError("unexpected"))
        before = tracker.updated_at
        with pytest.raises(RuntimeError, match="unexpected"):
            await tracker.update()
        assert tracker.updated_at == before

    asyncio.run(run())
    assert "invalid" in caplog.text


def test_async_owned_transport_is_closed_on_context_exit(monkeypatch):
    transport = FakeAsyncHttp(FakeHttp())
    monkeypatch.setattr("pyjmaxml.tracker._async.HttpxAsyncHttpClient", lambda: transport)
    tracker = AsyncTracker(["大阪府枚方市"])

    async def run():
        with pytest.raises(RuntimeError, match="body"):
            async with tracker:
                await tracker.update()
                raise RuntimeError("body")
        assert transport.closed
        await tracker.aclose()

    asyncio.run(run())
