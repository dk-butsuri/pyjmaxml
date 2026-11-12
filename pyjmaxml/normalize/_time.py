"""TimeDefine helpers shared by the time-series normalizers."""

from __future__ import annotations

from datetime import datetime, timedelta

from xsdata.models.datatype import XmlDuration

from .._generated.jmx import TypeTimeSeriesInfo


def duration(value: XmlDuration | None) -> timedelta | None:
    if value is None:
        return None
    if value.years or value.months:
        raise ValueError(f"TimeDefine/Duration has a calendar duration: {value}")
    result = timedelta(
        days=value.days or 0,
        hours=value.hours or 0,
        minutes=value.minutes or 0,
        seconds=value.seconds or 0,
    )
    return -result if value.negative else result


def periods(series: TypeTimeSeriesInfo) -> dict[int, tuple[datetime, timedelta | None, str]]:
    """Map timeId to (aware start, duration, name or '')."""
    result: dict[int, tuple[datetime, timedelta | None, str]] = {}
    for define in series.time_defines.time_define:
        start = define.date_time.value.to_datetime()
        if start.utcoffset() is None:
            raise ValueError("TimeDefine/DateTime must include a timezone")
        result[define.time_id] = (start, duration(define.duration), define.name or "")
    return result
