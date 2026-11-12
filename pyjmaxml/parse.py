"""Parse JMA XML into generated bodies and immutable report metadata."""

from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeAlias
from xml.etree import ElementTree

from xsdata.exceptions import ParserError
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.models.datatype import XmlDateTime

from ._generated.aliases import MeteBody, SeisBody, VolcBody
from ._generated.jmx import Report as RawReport

_REPORT_NAMESPACE = "http://xml.kishou.go.jp/jmaxml1/"
_BODY_TYPES = {
    MeteBody.Meta.namespace: MeteBody,
    SeisBody.Meta.namespace: SeisBody,
    VolcBody.Meta.namespace: VolcBody,
}


class ParseError(ValueError):
    """The XML cannot be bound to a JMA report under the selected parse mode."""


@dataclass(frozen=True)
class UnknownBody:
    """A Body extension whose namespace is not part of the pinned JMA schemas."""

    namespace: str
    xml: bytes


Body: TypeAlias = MeteBody | SeisBody | VolcBody | UnknownBody


@dataclass(frozen=True)
class Control:
    title: str
    date_time: datetime
    status: str
    editorial_office: str
    publishing_office: str


@dataclass(frozen=True)
class Head:
    title: str
    report_date_time: datetime
    target_date_time: datetime | None
    event_id: str
    info_type: str
    serial: str
    info_kind: str
    info_kind_version: str
    headline_text: str


@dataclass(frozen=True)
class Report:
    control: Control
    head: Head
    body: Body
    raw: RawReport


def _datetime(value: XmlDateTime) -> datetime:
    result = value.to_datetime()
    if result.utcoffset() is None:
        raise ParseError("JMA report timestamps must include a timezone")
    return result


def parse(data: bytes | str | os.PathLike[str], *, strict: bool = False) -> Report:
    """Parse XML text, bytes (optionally gzip-compressed), or an explicit path.

    A string is XML text; use pathlib.Path for a filename. Strict mode rejects
    unknown properties and failed value conversions. It is not XSD validation.
    """
    if isinstance(data, os.PathLike):
        content = Path(data).read_bytes()
    elif isinstance(data, str):
        content = data.encode("utf-8")
    else:
        content = data

    try:
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
        # xsdata's lxml handler uses recover=True. Validate well-formedness
        # before binding so truncated XML cannot silently produce a report.
        root = ElementTree.fromstring(content)
        if root.tag != f"{{{_REPORT_NAMESPACE}}}Report":
            raise ParseError("Expected a JMA Report root element")
        bodies = [child for child in root if child.tag.rsplit("}", 1)[-1] == "Body"]
        if len(bodies) != 1:
            raise ParseError("Expected exactly one Body element")
        body_xml = bodies[0]
        namespace = body_xml.tag[1:].partition("}")[0] if "}" in body_xml.tag else ""
        expected_body = _BODY_TYPES.get(namespace)
        if expected_body is None and strict:
            raise ParseError(f"Unknown Body namespace: {namespace!r}")
        unknown_xml = ElementTree.tostring(body_xml, encoding="utf-8")
        parser = XmlParser(
            context=XmlContext(models_package="pyjmaxml._generated"),
            config=ParserConfig(
                fail_on_unknown_properties=strict,
                fail_on_converter_warnings=strict,
            ),
        )
        raw = parser.from_bytes(content, RawReport)
        body: Body
        if expected_body is None:
            body = UnknownBody(namespace, unknown_xml)
        elif isinstance(raw.other_element, (MeteBody, SeisBody, VolcBody)):
            body = raw.other_element
            if body.Meta.namespace != namespace:
                raise ParseError("Body model does not match its namespace")
        else:
            raise ParseError(f"Body could not be resolved for namespace {namespace!r}")

        control, head = raw.control, raw.head
        return Report(
            control=Control(
                title=control.title,
                date_time=_datetime(control.date_time),
                status=(
                    control.status if isinstance(control.status, str) else control.status.value
                ),
                editorial_office=control.editorial_office,
                publishing_office=" ".join(control.publishing_office),
            ),
            head=Head(
                title=head.title,
                report_date_time=_datetime(head.report_date_time),
                target_date_time=(
                    _datetime(head.target_date_time) if head.target_date_time is not None else None
                ),
                event_id=head.event_id or "",
                info_type=head.info_type,
                serial=head.serial or "",
                info_kind=head.info_kind,
                info_kind_version=head.info_kind_version,
                headline_text=head.headline.text or "",
            ),
            body=body,
            raw=raw,
        )
    except ParseError:
        raise
    except (ElementTree.ParseError, ParserError, TypeError, ValueError, EOFError, OSError) as exc:
        raise ParseError(f"Cannot parse JMA report: {exc}") from exc
