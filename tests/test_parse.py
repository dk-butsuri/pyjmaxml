import gzip
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from jmadantic import MeteBody, ParseError, UnknownBody, data_type_code, parse

SAMPLES = Path(__file__).parent / "data" / "samples"
SOURCE = SAMPLES / "15_16_03_241226_VPWW55.xml"
REPORT_NS = "http://xml.kishou.go.jp/jmaxml1/"
HEAD_NS = "http://xml.kishou.go.jp/jmaxml1/informationBasis1/"
METE_NS = "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/"


@pytest.mark.parametrize("form", ["bytes", "text", "gzip", "gzip-path", "path"])
def test_input_forms_and_metadata(form, tmp_path):
    xml = SOURCE.read_bytes()
    if form == "gzip-path":
        data = tmp_path / "report.xml.gz"
        data.write_bytes(gzip.compress(xml))
    else:
        data = {
            "bytes": xml,
            "text": xml.decode("utf-8"),
            "gzip": gzip.compress(xml),
            "path": SOURCE,
        }[form]
    report = parse(data, strict=True)
    assert isinstance(report.body, MeteBody)
    assert report.body is report.raw.other_element
    assert data_type_code(report) == "VPWW55"
    assert report.control.status == "通常"
    assert report.control.publishing_office == "稚内地方気象台"
    assert report.control.date_time.utcoffset() == timedelta(0)
    assert report.head.report_date_time.utcoffset() == timedelta(hours=9)
    assert report.head.event_id == report.head.serial == ""
    assert "大雨" in report.head.headline_text


def test_unknown_body_is_preserved_but_rejected_in_strict_mode():
    root = ET.fromstring(SOURCE.read_bytes())
    original = root.find(f"{{{METE_NS}}}Body")
    assert original is not None
    root.remove(original)
    body = ET.SubElement(root, "{urn:future:jma}Body", {"version": "2"})
    ET.SubElement(body, "{urn:future:jma}Value").text = "extension"
    xml = ET.tostring(root)
    report = parse(xml)
    assert isinstance(report.body, UnknownBody)
    assert report.body.namespace == "urn:future:jma"
    restored = ET.fromstring(report.body.xml)
    assert restored.tag == body.tag
    assert restored.attrib == body.attrib
    assert restored.findtext("{urn:future:jma}Value") == "extension"
    with pytest.raises(ParseError, match="Unknown Body namespace"):
        parse(xml, strict=True)


def test_unknown_property_obeys_strict_mode():
    root = ET.fromstring(SOURCE.read_bytes())
    control = root.find(f"{{{REPORT_NS}}}Control")
    assert control is not None
    ET.SubElement(control, f"{{{REPORT_NS}}}FutureProperty").text = "new"
    xml = ET.tostring(root)
    assert parse(xml).control.title.startswith("気象警報")
    with pytest.raises(ParseError, match="FutureProperty"):
        parse(xml, strict=True)


def test_invalid_numeric_value_is_rejected_in_strict_mode():
    source = SAMPLES / "09_01_01_091210_VPTW40.xml"
    root = ET.fromstring(source.read_bytes())
    speed = next(root.iter("{http://xml.kishou.go.jp/jmaxml1/elementBasis1/}Speed"))
    speed.text = "not-a-number"
    with pytest.raises(ParseError):
        parse(ET.tostring(root), strict=True)


@pytest.mark.parametrize("xml", [b"", b"<Report>", b"<Other/>", SOURCE.read_bytes()[:-50]])
def test_malformed_or_non_report_xml(xml):
    with pytest.raises(ParseError):
        parse(xml)


def test_invalid_gzip():
    with pytest.raises(ParseError):
        parse(b"\x1f\x8btruncated")


def test_naive_timestamp_is_rejected():
    xml = SOURCE.read_bytes().replace(b"2020-06-22T14:00:00Z", b"2020-06-22T14:00:00")
    with pytest.raises(ParseError, match="timezone"):
        parse(xml, strict=True)


def test_nillable_target_time():
    root = ET.fromstring(SOURCE.read_bytes())
    target = root.find(f"{{{HEAD_NS}}}Head/{{{HEAD_NS}}}TargetDateTime")
    assert target is not None
    target.text = None
    target.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
    assert parse(ET.tostring(root), strict=True).head.target_date_time is None


@pytest.mark.parametrize("count", [0, 2])
def test_exactly_one_body_is_required(count):
    root = ET.fromstring(SOURCE.read_bytes())
    body = root.find(f"{{{METE_NS}}}Body")
    assert body is not None
    if count == 0:
        root.remove(body)
    else:
        ET.SubElement(root, f"{{{METE_NS}}}Body")
    with pytest.raises(ParseError, match="exactly one Body"):
        parse(ET.tostring(root))
