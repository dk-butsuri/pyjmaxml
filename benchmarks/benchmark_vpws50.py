"""Time VPWS50 apply on a fresh full state; no network or timing assertions.

Run with: uv run --offline python benchmarks/benchmark_vpws50.py --repeat 7
State reconstruction, XML parsing, and output serialization are outside timing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

from pyjmaxml import MeteBody, WarningState, parse
from pyjmaxml.codes import AREA_CITY


def full_state_json() -> str:
    """Seed all published weather cities with all seven groups in version 1."""
    payload = json.loads(WarningState().to_json())
    kinds = [
        ("VPWW55", "10", "レベル２大雨注意報"),
        ("VPWW56", "29", "レベル２土砂災害注意報"),
        ("VPWW57", "19", "レベル２高潮注意報"),
        ("VPWW58", "15", "強風注意報"),
        ("VPWW59", "16", "波浪注意報"),
        ("VPWW60", "12", "大雪注意報"),
        ("VPWW61", "14", "雷注意報"),
    ]
    payload["cells"] = [
        {
            "city": city,
            "group": group,
            "as_of": "2000-01-01T00:00:00+00:00",
            "kinds": [{"name": name, "code": code, "group": group}],
        }
        for city in sorted(AREA_CITY)
        for group, code, name in kinds
    ]
    return json.dumps(payload, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    report_path = Path(__file__).resolve().parents[1] / (
        "tests/golden/_shared/vpws50_20261112T0000.xml"
    )
    report = parse(report_path, strict=True)
    assert isinstance(report.body, MeteBody)
    serialized = full_state_json()
    durations: list[float] = []
    checksums: set[str] = set()
    change_counts: set[int] = set()
    for _ in range(args.repeat):
        state = WarningState.from_json(serialized)
        started = perf_counter()
        result = state.apply(report)
        durations.append(perf_counter() - started)
        assert result.applied and result.skip_reason is None
        change_counts.add(len(result.changes))
        checksums.add(hashlib.sha256(state.to_json().encode()).hexdigest())
    assert len(checksums) == len(change_counts) == 1
    measurements = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cities": len(AREA_CITY),
        "cells": len(json.loads(serialized)["cells"]),
        "report_items": sum(
            len(w.item)
            for w in report.body.warning
            if w.type_value == "気象警報・注意報（市町村等）"
        ),
        "repeat": args.repeat,
        "seconds": durations,
        "median_seconds": statistics.median(durations),
        "min_seconds": min(durations),
        "max_seconds": max(durations),
        "change_count": next(iter(change_counts)),
        "result_sha256": next(iter(checksums)),
    }
    text = json.dumps(measurements, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
