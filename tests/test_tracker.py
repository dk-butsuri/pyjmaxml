from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from xml.etree import ElementTree as ET

import pytest
from feed_helpers import ATOM, recorded
from tracker_helpers import (
    BASE,
    DATA,
    EARLY,
    EARTHQUAKE,
    FORECAST,
    POSSIBILITY,
    POSSIBILITY_WEEKLY,
    SNAPSHOT,
    TIMESERIES,
    WARNING,
    WEEKLY,
    Clock,
    FakeHttp,
    atom_entries,
    entry_for,
)

from pyjmaxml import (
    AreaName,
    Prefecture,
    Tracker,
    WarningState,
    earthquake_info,
    parse,
    warning_possibility,
    warning_timeseries,
    weather_forecast,
)
from pyjmaxml.codes._area_name import AREA_CODE_BY_NAME, AREAS_BY_PREFECTURE
from pyjmaxml.feed import FeedTransportError, HttpResponse, TooFrequentError


def test_all_views_match_low_level_apis_and_are_snapshots():
    http = FakeHttp()
    clock = Clock(parse(WARNING).control.date_time)
    warning = http.document(WARNING, "011000")
    forecasts = [
        http.document(path)
        for path in (FORECAST, WEEKLY, POSSIBILITY, EARLY, POSSIBILITY_WEEKLY, TIMESERIES)
    ]
    earthquake = http.document(EARTHQUAKE)
    http.queue(BASE + "extra_l.xml", atom_entries(warning))
    http.queue(BASE + "regular_l.xml", atom_entries(*forecasts))
    http.queue(BASE + "eqvol.xml", atom_entries(earthquake))
    tracker = Tracker(
        ["北海道稚内市", "東京都千代田区"], http=http, clock=clock, user_agent="tracker-test/1"
    )
    before = tracker.area("北海道稚内市")
    assert tracker.updated_at is None and tracker.earthquake is None
    assert not before.warnings and not before.timeseries
    result = tracker.update()
    state = WarningState()
    expected = state.apply(parse(WARNING), now=clock())
    assert tracker.area("北海道稚内市").warnings == state.by_city("0121400")
    assert result.changes == tuple(c for c in expected.changes if c.area == "0121400")
    tokyo = tracker.area("東京都千代田区")
    assert tokyo.forecast == weather_forecast(parse(FORECAST)).by_city(tokyo.code)
    assert tokyo.weekly_forecast == weather_forecast(parse(WEEKLY)).by_city(tokyo.code)
    assert tokyo.possibility == warning_possibility(parse(POSSIBILITY)).by_city(tokyo.code)
    assert tokyo.possibility_early == warning_possibility(parse(EARLY)).by_city(tokyo.code)
    assert tokyo.possibility_weekly == warning_possibility(parse(POSSIBILITY_WEEKLY)).by_city(
        tokyo.code
    )
    assert all(
        (
            tokyo.forecast,
            tokyo.weekly_forecast,
            tokyo.possibility,
            tokyo.possibility_early,
            tokyo.possibility_weekly,
        )
    )
    assert tracker.area("北海道稚内市").timeseries == warning_timeseries(parse(TIMESERIES)).by_city(
        "0121400"
    )
    assert tracker.earthquake == earthquake_info(parse(EARTHQUAKE))
    assert result.applied == 8 and not result.errors
    assert tracker.updated_at == clock().astimezone(UTC)
    assert not before.warnings and not before.timeseries
    with pytest.raises(FrozenInstanceError):
        tokyo.__setattr__("code", "changed")
    assert all(req.headers["User-Agent"] == "tracker-test/1" for req in http.requests)


def test_filtering_ack_and_first_update_only_long_feeds():
    http = FakeHttp()
    clock = Clock(parse(WARNING).control.date_time)
    unwanted_warning = entry_for(WARNING, "270000")
    unwanted_forecast = entry_for(FORECAST)
    unsupported = replace(entry_for(FORECAST, "011000"), id="unused", title="府県天気概況")
    snapshot = http.document(SNAPSHOT, "010000")
    http.queue(BASE + "extra_l.xml", atom_entries(unwanted_warning))
    http.queue(BASE + "regular_l.xml", atom_entries(unwanted_forecast, unsupported, snapshot))
    # Repeated entries on the short feed are already acknowledged through the shared seen store.
    http.queue(BASE + "extra.xml", atom_entries(unwanted_warning), atom_entries(unwanted_warning))
    http.queue(
        BASE + "regular.xml",
        atom_entries(unwanted_forecast, unsupported, snapshot),
        atom_entries(unwanted_forecast, unsupported, snapshot),
    )
    tracker = Tracker(["北海道稚内市"], http=http, clock=clock)
    tracker.update()
    clock.now += timedelta(seconds=60)
    tracker.update()
    assert http.counts[snapshot.url] == 1
    assert not http.counts[unwanted_warning.url]
    assert not http.counts[unwanted_forecast.url]
    assert not http.counts[unsupported.url]
    polls = [r.url.removeprefix(BASE) for r in http.requests if r.url.startswith(BASE)]
    assert polls == [
        "extra_l.xml",
        "regular_l.xml",
        "extra.xml",
        "regular.xml",
        "eqvol.xml",
        "extra.xml",
        "regular.xml",
        "eqvol.xml",
    ]


@pytest.mark.parametrize("long", [False, True])
def test_fetch_failure_retries_without_losing_other_feed_updates(long):
    http = FakeHttp()
    clock = Clock(parse(WARNING).control.date_time)
    warning = entry_for(WARNING, "011000")
    failure = FeedTransportError("offline fetch failure")
    http.queue(warning.url, failure, HttpResponse(200, {}, WARNING.read_bytes()))
    http.queue(BASE + ("extra_l.xml" if long else "extra.xml"), atom_entries(warning))
    forecast = http.document(FORECAST)
    http.queue(BASE + "regular.xml", atom_entries(forecast))
    tracker = Tracker(["北海道稚内市", "東京都千代田区"], http=http, clock=clock)
    first = tracker.update()
    assert first.errors == (failure,)
    assert first.applied == 1
    assert tracker.area("東京都千代田区").forecast
    assert not tracker.area("北海道稚内市").warnings
    clock.now += timedelta(seconds=60)
    second = tracker.update()
    assert not second.errors and second.applied == 1
    assert tracker.area("北海道稚内市").warnings
    assert http.counts[warning.url] == 2
    clock.now += timedelta(seconds=60)
    assert tracker.update().applied == 0
    assert http.counts[warning.url] == 2


def test_poll_failures_and_minimum_interval_are_returned():
    http = FakeHttp()
    failure = FeedTransportError("offline poll failure")
    http.queue(BASE + "extra_l.xml", failure)
    forecast = http.document(FORECAST)
    http.queue(BASE + "regular.xml", atom_entries(forecast))
    tracker = Tracker(
        ["東京都千代田区"], http=http, clock=lambda: datetime(2026, 11, 12, tzinfo=UTC)
    )
    first = tracker.update()
    assert first.errors == (failure,) and first.applied == 1
    before = tracker.area("東京都千代田区")
    second = tracker.update()
    assert len(second.errors) == 3
    assert all(isinstance(error, TooFrequentError) for error in second.errors)
    assert tracker.area("東京都千代田区") == before


def test_failed_long_feed_poll_is_retried_after_its_interval():
    # A tracker started while offline must still read the long feeds later.
    http = FakeHttp()
    clock = Clock(parse(FORECAST).control.date_time)
    http.queue(BASE + "extra_l.xml", FeedTransportError("offline"))
    http.queue(BASE + "regular_l.xml", FeedTransportError("offline"))
    tracker = Tracker(["東京都千代田区"], http=http, clock=clock)
    assert len(tracker.update().errors) == 2
    clock.now += timedelta(minutes=10)
    # Waiting for the long-feed interval is expected and not reported.
    assert tracker.update().errors == ()
    assert http.counts[BASE + "regular_l.xml"] == 1
    forecast = http.document(FORECAST)
    http.queue(BASE + "regular_l.xml", atom_entries(forecast))
    clock.now += timedelta(hours=1)
    assert tracker.update().applied == 1
    assert tracker.area("東京都千代田区").forecast
    clock.now += timedelta(hours=1)
    tracker.update()
    assert http.counts[BASE + "extra_l.xml"] == 2
    assert http.counts[BASE + "regular_l.xml"] == 2


def test_older_normalized_report_does_not_replace_latest_control_datetime():
    http = FakeHttp()
    clock = Clock(parse(FORECAST).control.date_time)
    new = http.document(FORECAST)
    old = replace(new, id="older", url=new.url.replace("_0_", "_older_"))
    root = ET.fromstring(FORECAST.read_bytes())
    control = root.find("{*}Control/{*}DateTime")
    assert control is not None
    control.text = (clock() - timedelta(days=1)).isoformat()
    # Clear time-series content so retaining the old value would be visible.
    for meteorological in root.findall("{*}Body/{*}MeteorologicalInfos"):
        for series in list(meteorological):
            meteorological.remove(series)
    http.queue(old.url, HttpResponse(200, {}, ET.tostring(root)))
    http.queue(BASE + "regular.xml", atom_entries(new), atom_entries(old))
    tracker = Tracker(["東京都千代田区"], http=http, clock=clock)
    assert tracker.update().applied == 1
    before = tracker.area("東京都千代田区")
    assert before.forecast
    clock.now += timedelta(seconds=60)
    assert tracker.update().applied == 0
    assert tracker.area("東京都千代田区") == before


def test_runtime_area_validation_and_prefecture_snapshots():
    with pytest.raises(ValueError):
        Tracker()
    with pytest.raises(ValueError):
        Tracker([cast(AreaName, "枚方市")])
    with pytest.raises(ValueError):
        Tracker(prefectures=[cast(Prefecture, "近畿")])
    http = FakeHttp()
    warning = http.document(WARNING, "011000")
    http.queue(BASE + "extra.xml", atom_entries(warning))
    tracker = Tracker(
        ["北海道稚内市", "北海道稚内市"],
        prefectures=["北海道", "北海道"],
        http=http,
        clock=lambda: parse(WARNING).control.date_time,
    )
    before = tracker.prefecture("北海道")
    assert not before.warned()
    assert tracker.areas == AREAS_BY_PREFECTURE["北海道"]
    assert len(tracker.areas) == 186
    assert [AREA_CODE_BY_NAME[name] for name in tracker.areas] == sorted(
        AREA_CODE_BY_NAME[name] for name in tracker.areas
    )
    tracker.update()
    after = tracker.prefecture("北海道")
    assert after.code == "01"
    assert after.area("北海道稚内市") == tracker.area("北海道稚内市")
    assert after.area("北海道稚内市") in after.warned()
    assert not before.warned()
    for name in ("大阪府枚方市", cast(AreaName, "存在しない区域")):
        with pytest.raises(ValueError):
            tracker.area(name)
        with pytest.raises(ValueError):
            after.area(name)
    with pytest.raises(ValueError):
        Tracker(["大阪府枚方市"]).prefecture("大阪府")


@pytest.mark.parametrize("case", ["parse", "apply", "normalize", "status"])
def test_bad_reports_are_logged_and_acknowledged(case, monkeypatch, caplog):
    http = FakeHttp()
    path = FORECAST if case == "normalize" else WARNING
    entry = entry_for(path, "011000" if path == WARNING else None)
    data = path.read_bytes()
    if case == "parse":
        data = b"<invalid"
    elif case == "status":
        data = data.replace("<Status>通常</Status>".encode(), "<Status>訓練</Status>".encode())
    elif case == "apply":
        monkeypatch.setattr(
            "pyjmaxml.tracker._core.WarningState.apply",
            lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad warning")),
        )
    else:
        monkeypatch.setattr(
            "pyjmaxml.tracker._core.weather_forecast",
            lambda *a: (_ for _ in ()).throw(ValueError("bad forecast")),
        )
    http.queue(entry.url, HttpResponse(200, {}, data))
    kind = "regular" if case == "normalize" else "extra"
    http.queue(BASE + kind + ".xml", atom_entries(entry))
    clock = Clock(parse(WARNING).control.date_time)
    tracker = Tracker(["北海道稚内市", "東京都千代田区"], http=http, clock=clock)
    result = tracker.update()
    assert result.applied == 0 and not result.errors
    clock.now += timedelta(seconds=60)
    tracker.update()
    assert http.counts[entry.url] == 1
    if case != "status":
        assert entry.id in caplog.text
        assert caplog.records[-1].exc_info is not None


def test_non_feed_error_propagates_and_does_not_mark_update_completed():
    http = FakeHttp()
    http.queue(BASE + "extra_l.xml", RuntimeError("unexpected"))
    tracker = Tracker(["大阪府枚方市"], http=http)
    with pytest.raises(RuntimeError, match="unexpected"):
        tracker.update()
    assert tracker.updated_at is None


def test_recorded_feed_titles_match_saved_reports_and_drive_tracker():
    response = recorded("regular")
    root = ET.fromstring(response.body)
    saved = {
        p.name: p for folder in ("forecast", "possibility") for p in (DATA / folder).glob("*.xml")
    }
    http = FakeHttp()
    matches = 0
    for node in root.findall(ATOM + "entry"):
        link = node.find(ATOM + "link")
        assert link is not None
        url = link.attrib["href"]
        path = saved.get(url.rsplit("/", 1)[-1])
        if path is not None:
            assert node.findtext(ATOM + "title") == parse(path).control.title
            http.queue(url, HttpResponse(200, {}, path.read_bytes()))
            matches += 1
        else:
            root.remove(node)
    assert matches == 7
    http.queue(BASE + "regular.xml", HttpResponse(200, {}, ET.tostring(root)))
    tracker = Tracker(["東京都千代田区", "北海道稚内市", "鹿児島県鹿児島市"], http=http)
    result = tracker.update()
    assert not result.errors
    assert tracker.area("東京都千代田区").forecast
    assert tracker.area("鹿児島県鹿児島市").weekly_forecast


def test_recorded_extra_title_and_warning_match_low_level_api():
    path = DATA / "tracker/20261111130624_0_VPWW59_130000.xml"
    report = parse(path)
    root = ET.fromstring(recorded("extra").body)
    urls = []
    for node in list(root):
        if node.tag != ATOM + "entry":
            continue
        link = node.find(ATOM + "link")
        assert link is not None
        url = link.attrib["href"]
        if url.endswith("/" + path.name):
            assert node.findtext(ATOM + "title") == report.control.title
            urls.append(url)
        else:
            root.remove(node)
    assert len(urls) == 1
    http = FakeHttp()
    http.queue(BASE + "extra.xml", HttpResponse(200, {}, ET.tostring(root)))
    http.queue(urls[0], HttpResponse(200, {}, path.read_bytes()))
    tracker = Tracker(prefectures=["東京都"], http=http, clock=lambda: report.control.date_time)
    state = WarningState()
    state.apply(report, now=report.control.date_time)
    assert tracker.update().applied == 1
    for area in tracker.prefecture("東京都").areas:
        assert area.warnings == state.by_city(area.code)
    assert tracker.prefecture("東京都").warned()


def test_long_fetch_failure_resolved_on_short_feed_is_not_retried_again():
    http = FakeHttp()
    clock = Clock(parse(WARNING).control.date_time)
    entry = entry_for(WARNING, "011000")
    http.queue(
        entry.url, FeedTransportError("long failed"), HttpResponse(200, {}, WARNING.read_bytes())
    )
    http.queue(BASE + "extra_l.xml", atom_entries(entry))
    http.queue(BASE + "extra.xml", atom_entries(entry))
    tracker = Tracker(["北海道稚内市"], http=http, clock=clock)
    assert tracker.update().applied == 1
    clock.now += timedelta(seconds=60)
    assert tracker.update().applied == 0
    assert http.counts[entry.url] == 2


def test_latest_earthquake_uses_control_datetime_across_groups():
    paths = sorted((DATA / "earthquake").glob("*.xml"))
    latest = max(paths, key=lambda path: parse(path).control.date_time)
    older = min(paths, key=lambda path: parse(path).control.date_time)
    assert latest != older
    http = FakeHttp()
    new = http.document(latest)
    old = http.document(older)
    # Feed updated order deliberately differs from report Control/DateTime.
    old = replace(old, updated=new.updated + timedelta(seconds=1))
    http.queue(BASE + "eqvol.xml", atom_entries(new), atom_entries(old))
    clock = Clock(parse(latest).control.date_time)
    tracker = Tracker(["大阪府枚方市"], http=http, clock=clock)
    assert tracker.update().applied == 1
    before = tracker.earthquake
    clock.now += timedelta(seconds=60)
    assert tracker.update().applied == 0
    assert tracker.earthquake == before == earthquake_info(parse(latest))


@pytest.mark.parametrize(
    "path",
    [p for folder in ("forecast", "possibility") for p in sorted((DATA / folder).glob("*.xml"))],
    ids=lambda p: p.name,
)
def test_saved_forecast_and_possibility_area_codes_share_url_prefecture_prefix(path):
    prefix = path.stem.rsplit("_", 1)[1][:2]
    root = ET.parse(path).getroot()
    codes = [node.text for node in root.findall(".//{*}TimeSeriesInfo/{*}Item/{*}Area/{*}Code")]
    assert codes and all(code is not None and code[:2] == prefix for code in codes)
