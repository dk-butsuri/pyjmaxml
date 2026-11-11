import ast
from datetime import UTC, datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from feed_helpers import ATOM, feed, recorded

from jmadantic.feed import (
    FeedKind,
    FeedParseError,
    FeedPoller,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    TooFrequentError,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)


@pytest.mark.parametrize(("kind", "count"), [(FeedKind.REGULAR, 530), (FeedKind.EXTRA, 104)])
def test_recorded_feed_entries(kind, count):
    response = recorded(kind.value)
    entries = FeedPoller(kind).handle_response(response, NOW)
    assert len(entries) == count
    root = ET.fromstring(response.body)
    for entry, xml in zip(entries, root.findall(ATOM + "entry"), strict=True):
        assert entry.id == xml.findtext(ATOM + "id")
        assert entry.title == xml.findtext(ATOM + "title")
        assert entry.author == xml.findtext(ATOM + "author/" + ATOM + "name")
        timestamp = xml.findtext(ATOM + "updated")
        assert timestamp is not None
        assert entry.updated == datetime.fromisoformat(timestamp)
        assert entry.updated.utcoffset() is not None
        link = xml.find(ATOM + "link")
        assert link is not None
        assert entry.url == link.get("href")


def test_recorded_200_304_then_new_entry():
    poller = FeedPoller(FeedKind.EXTRA)
    first_request = poller.next_request(NOW)
    assert "If-None-Match" not in first_request.headers
    assert "If-Modified-Since" not in first_request.headers
    response = recorded("extra")
    entries = poller.handle_response(response, NOW + timedelta(seconds=1))
    assert len(entries) == 104
    second_request = poller.next_request(NOW + timedelta(seconds=60))
    assert second_request.headers["If-None-Match"] == response.headers["ETag"]
    assert second_request.headers["If-None-Match"].startswith('W/"')
    assert second_request.headers["If-Modified-Since"] == response.headers["Last-Modified"]
    assert poller.handle_response(recorded("extra", 304), NOW + timedelta(seconds=61)) == []
    poller.next_request(NOW + timedelta(seconds=120))
    # Derive the next response in memory; never rewrite the recordings.
    root = ET.fromstring(response.body)
    new_entry = ET.fromstring(feed("new-entry")).find(ATOM + "entry")
    assert new_entry is not None
    root.append(new_entry)
    new_response = HttpResponse(200, {"etag": 'W/"new"'}, ET.tostring(root))
    result = poller.handle_response(new_response, NOW + timedelta(seconds=121))
    assert [entry.id for entry in result] == ["new-entry"]
    request = poller.next_request(NOW + timedelta(seconds=180))
    assert request.headers["If-None-Match"] == 'W/"new"'
    assert "If-Modified-Since" not in request.headers


@pytest.mark.parametrize("kind", list(FeedKind))
@pytest.mark.parametrize("long", [False, True])
def test_urls_and_default_interval(kind, long):
    poller = FeedPoller(kind, long=long)
    suffix = "_l" if long else ""
    request = poller.next_request(NOW)
    assert request.method == "GET"
    assert request.url == f"https://www.data.jma.go.jp/developer/xml/feed/{kind.value}{suffix}.xml"
    assert request.headers["User-Agent"] == f"jmadantic/{version('jmadantic')}"
    seconds = 3600 if long else 60
    with pytest.raises(TooFrequentError):
        poller.next_request(NOW + timedelta(seconds=seconds, microseconds=-1))
    assert poller.next_request(NOW + timedelta(seconds=seconds)).url == request.url


@pytest.mark.parametrize(("long", "seconds"), [(False, 120), (True, 7200)])
def test_longer_intervals(long, seconds):
    poller = FeedPoller(FeedKind.EXTRA, long=long, min_interval=seconds)
    poller.next_request(NOW)
    with pytest.raises(TooFrequentError):
        poller.next_request(NOW + timedelta(seconds=seconds - 1))
    poller.next_request(NOW + timedelta(seconds=seconds))


@pytest.mark.parametrize(("long", "seconds"), [(False, 59), (True, 3599), (False, 0)])
def test_short_interval_requires_explicit_override(long, seconds):
    with pytest.raises(ValueError, match="unsafe_min_interval"):
        FeedPoller(FeedKind.EXTRA, long=long, min_interval=seconds)
    poller = FeedPoller(FeedKind.EXTRA, long=long, min_interval=seconds, unsafe_min_interval=True)
    poller.next_request(NOW)
    poller.next_request(NOW + timedelta(seconds=seconds))


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), float("-inf")])
def test_invalid_intervals(seconds):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        FeedPoller(FeedKind.EXTRA, min_interval=seconds, unsafe_min_interval=True)


def test_interval_survives_rejected_attempts_and_clock_reversal():
    poller = FeedPoller(FeedKind.EXTRA)
    poller.next_request(NOW)
    for seconds in [-1, 30, 59]:
        with pytest.raises(TooFrequentError):
            poller.next_request(NOW + timedelta(seconds=seconds))
    # Different UTC offsets represent the same instants for rate limiting.
    poller.next_request((NOW + timedelta(seconds=60)).astimezone(timezone(timedelta(hours=9))))


def test_naive_clock_is_rejected_without_consuming_attempt():
    poller = FeedPoller(FeedKind.EXTRA)
    with pytest.raises(ValueError, match="timezone"):
        poller.next_request(datetime(2026, 11, 12))
    poller.next_request(NOW)
    with pytest.raises(ValueError, match="timezone"):
        poller.handle_response(HttpResponse(304, {}, b""), datetime(2026, 11, 12))


def test_entry_request_has_user_agent_and_no_feed_validators():
    poller = FeedPoller(FeedKind.REGULAR)
    entries = poller.handle_response(recorded("regular"), NOW)
    feed_request = poller.next_request(NOW)
    assert "If-None-Match" in feed_request.headers
    for entry in entries[:2]:
        request = poller.entry_request(entry)
        assert request.method == "GET"
        assert request.url == entry.url
        assert request.headers["User-Agent"] == feed_request.headers["User-Agent"]
        assert "If-None-Match" not in request.headers
        assert "If-Modified-Since" not in request.headers


def test_case_insensitive_headers_and_304_validator_updates():
    poller = FeedPoller(FeedKind.EXTRA)
    poller.handle_response(
        HttpResponse(200, {"eTaG": 'W/"first"', "LAST-MODIFIED": "original"}, feed()), NOW
    )
    poller.handle_response(HttpResponse(304, {}, b"not XML"), NOW)
    poller.handle_response(HttpResponse(304, {"etag": 'W/"second"'}, b""), NOW)
    headers = poller.next_request(NOW).headers
    assert headers["If-None-Match"] == 'W/"second"'
    assert headers["If-Modified-Since"] == "original"


def test_success_without_validators_clears_old_values():
    poller = FeedPoller(FeedKind.EXTRA)
    poller.handle_response(recorded("extra"), NOW)
    poller.handle_response(HttpResponse(200, {}, feed()), NOW)
    headers = poller.next_request(NOW).headers
    assert "If-None-Match" not in headers
    assert "If-Modified-Since" not in headers


def test_duplicate_ids_within_and_across_responses_and_injected_empty_store():
    seen: set[str] = set()
    poller = FeedPoller(FeedKind.EXTRA, seen=seen)
    response = HttpResponse(200, {}, feed("a", "a", "b", "a"))
    assert [entry.id for entry in poller.handle_response(response, NOW)] == ["a", "b"]
    assert seen == {"a", "b"}
    assert poller.handle_response(response, NOW) == []
    restarted = FeedPoller(FeedKind.EXTRA, seen=seen)
    assert restarted.handle_response(response, NOW) == []


def test_default_store_is_bounded_lru_and_batch_duplicates_do_not_reappear():
    poller = FeedPoller(FeedKind.EXTRA)
    ids = [str(number) for number in range(10_000)]
    assert len(poller.handle_response(HttpResponse(200, {}, feed(*ids)), NOW)) == 10_000
    # Refresh 0, so adding 10000 evicts 1 rather than 0.
    assert poller.handle_response(HttpResponse(200, {}, feed("0")), NOW) == []
    poller.handle_response(HttpResponse(200, {}, feed("10000")), NOW)
    assert poller.handle_response(HttpResponse(200, {}, feed("0")), NOW) == []
    assert [e.id for e in poller.handle_response(HttpResponse(200, {}, feed("1")), NOW)] == ["1"]
    other = FeedPoller(FeedKind.EXTRA)
    batch = HttpResponse(200, {}, feed(*ids, "10000", "0"))
    assert len(other.handle_response(batch, NOW)) == 10_001


@pytest.mark.parametrize("status", [204, 301, 400, 429, 500])
def test_non_success_status_does_not_change_state(status):
    poller = FeedPoller(FeedKind.EXTRA)
    poller.handle_response(HttpResponse(200, {"ETag": '"valid"'}, feed()), NOW)
    with pytest.raises(HttpStatusError) as error:
        poller.handle_response(HttpResponse(status, {"ETag": '"bad"'}, feed("a")), NOW)
    assert error.value.status == status
    assert poller.next_request(NOW).headers["If-None-Match"] == '"valid"'
    assert len(poller.handle_response(HttpResponse(200, {}, feed("a")), NOW)) == 1


@pytest.mark.parametrize(
    "body",
    [b"", b"<feed>", b"<feed/>", b'<feed xmlns="urn:wrong"/>'],
)
def test_invalid_atom(body):
    with pytest.raises(FeedParseError):
        FeedPoller(FeedKind.EXTRA).handle_response(HttpResponse(200, {}, body), NOW)


@pytest.mark.parametrize("field", ["id", "title", "updated", "author", "link"])
def test_incomplete_feed_does_not_partially_commit(field):
    seen: set[str] = set()
    poller = FeedPoller(FeedKind.EXTRA, seen=seen)
    poller.handle_response(HttpResponse(200, {"ETag": '"old"'}, feed()), NOW)
    root = ET.fromstring(feed("valid", "broken"))
    node = root.findall(ATOM + "entry")[1]
    child = node.find(ATOM + field)
    assert child is not None
    node.remove(child)
    with pytest.raises(FeedParseError):
        poller.handle_response(HttpResponse(200, {"ETag": '"new"'}, ET.tostring(root)), NOW)
    assert seen == set()
    assert poller.next_request(NOW).headers["If-None-Match"] == '"old"'


@pytest.mark.parametrize("timestamp", ["not-a-date", "2026-11-12T00:00:00"])
def test_invalid_entry_timestamp(timestamp):
    root = ET.fromstring(feed("a"))
    updated = root.find(ATOM + "entry/" + ATOM + "updated")
    assert updated is not None
    updated.text = timestamp
    with pytest.raises(FeedParseError):
        FeedPoller(FeedKind.EXTRA).handle_response(HttpResponse(200, {}, ET.tostring(root)), NOW)


def test_atom_feed_author_and_default_link_relation():
    root = ET.fromstring(feed("a"))
    entry = root.find(ATOM + "entry")
    assert entry is not None
    author = entry.find(ATOM + "author")
    assert author is not None
    entry.remove(author)
    root.append(author)
    entry.insert(0, ET.Element(ATOM + "link", {"rel": "self", "href": "ignored"}))
    result = FeedPoller(FeedKind.EXTRA).handle_response(
        HttpResponse(200, {}, ET.tostring(root)), NOW
    )
    assert result[0].author == "テスト発表官署"
    assert result[0].url == "https://example.test/a.xml"


def test_message_headers_are_snapshots():
    headers = {"ETag": '"one"'}
    request = HttpRequest("GET", "https://example.test/feed", headers)
    response = HttpResponse(200, headers, b"body")
    headers["ETag"] = '"two"'
    assert request.headers["ETag"] == response.headers["ETag"] == '"one"'


def test_core_has_no_network_clock_or_thread_imports():
    path = Path(__file__).parents[1] / "jmadantic" / "feed" / "_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & {"urllib", "httpx", "time", "socket", "threading", "asyncio"}
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "utcnow", "today", "sleep"}
        for node in ast.walk(tree)
    )
