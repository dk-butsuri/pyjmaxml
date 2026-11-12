from email.parser import Parser
from pathlib import Path
from xml.etree import ElementTree as ET

from pyjmaxml.feed import HttpResponse

DATA = Path(__file__).parent / "data" / "feed"
ATOM = "{http://www.w3.org/2005/Atom}"


def recorded(kind: str, status: int = 200) -> HttpResponse:
    suffix = ".304" if status == 304 else ""
    text = (DATA / f"{kind}{suffix}.headers.txt").read_text(encoding="utf-8")
    status_line, headers = text.split("\n", 1)
    assert int(status_line.split()[1]) == status
    body = (DATA / f"{kind}.xml").read_bytes() if status == 200 else b""
    return HttpResponse(status, dict(Parser().parsestr(headers).items()), body)


def feed(*ids: str) -> bytes:
    root = ET.Element(ATOM + "feed")
    for entry_id in ids:
        entry = ET.SubElement(root, ATOM + "entry")
        for name, value in [
            ("id", entry_id),
            ("title", "テスト電文"),
            ("updated", "2026-11-12T00:00:00+09:00"),
        ]:
            ET.SubElement(entry, ATOM + name).text = value
        author = ET.SubElement(entry, ATOM + "author")
        ET.SubElement(author, ATOM + "name").text = "テスト発表官署"
        ET.SubElement(
            entry,
            ATOM + "link",
            {"href": f"https://example.test/{entry_id}.xml", "type": "application/xml"},
        )
    return ET.tostring(root)
