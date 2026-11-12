"""Offline Tracker fixtures using recorded feeds and injectable transports."""

from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from feed_helpers import ATOM, feed

from pyjmaxml import parse
from pyjmaxml.feed import Entry, HttpRequest, HttpResponse

DATA = Path(__file__).parent / "data"
BASE = "https://www.data.jma.go.jp/developer/xml/feed/"
WARNING = DATA / "samples/15_16_03_241226_VPWW55.xml"
SNAPSHOT = DATA / "samples/15_18_01_250630_VPWS50.xml"
FORECAST = DATA / "forecast/20261111073453_0_VPFD51_130000.xml"
WEEKLY = DATA / "forecast/20261111073607_0_VPFW50_130000.xml"
POSSIBILITY = DATA / "possibility/20261111073453_0_VPFD60_130000.xml"
EARLY = DATA / "possibility/20261111073453_0_VPFD61_130000.xml"
POSSIBILITY_WEEKLY = DATA / "possibility/20261111073607_0_VPFW60_130000.xml"
TIMESERIES = DATA / "timeseries/20261112075502_0_VPWP50_011000.xml"
EARTHQUAKE = DATA / "earthquake/20261107160836_0_VXSE53_010000.xml"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def entry_for(path: Path, code: str | None = None, tag: str = "") -> Entry:
    report = parse(path)
    name = path.stem + tag
    if code is not None:
        name += "_" + code
    return Entry(
        name,
        report.control.title,
        report.control.date_time,
        "offline",
        f"https://example.test/{name}.xml",
    )


def atom_entries(*entries: Entry) -> HttpResponse:
    root = ET.fromstring(feed(*(entry.id for entry in entries)))
    for node, entry in zip(root.findall(ATOM + "entry"), entries, strict=True):
        for field, value in (("title", entry.title), ("updated", entry.updated.isoformat())):
            child = node.find(ATOM + field)
            assert child is not None
            child.text = value
        link = node.find(ATOM + "link")
        assert link is not None
        link.set("href", entry.url)
    return HttpResponse(200, {}, ET.tostring(root))


class FakeHttp:
    def __init__(self) -> None:
        self.responses: dict[str, list[HttpResponse | Exception]] = {}
        self.requests: list[HttpRequest] = []

    def queue(self, url: str, *responses: HttpResponse | Exception) -> None:
        self.responses.setdefault(url, []).extend(responses)

    def document(self, path: Path, code: str | None = None, tag: str = "") -> Entry:
        entry = entry_for(path, code, tag)
        self.queue(entry.url, HttpResponse(200, {}, path.read_bytes()))
        return entry

    def send(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        queued = self.responses.get(req.url)
        if not queued:
            assert req.url.startswith(BASE), f"Unexpected report request: {req.url}"
            return HttpResponse(304, {}, b"")
        response = queued.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def counts(self) -> Counter[str]:
        return Counter(request.url for request in self.requests)


class FakeAsyncHttp:
    def __init__(self, sync: FakeHttp) -> None:
        self.sync = sync
        self.closed = False

    async def send(self, req: HttpRequest) -> HttpResponse:
        return self.sync.send(req)

    async def aclose(self) -> None:
        self.closed = True
