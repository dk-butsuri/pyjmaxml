"""Poll once; optionally replay a local XML without network access."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from pyjmaxml import ParseError, WarningState, parse
from pyjmaxml.feed import FeedClient, FeedError, FeedKind, HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


def update_once(client: FeedClient, state: WarningState, *, now: datetime | None = None) -> None:
    for entry in client.poll():
        try:
            data = client.fetch(entry)
        except FeedError:
            logger.exception("取得失敗（未ack・次回再取得）: %s", entry.id)
            continue
        try:
            report = parse(data)
        except ParseError:
            logger.exception("解析できない電文をackして除外: %s", entry.id)
            client.ack(entry)
            continue
        try:
            state.apply(report, now=now)
        except ValueError:
            logger.exception("状態に適用できない電文をackして除外: %s", entry.id)
        client.ack(entry)


class LocalSampleHttp:
    """Return a synthetic Atom entry and a local sample; perform no I/O over HTTP."""

    def __init__(self, path: Path) -> None:
        self.body = path.read_bytes()
        self.report_url = "https://example.invalid/local-sample.xml"
        atom = "{http://www.w3.org/2005/Atom}"
        root = ET.Element(atom + "feed")
        entry = ET.SubElement(root, atom + "entry")
        for key, value in (
            ("id", "local-sample"),
            ("title", "録画済みの電文"),
            ("updated", "2000-01-01T00:00:00Z"),
        ):
            ET.SubElement(entry, atom + key).text = value
        author = ET.SubElement(entry, atom + "author")
        ET.SubElement(author, atom + "name").text = "オフラインサンプル"
        ET.SubElement(entry, atom + "link", {"href": self.report_url})
        self.feed = ET.tostring(root)

    def send(self, req: HttpRequest) -> HttpResponse:
        return HttpResponse(200, {}, self.body if req.url == self.report_url else self.feed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="0121400")
    parser.add_argument("--offline-sample", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    http = LocalSampleHttp(args.offline_sample) if args.offline_sample else None
    client = FeedClient(FeedKind.EXTRA, http=http, user_agent="warning-example/0.1.0")
    state = WarningState()
    update_once(client, state, now=None if args.offline_sample else datetime.now(UTC))
    source = "https://xml.kishou.go.jp/xmlpull.html"
    if args.offline_sample:
        print("録画済みサンプルの再生です。現在の発表状況ではありません。")
        source = "https://xml.kishou.go.jp/tec_material.html"
    print(f"出典：気象庁ホームページ（{source}）")
    print("気象庁の防災情報XMLを、このサンプルの実行者が加工して作成")
    print(args.city, sorted(kind.name for kind in state.by_city(args.city)))


if __name__ == "__main__":
    main()
