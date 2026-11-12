"""Earthquake information from 震度速報 (VXSE51), 震源に関する情報 (VXSE52) and
震源・震度に関する情報 (VXSE53)."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Literal, cast

from xsdata.models.datatype import XmlDateTime

from .._generated.jmx import TypeCommentForm, TypeEarthquake, TypeIntensityDetail
from ..kinds import data_type_code
from ..parse import Report, SeisBody

_LOGGER = logging.getLogger(__name__)
_GROUPS = frozenset({"VXSE51", "VXSE52", "VXSE53"})
# Reported instead of an intensity when a station likely saw 5- or more but has not reported.
_UNRECEIVED = "震度５弱以上未入電"
# ISO 6709 as used by JMA: latitude, longitude and an optional height in metres.
_COORDINATE = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?/")


class Intensity(IntEnum):
    """Seismic intensity (震度) in ascending order.

    The values are ranks, not intensities: FIVE_UPPER is 6. str() and f-strings
    therefore print the label ('震度5強') instead of the number.
    """

    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE_LOWER = 5
    FIVE_UPPER = 6
    SIX_LOWER = 7
    SIX_UPPER = 8
    SEVEN = 9

    @property
    def label(self) -> str:
        """Japanese label such as '震度5弱'."""
        return _LABELS[self]

    def __str__(self) -> str:
        return self.label

    def __format__(self, format_spec: str) -> str:
        return format(self.label, format_spec)


_INTENSITIES = {
    "1": Intensity.ONE,
    "2": Intensity.TWO,
    "3": Intensity.THREE,
    "4": Intensity.FOUR,
    "5-": Intensity.FIVE_LOWER,
    "5+": Intensity.FIVE_UPPER,
    "6-": Intensity.SIX_LOWER,
    "6+": Intensity.SIX_UPPER,
    "7": Intensity.SEVEN,
}
_LABELS = {
    intensity: "震度" + code.replace("-", "弱").replace("+", "強")
    for code, intensity in _INTENSITIES.items()
}


@dataclass(frozen=True)
class Hypocenter:
    """Epicentre name and position; depth_km is 0 for ごく浅い and None when unknown."""

    name: str
    code: str
    detailed_name: str
    latitude: float | None
    longitude: float | None
    depth_km: float | None
    description: str


@dataclass(frozen=True)
class Magnitude:
    """value is None when the magnitude is not determined (e.g. Ｍ８を超える巨大地震)."""

    value: float | None
    type: str
    condition: str
    description: str


@dataclass(frozen=True)
class IntensityCell:
    """Observed intensity of a prefecture, area, city or station.

    unreceived marks 震度５弱以上未入電: some stations likely saw 5- or more but have not
    reported, so intensity is None or covers only the stations that did. raw keeps the
    original text. Codes above the cell's level are filled in, lower ones
    are empty.
    """

    level: Literal["pref", "area", "city", "station"]
    code: str
    name: str
    pref_code: str
    area_code: str
    city_code: str
    intensity: Intensity | None
    unreceived: bool
    raw: str
    revise: str


@dataclass(frozen=True)
class EarthquakeInfo:
    group: Literal["VXSE51", "VXSE52", "VXSE53"]
    info_type: str
    event_id: str
    serial: str
    report_date_time: datetime
    origin_time: datetime | None
    arrival_time: datetime | None
    hypocenter: Hypocenter | None
    magnitude: Magnitude | None
    max_intensity: Intensity | None
    intensities: tuple[IntensityCell, ...]
    forecast_comment: str
    forecast_comment_codes: tuple[str, ...]
    var_comment: str
    free_form_comment: str
    text: str

    def by_area(self, code: str) -> tuple[IntensityCell, ...]:
        """The area cell and everything below it, for an 地震情報／細分区域 code such as 211."""
        return tuple(cell for cell in self.intensities if cell.area_code == code)

    def by_city(self, code: str) -> tuple[IntensityCell, ...]:
        """The city cell and its stations; VXSE51 has no cities and matches nothing."""
        return tuple(cell for cell in self.intensities if cell.city_code == code)


def _intensity(raw: str | None, condition: str | None = None) -> tuple[Intensity | None, bool, str]:
    # The unreceived note is either the value itself (stations) or a Condition next to
    # MaxInt, which then covers only the stations that did report.
    text = (raw or "").strip()
    unreceived = text == _UNRECEIVED or condition == _UNRECEIVED
    intensity = _INTENSITIES.get(text)
    if intensity is None and text and text != _UNRECEIVED:
        _LOGGER.warning("Unknown seismic intensity %r", text)
    return intensity, unreceived, text or (condition or "")


def _time(value: XmlDateTime | None) -> datetime | None:
    if value is None:
        return None
    result = value.to_datetime()
    if result.utcoffset() is None:
        raise ValueError("Earthquake time must include a timezone")
    return result


def _hypocenter(earthquake: TypeEarthquake) -> Hypocenter | None:
    if earthquake.hypocenter is None:
        return None
    area = earthquake.hypocenter.area
    # Old reports may add a Tokyo-datum copy; prefer the default (WGS) coordinate.
    coordinates = sorted(area.coordinate, key=lambda c: c.datum is not None)
    latitude = longitude = depth = None
    description = ""
    if coordinates:
        coordinate = coordinates[0]
        description = coordinate.description or ""
        if coordinate.value:
            match = _COORDINATE.fullmatch(coordinate.value)
            if match is None:
                raise ValueError(f"Unsupported hypocenter coordinate {coordinate.value!r}")
            latitude, longitude = float(match[1]), float(match[2])
            # Height is negative below sea level; + 0.0 turns ごく浅い (+0) into 0.0, not -0.0.
            depth = None if match[3] is None else -float(match[3]) / 1000 + 0.0
    return Hypocenter(
        area.name,
        area.code.value,
        area.detailed_name or "",
        latitude,
        longitude,
        depth,
        description,
    )


def _magnitude(earthquake: TypeEarthquake) -> Magnitude | None:
    if not earthquake.magnitude:
        return None
    magnitude = earthquake.magnitude[0]
    value = None if math.isnan(magnitude.value) else magnitude.value
    return Magnitude(
        value,
        magnitude.type_value,
        magnitude.condition or "",
        magnitude.description or "",
    )


def _cells(observation: TypeIntensityDetail) -> list[IntensityCell]:
    cells: list[IntensityCell] = []
    for pref in observation.pref:
        cells.append(
            IntensityCell(
                "pref",
                pref.code,
                pref.name,
                pref.code,
                "",
                "",
                *_intensity(pref.max_int, pref.condition),
                pref.revise or "",
            )
        )
        for area in pref.area:
            cells.append(
                IntensityCell(
                    "area",
                    area.code,
                    area.name,
                    pref.code,
                    area.code,
                    "",
                    *_intensity(area.max_int, area.condition),
                    area.revise or "",
                )
            )
            for city in area.city:
                cells.append(
                    IntensityCell(
                        "city",
                        city.code,
                        city.name,
                        pref.code,
                        area.code,
                        city.code,
                        *_intensity(city.max_int, city.condition),
                        city.revise or "",
                    )
                )
                for station in city.intensity_station:
                    cells.append(
                        IntensityCell(
                            "station",
                            station.code,
                            station.name,
                            pref.code,
                            area.code,
                            city.code,
                            *_intensity(station.int_value),
                            station.revise or "",
                        )
                    )
    return cells


def _comment(comment: TypeCommentForm | None) -> tuple[str, tuple[str, ...]]:
    if comment is None:
        return "", ()
    return comment.text, tuple(code for codes in comment.code for code in codes.split())


def earthquake_info(report: Report) -> EarthquakeInfo:
    """Flatten a VXSE51, VXSE52 or VXSE53 report; Control/Status is not checked.

    A cancellation (InfoType 取消) has only text; check info_type before using it.
    """
    group = data_type_code(report)
    if group not in _GROUPS:
        raise ValueError(f"Not an earthquake information report: {report.control.title}")
    body = report.body
    if not isinstance(body, SeisBody):
        raise ValueError("Earthquake information reports require a seismology Body")
    if len(body.earthquake) > 1:
        raise ValueError("Earthquake information with several Earthquake elements")
    earthquake = body.earthquake[0] if body.earthquake else None
    observation = body.intensity.observation if body.intensity is not None else None
    comments = body.comments
    forecast, forecast_codes = _comment(comments.forecast_comment if comments else None)
    var, _ = _comment(comments.var_comment if comments else None)
    return EarthquakeInfo(
        cast(Literal["VXSE51", "VXSE52", "VXSE53"], group),
        report.head.info_type,
        report.head.event_id or "",
        report.head.serial or "",
        report.head.report_date_time,
        _time(earthquake.origin_time) if earthquake else None,
        _time(earthquake.arrival_time) if earthquake else None,
        _hypocenter(earthquake) if earthquake else None,
        _magnitude(earthquake) if earthquake else None,
        _intensity(observation.max_int)[0] if observation else None,
        tuple(_cells(observation)) if observation else (),
        forecast,
        forecast_codes,
        var,
        (comments.free_form_comment or "") if comments else "",
        body.text or "",
    )
