"""Show named warning areas once, with an offline replay option."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from pyjmaxml import Tracker, parse
from pyjmaxml.feed import HttpRequest, HttpResponse


class OfflineSample:
    """Serve the bundled Hokkaido sample for one synthetic EXTRA entry."""

    def __init__(self) -> None:
        path = Path(__file__).resolve().parents[1] / "tests/data/samples/15_16_03_241226_VPWW55.xml"
        self.body = path.read_bytes()
        report = parse(self.body)
        self.now = report.control.date_time
        self.url = "https://example.invalid/warning_011000.xml"
        atom = "{http://www.w3.org/2005/Atom}"
        feed = ET.Element(atom + "feed")
        entry = ET.SubElement(feed, atom + "entry")
        for key, value in (
            ("id", self.url),
            ("title", report.control.title),
            ("updated", self.now.isoformat()),
        ):
            ET.SubElement(entry, atom + key).text = value
        author = ET.SubElement(entry, atom + "author")
        ET.SubElement(author, atom + "name").text = "オフラインサンプル"
        ET.SubElement(entry, atom + "link", {"href": self.url})
        self.feed = ET.tostring(feed)

    def send(self, req: HttpRequest) -> HttpResponse:
        if req.url == self.url:
            return HttpResponse(200, {}, self.body)
        if req.url.endswith("/extra_l.xml"):
            return HttpResponse(200, {}, self.feed)
        return HttpResponse(304, {}, b"")

    def clock(self) -> datetime:
        return self.now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-sample", action="store_true")
    args = parser.parse_args()
    http = OfflineSample() if args.offline_sample else None
    clock: Callable[[], datetime] | None = None
    if http is not None:
        clock = http.clock
        print("録画済みサンプルの再生です。現在の発表状況ではありません。")
    tracker = Tracker(
        ["北海道稚内市"], http=http, clock=clock, user_agent="track-areas-example/0.1.0"
    )
    result = tracker.update()
    view = tracker.area("北海道稚内市")
    print(view.name, sorted(kind.name for kind in view.warnings))
    for error in result.errors:
        print("取得失敗:", error)
    print("出典：気象庁ホームページ（https://xml.kishou.go.jp/xmlpull.html）")
    print("気象庁の防災情報XMLを、このサンプルの実行者が加工して作成")


if __name__ == "__main__":
    main()
