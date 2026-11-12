import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pyjmaxml import (
    ChangeType,
    Element,
    SkipReason,
    State,
    WarningState,
    classify_flood,
    element_in,
    level_at_least,
    parse,
)
from pyjmaxml.codes import AREA_CITY_PARENT

SHARED = Path(__file__).parent / "golden" / "_shared"
NOW = datetime(2026, 11, 12, tzinfo=UTC)
A, B, C = "0121400", "0151100", "0151200"
R = "http://xml.kishou.go.jp/jmaxml1/"
H = "http://xml.kishou.go.jp/jmaxml1/informationBasis1/"
M = "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/"
MUNICIPAL = "気象警報・注意報（市町村等）"
TITLES = {
    "VPWW55": "気象警報・注意報（Ｒ０６）（大雨）",
    "VPWW58": "気象警報・注意報（Ｒ０６）（暴風）",
    "VPWW61": "気象警報・注意報（Ｒ０６）（その他注意報）",
    "VPWS50": "気象警報・注意報（Ｒ０６）（集約通報）",
}


def at(minutes):
    return NOW + timedelta(minutes=minutes)


def kind(code, name, status="発表", time=None):
    return code, name, status, time


RAIN = kind("43", "レベル４大雨危険警報")
RAIN_LOW = kind("03", "レベル３大雨警報")
THUNDER = kind("14", "雷注意報")
NONE = kind(None, None, "発表警報・注意報はなし")


def weather(
    group="VPWW55",
    *,
    cities=None,
    issued=0,
    sent=0,
    office="office",
    event="",
    status="通常",
    serial="1",
    extra_kinds=(),
):
    """Build minimal typed reports in memory; never write fixture XML files."""
    root = ET.Element(f"{{{R}}}Report")
    control = ET.SubElement(root, f"{{{R}}}Control")
    for key, value in [
        ("Title", TITLES[group]),
        ("DateTime", at(sent).isoformat()),
        ("Status", status),
        ("EditorialOffice", office),
        ("PublishingOffice", office),
    ]:
        ET.SubElement(control, f"{{{R}}}{key}").text = value
    head = ET.SubElement(root, f"{{{H}}}Head")
    for key, value in [
        ("Title", "test"),
        ("ReportDateTime", at(issued).isoformat()),
        ("TargetDateTime", at(issued).isoformat()),
        ("EventID", event),
        ("InfoType", "発表"),
        ("Serial", serial),
        ("InfoKind", "気象警報・注意報"),
        ("InfoKindVersion", "1.5_0"),
    ]:
        ET.SubElement(head, f"{{{H}}}{key}").text = value
    headline = ET.SubElement(head, f"{{{H}}}Headline")
    ET.SubElement(headline, f"{{{H}}}Text").text = "test"
    body = ET.SubElement(root, f"{{{M}}}Body")

    def add_warning(warning_type, items):
        warning = ET.SubElement(body, f"{{{M}}}Warning", {"type": warning_type})
        for city, kinds in items.items():
            item = ET.SubElement(warning, f"{{{M}}}Item")
            for code, name, state, stamp in kinds:
                node = ET.SubElement(item, f"{{{M}}}Kind")
                for key, value in [("Name", name), ("Code", code), ("Status", state)]:
                    if value is not None:
                        ET.SubElement(node, f"{{{M}}}{key}").text = value
                if stamp is not None:
                    ET.SubElement(node, f"{{{M}}}DateTime", {"type": "発表時刻"}).text = at(
                        stamp
                    ).isoformat()
            area = ET.SubElement(item, f"{{{M}}}Area")
            ET.SubElement(area, f"{{{M}}}Name").text = "test city"
            ET.SubElement(area, f"{{{M}}}Code").text = city

    if cities is not None:
        add_warning(MUNICIPAL, cities)
    if extra_kinds:
        add_warning("気象警報・注意報（府県予報区等）", {"011000": extra_kinds})
    return parse(ET.tostring(root), strict=True)


def names(kinds):
    return {k.name for k in kinds}


def test_split_city_river_coverage_uses_published_parent_map():
    state = WarningState()
    state.apply(parse(SHARED / "vxsu_8201813100_l2.xml", strict=True))
    expected = frozenset({classify_flood("21", "レベル２氾濫注意報", "VXSU")})
    for code in ["0442100", "0442101", "0442102"]:
        assert state.by_city(code) == expected
        assert state.cities()[code] == expected
    river = state.rivers()["8201813100"]
    assert "0442100" in river.cities
    assert "0442101" not in river.cities
    assert "0442199" not in AREA_CITY_PARENT
    assert state.by_city("0442199") == frozenset()


def test_parent_query_does_not_union_split_weather_cells():
    state = WarningState()
    state.apply(weather(cities={"0442101": [RAIN]}))
    assert state.by_city("0442100") == frozenset()
    assert "0442100" not in state.cities()
    state.apply(parse(SHARED / "vxsu_8201813100_l2.xml", strict=True))
    assert names(state.by_city("0442101")) == {RAIN[1], "レベル２氾濫注意報"}
    assert names(state.by_city("0442100")) == {"レベル２氾濫注意報"}
    assert names(state.by_city("0442102")) == {"レベル２氾濫注意報"}


def test_skip_precedence_and_equal_control_timestamp():
    state = WarningState()
    first = weather(cities={A: [RAIN]}, sent=10)
    state.apply(first)
    state.apply(weather(cities={A: [RAIN_LOW]}, sent=20, issued=1))
    assert state.apply(first).skip_reason == SkipReason.DUPLICATE
    equal_time_different_serial = weather(cities={A: [RAIN]}, sent=20, serial="2")
    assert state.apply(equal_time_different_serial).skip_reason == SkipReason.STALE
    unsupported = replace(first, control=replace(first.control, title="unsupported"))
    assert state.apply(unsupported).skip_reason == SkipReason.UNSUPPORTED
    training = replace(unsupported, control=replace(unsupported.control, status="訓練"))
    assert state.apply(training).skip_reason == SkipReason.STATUS
    assert state.last_updated == at(20)


@pytest.mark.parametrize("field", ["office", "event"])
def test_information_units_include_office_and_event(field):
    state = WarningState()
    first = weather(cities={A: [RAIN]}, sent=10)
    state.apply(first)
    independent = weather(cities={A: [RAIN_LOW]}, sent=5, issued=1, **{field: "different"})
    assert state.apply(independent).applied
    assert state.last_updated == at(5)  # Last applied, not the maximum timestamp.


def test_custom_statuses_and_status_identity_survive_serialization():
    state = WarningState(accept_status={"通常", "訓練"})
    state.apply(weather(cities={A: [RAIN]}, sent=10, status="通常"))
    training = weather(cities={B: [RAIN_LOW]}, sent=5, status="訓練")
    assert state.apply(training).applied
    restored = WarningState.from_json(state.to_json())
    assert restored.apply(training).skip_reason == SkipReason.DUPLICATE
    assert restored.apply(weather(status="試験", sent=100)).skip_reason == SkipReason.STATUS
    assert restored.last_updated == at(5)


def test_vpww_cell_timestamp_is_separate_from_control_timestamp():
    state = WarningState()
    state.apply(weather("VPWS50", cities={A: [kind("43", RAIN[1], time=20)]}, sent=10))
    older_content = weather(cities={A: [RAIN_LOW]}, sent=11, issued=19)
    result = state.apply(older_content)
    assert result.applied and result.changes == ()
    assert names(state.by_city(A)) == {RAIN[1]}
    assert state.last_updated == at(11)
    equal_content_time = weather(cities={A: [RAIN_LOW]}, sent=12, issued=20)
    change = state.apply(equal_content_time).changes[0]
    assert change.type == ChangeType.DOWNGRADED
    assert change.at == at(20)
    assert names(change.before) == {RAIN[1]} and names(change.after) == {RAIN_LOW[1]}


def test_snapshot_group_uses_maximum_kind_time():
    state = WarningState()
    wind = kind("15", "強風注意報", time=10)
    snow = kind("13", "風雪注意報", time=20)
    state.apply(weather("VPWS50", cities={A: [wind, snow]}, sent=25))
    replacement = kind("05", "暴風警報")
    assert (
        state.apply(weather("VPWW58", cities={A: [replacement]}, issued=19, sent=30)).changes == ()
    )
    change = state.apply(weather("VPWW58", cities={A: [replacement]}, issued=20, sent=31)).changes[
        0
    ]
    assert change.type == ChangeType.UPGRADED and change.at == at(20)
    assert names(change.before) == {"強風注意報", "風雪注意報"}


def test_snapshot_watermark_uses_all_kind_timestamps_and_leaves_missing_cities():
    state = WarningState()
    state.apply(weather("VPWW61", cities={A: [THUNDER], B: [THUNDER]}, issued=15, sent=15))
    result = state.apply(
        weather(
            "VPWS50",
            cities={A: [kind("03", RAIN_LOW[1], time=10)]},
            issued=40,
            sent=40,
            extra_kinds=[kind("43", RAIN[1], time=20)],
        )
    )
    assert names(state.by_city(A)) == {RAIN_LOW[1]}
    assert names(state.by_city(B)) == {THUNDER[1]}
    cancelled = [c for c in result.changes if c.type == ChangeType.CANCELLED]
    assert len(cancelled) == 1 and cancelled[0].at == at(20)


def test_snapshot_clearing_retains_empty_cell_watermarks_after_roundtrip():
    state = WarningState()
    state.apply(weather("VPWW61", cities={A: [THUNDER]}, issued=5, sent=5))
    state.apply(weather("VPWS50", cities={A: [kind("03", RAIN_LOW[1], time=10)]}, sent=10))
    state = WarningState.from_json(state.to_json())
    assert state.apply(weather("VPWW61", cities={A: [THUNDER]}, issued=9, sent=20)).changes == ()
    assert names(state.by_city(A)) == {RAIN_LOW[1]}
    changes = state.apply(weather("VPWW61", cities={A: [THUNDER]}, issued=11, sent=21)).changes
    assert len(changes) == 1 and changes[0].type == ChangeType.ISSUED


def test_snapshot_and_city_lookup_do_not_scan_all_cells_after_restore(monkeypatch):
    state = WarningState()
    state.apply(weather("VPWW61", cities={A: [THUNDER], B: [THUNDER]}, issued=5, sent=5))
    saved = state.to_json()
    state = WarningState.from_json(saved)
    assert state.to_json() == saved
    assert set(json.loads(saved)) == {
        "version",
        "accept_status",
        "last_updated",
        "cells",
        "cleared",
        "cleared_all",
        "rivers",
        "seen",
        "latest",
    }

    class NoFullScan(dict):
        def items(self):
            raise AssertionError("Snapshot items and city queries must use the city index")

    # A deterministic complexity guard, independent of wall-clock/CI speed.
    monkeypatch.setattr(state, "_cells", NoFullScan(state._cells))
    state.apply(weather("VPWS50", cities={A: [kind("03", RAIN_LOW[1], time=10)]}, sent=10))
    assert names(state.by_city(A)) == {RAIN_LOW[1]}
    assert names(state.by_city(B)) == {THUNDER[1]}
    # Replacing a cell via VPWW must keep the same index current too.
    state.apply(weather("VPWW61", cities={A: [THUNDER]}, issued=11, sent=11))
    assert names(state.cities()[A]) == {RAIN_LOW[1], THUNDER[1]}


def test_snapshot_without_municipal_warning_clears_only_cells_not_newer_than_report():
    state = WarningState()
    state.apply(weather(cities={A: [RAIN]}, issued=5, sent=5))
    state.apply(weather("VPWW58", cities={B: [kind("05", "暴風警報")]}, issued=20, sent=20))
    result = state.apply(weather("VPWS50", cities=None, issued=10, sent=30))
    assert state.by_city(A) == frozenset()
    assert names(state.by_city(B)) == {"暴風警報"}
    assert len(result.changes) == 1 and result.changes[0].at == at(10)


@pytest.mark.parametrize("inactive", ["解除", "発表警報・注意報はなし"])
def test_inactive_kinds_clear_without_creating_active_warning(inactive):
    state = WarningState()
    state.apply(weather(cities={A: [RAIN]}))
    result = state.apply(weather(cities={A: [kind("00", "解除", inactive)]}, issued=1, sent=1))
    assert state.by_city(A) == frozenset()
    assert result.changes[0].type == ChangeType.CANCELLED
    assert A not in state.cities()


def test_no_kind_creates_empty_cells_and_does_not_emit_changes():
    state = WarningState()
    result = state.apply(weather(cities={A: [], B: [NONE]}, issued=10, sent=10))
    assert result.applied and result.changes == ()
    # The empty cells still reject an older report from an independent unit.
    result = state.apply(weather(cities={A: [RAIN]}, issued=9, sent=20, office="other office"))
    assert result.applied and result.changes == ()
    assert state.cities() == {}


def test_unchanged_and_same_rank_changed_warnings_and_change_sorting():
    state = WarningState()
    original = weather("VPWW61", cities={B: [THUNDER], A: [THUNDER]}, issued=1, sent=1)
    changes = state.apply(original).changes
    assert [c.area for c in changes] == sorted([A, B])
    assert state.apply(weather("VPWW61", cities={B: [THUNDER]}, issued=2, sent=2)).changes == ()
    replacement = kind("20", "濃霧注意報")
    change = state.apply(weather("VPWW61", cities={B: [replacement]}, issued=3, sent=3)).changes[0]
    assert change.type == ChangeType.CHANGED
    assert change.at == at(3)


def test_city_filtering_and_query_snapshots():
    state = WarningState()
    state.apply(weather(cities={A: [RAIN], B: [RAIN_LOW]}))
    state.apply(weather("VPWW61", cities={A: [THUNDER]}, sent=1))
    snapshot = state.cities()
    assert names(state.cities(level_at_least(4))[A]) == {RAIN[1]}
    assert B not in state.cities(level_at_least(4))
    assert names(state.cities(element_in(Element.OTHER))[A]) == {THUNDER[1]}
    state.apply(weather(cities={A: [NONE]}, issued=1, sent=2))
    assert names(snapshot[A]) == {RAIN[1], THUNDER[1]}
    assert names(state.by_city(A)) == {THUNDER[1]}


def test_river_coverage_changes_update_queries_without_kind_change_event():
    root = ET.parse(SHARED / "vxsu_8201813100_l2.xml").getroot()
    state = WarningState()
    state.apply(parse(ET.tostring(root), strict=True))
    snapshot = state.rivers()
    date = root.find(f"{{{R}}}Control/{{{R}}}DateTime")
    assert date is not None
    date.text = at(0).isoformat()
    for code in root.findall(f".//{{{M}}}CityCode"):
        code.text = A
    result = state.apply(parse(ET.tostring(root), strict=True))
    assert result.applied and result.changes == ()
    assert state.by_city("0442101") == frozenset()
    assert names(state.by_city(A)) == {"レベル２氾濫注意報"}
    assert "0442100" in snapshot["8201813100"].cities
    assert state.rivers()["8201813100"].cities == frozenset({A})


def test_serialization_roundtrip_preserves_rivers_cells_history_and_status_config():
    state: State = WarningState(accept_status={"通常", "訓練"})
    weather_report = weather(cities={A: [RAIN]}, sent=5)
    river_report = parse(SHARED / "vxsu_8201813100_l2.xml", strict=True)
    state.apply(weather_report)
    state.apply(river_report)
    serialized = state.to_json()
    restored = WarningState.from_json(serialized)
    assert restored.to_json() == serialized
    assert names(restored.by_city(A)) == {RAIN[1]}
    assert names(restored.by_city("0442101")) == {"レベル２氾濫注意報"}
    assert restored.apply(weather_report).skip_reason == SkipReason.DUPLICATE
    assert (
        restored.apply(weather(cities={A: [RAIN]}, sent=4, serial="2")).skip_reason
        == SkipReason.STALE
    )
    payload = json.loads(serialized)
    assert payload["version"] == 1
    assert set(payload["cells"][0]["kinds"][0]) == {"name", "code", "group"}


def test_telegram_history_is_bounded_but_information_unit_watermark_survives():
    state = WarningState()
    original = weather(cities=None)
    report = original
    for index in range(10_005):
        report = replace(
            original, control=replace(original.control, date_time=NOW + timedelta(seconds=index))
        )
        assert state.apply(report).applied
    saved = state.to_json()
    assert len(json.loads(saved)["seen"]) == 10_000
    restored = WarningState.from_json(saved)
    assert restored.apply(original).skip_reason == SkipReason.STALE
    assert restored.apply(report).skip_reason == SkipReason.DUPLICATE


def test_unresolvable_snapshot_does_not_mutate_state_or_consume_telegram_key():
    state = WarningState()
    state.apply(weather(cities={A: [RAIN]}))
    before = state.to_json()
    bad = weather("VPWS50", cities={A: [NONE]}, sent=10)
    with pytest.raises(ValueError, match="watermark"):
        state.apply(bad)
    assert state.to_json() == before
    corrected = weather("VPWS50", cities={A: [kind("03", RAIN_LOW[1], time=10)]}, sent=10)
    assert state.apply(corrected).applied


@pytest.mark.parametrize("global_clear", [False, True])
def test_snapshot_absence_watermark_blocks_old_missing_cells_after_roundtrip(global_clear):
    state = WarningState()
    snapshot = weather(
        "VPWS50",
        cities=None if global_clear else {B: [NONE], A: [NONE]},
        extra_kinds=[kind("14", THUNDER[1], time=10)],
        issued=10,
        sent=10,
    )
    assert state.apply(snapshot).applied
    saved = state.to_json()
    payload = json.loads(saved)
    assert payload["cells"] == []
    assert payload["cleared"] == (
        [] if global_clear else [{"city": city, "at": at(10).isoformat()} for city in (A, B)]
    )
    assert payload["cleared_all"] == (at(10).isoformat() if global_clear else None)
    assert state.cities() == {} and state.rivers() == {}
    state = WarningState.from_json(saved)
    assert state.to_json() == saved
    old = weather(cities={A: [RAIN]}, issued=9, sent=20)
    result = state.apply(old)
    assert result.applied and result.changes == ()
    assert state.by_city(A) == frozenset()
    for minute in (10, 11):
        state = WarningState.from_json(saved)
        result = state.apply(weather(cities={A: [RAIN]}, issued=minute, sent=20 + minute))
        assert result.applied
        assert names(state.by_city(A)) == {RAIN[1]}


@pytest.mark.parametrize("global_clear", [False, True])
def test_snapshot_absence_watermarks_never_move_backwards(global_clear):
    state = WarningState()
    for minute, sent in [(20, 20), (10, 30)]:
        state.apply(
            weather(
                "VPWS50",
                cities=None if global_clear else {A: [NONE]},
                extra_kinds=[kind("14", THUNDER[1], time=minute)],
                issued=minute,
                sent=sent,
            )
        )
    result = state.apply(weather(cities={A: [RAIN]}, issued=15, sent=40))
    assert result.applied and result.changes == ()
    assert state.cities() == {}


def test_existing_cell_precedes_absence_watermark_and_other_cities_are_untouched():
    state = WarningState()
    state.apply(weather("VPWS50", cities={A: [kind("43", RAIN[1], time=5)]}, sent=10))
    state.apply(
        weather(
            "VPWS50",
            cities={A: [kind("43", RAIN[1], time=5)]},
            extra_kinds=[kind("14", THUNDER[1], time=20)],
            sent=20,
        )
    )
    state = WarningState.from_json(state.to_json())
    state.apply(weather(cities={A: [RAIN_LOW], B: [RAIN]}, issued=10, sent=30))
    assert names(state.by_city(A)) == {RAIN_LOW[1]}
    assert names(state.by_city(B)) == {RAIN[1]}


def test_snapshot_active_kind_uses_absence_watermark_for_missing_cell():
    state = WarningState()
    state.apply(weather("VPWS50", issued=20, sent=20))
    result = state.apply(weather("VPWS50", cities={A: [kind("43", RAIN[1], time=10)]}, sent=30))
    assert result.applied and result.changes == ()
    assert state.cities() == {}


def test_invalid_later_snapshot_item_does_not_commit_absence_watermarks():
    state = WarningState()
    state.apply(weather("VPWS50", issued=5, sent=5))
    before = state.to_json()
    bad = weather(
        "VPWS50",
        cities={A: [NONE], B: [RAIN]},
        sent=10,
        extra_kinds=[kind("14", THUNDER[1], time=10)],
    )
    with pytest.raises(ValueError, match="DateTime"):
        state.apply(bad)
    assert state.to_json() == before
    corrected = weather("VPWS50", cities={A: [NONE], B: [kind("43", RAIN[1], time=10)]}, sent=10)
    assert state.apply(corrected).applied


@pytest.mark.parametrize("missing", [("cleared",), ("cleared_all",), ("cleared", "cleared_all")])
def test_older_json_without_absence_watermarks_is_readable(missing):
    state = WarningState()
    report = weather(cities={A: [RAIN]})
    state.apply(report)
    payload = json.loads(state.to_json())
    for field in missing:
        del payload[field]
    restored = WarningState.from_json(json.dumps(payload))
    assert restored.to_json() == state.to_json()
    assert restored.apply(report).skip_reason == SkipReason.DUPLICATE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cleared", None),
        ("cleared", {}),
        ("cleared", [None]),
        ("cleared", [{}]),
        ("cleared", [{"city": 123, "at": at(0).isoformat()}]),
        ("cleared", [{"city": A, "at": 123}]),
        ("cleared", [{"city": A, "at": "invalid"}]),
        ("cleared", [{"city": A, "at": "2026-11-12T00:00:00"}]),
        ("cleared_all", []),
        ("cleared_all", 123),
        ("cleared_all", "invalid"),
        ("cleared_all", "2026-11-12T00:00:00"),
    ],
)
def test_invalid_absence_watermark_json_is_rejected(field, value):
    payload = json.loads(WarningState().to_json())
    payload[field] = value
    with pytest.raises(ValueError):
        WarningState.from_json(json.dumps(payload))


def test_age_filter_is_opt_in():
    assert WarningState().apply(weather(cities={A: [RAIN]}, sent=-1_000_000)).applied


@pytest.mark.parametrize(
    ("offset", "reason"),
    [
        (-timedelta(hours=24), None),
        (-timedelta(hours=24, seconds=1), SkipReason.TOO_OLD),
        (timedelta(minutes=10), None),
        (timedelta(minutes=10, seconds=1), SkipReason.FUTURE),
    ],
)
def test_control_time_bounds_are_inclusive(offset, reason):
    # ReportDateTime intentionally differs: filtering must use Control/DateTime.
    report = weather(cities={A: [RAIN]}, issued=-1_000_000)
    report = replace(report, control=replace(report.control, date_time=NOW + offset))
    state = WarningState()
    before = state.to_json()
    result = state.apply(report, now=NOW)
    assert result.skip_reason == reason and result.applied == (reason is None)
    if reason is not None:
        assert result.changes == () and state.to_json() == before
        assert state.apply(report).applied


@pytest.mark.parametrize(
    ("sent", "bounds"),
    [(-1_000_000, {"max_age": None}), (1_000_000, {"max_future": None})],
)
def test_time_bound_can_be_disabled(sent, bounds):
    assert WarningState().apply(weather(sent=sent), now=NOW, **bounds).applied


@pytest.mark.parametrize(
    ("sent", "bounds", "reason"),
    [
        (-61, {"max_age": timedelta(hours=1)}, SkipReason.TOO_OLD),
        (-60, {"max_age": timedelta(hours=1)}, None),
        (21, {"max_future": timedelta(minutes=20)}, SkipReason.FUTURE),
        (20, {"max_future": timedelta(minutes=20)}, None),
        (0, {"max_age": timedelta(0), "max_future": timedelta(0)}, None),
    ],
)
def test_custom_time_bounds(sent, bounds, reason):
    result = WarningState().apply(weather(sent=sent), now=NOW, **bounds)
    assert result.skip_reason == reason


@pytest.mark.parametrize(
    "bounds",
    [
        {"now": NOW.replace(tzinfo=None)},
        {"now": NOW, "max_age": -timedelta(seconds=1)},
        {"now": NOW, "max_future": -timedelta(seconds=1)},
        {"max_age": -timedelta(seconds=1)},
        {"max_future": -timedelta(seconds=1)},
    ],
)
def test_invalid_time_filter_arguments_do_not_mutate_state(bounds):
    state = WarningState()
    before = state.to_json()
    with pytest.raises(ValueError):
        state.apply(weather(), **bounds)
    assert state.to_json() == before


def test_ledger_skip_precedence_over_time_filters():
    state = WarningState()
    first = weather(cities={A: [RAIN]}, sent=10)
    state.apply(first)
    later_now = at(10) + timedelta(days=7)
    assert state.apply(first, now=later_now).skip_reason == SkipReason.DUPLICATE
    assert state.apply(weather(sent=9), now=later_now).skip_reason == SkipReason.STALE
    unsupported = replace(first, control=replace(first.control, title="unsupported"))
    assert state.apply(unsupported, now=later_now).skip_reason == SkipReason.UNSUPPORTED
    training = replace(unsupported, control=replace(unsupported.control, status="訓練"))
    assert state.apply(training, now=later_now).skip_reason == SkipReason.STATUS


@pytest.mark.parametrize("value", ["[]", "null", "{}", '{"version":2}', '{"version":true}'])
def test_invalid_serialization_versions_and_shapes(value):
    with pytest.raises(ValueError):
        WarningState.from_json(value)


def test_naive_persisted_time_is_rejected():
    state = WarningState()
    state.apply(weather(cities={A: [RAIN]}))
    payload = json.loads(state.to_json())
    payload["cells"][0]["as_of"] = "2026-11-12T00:00:00"
    with pytest.raises(ValueError, match="timezone"):
        WarningState.from_json(json.dumps(payload))


def test_state_layer_has_no_network_filesystem_or_clock_access():
    for path in (Path(__file__).parents[1] / "pyjmaxml" / "state").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & {
                    "urllib",
                    "httpx",
                    "socket",
                    "time",
                    "threading",
                    "pathlib",
                }
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in {
                    "urllib",
                    "httpx",
                    "socket",
                    "time",
                    "threading",
                    "pathlib",
                }
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "now",
                    "utcnow",
                    "today",
                    "sleep",
                    "read_text",
                    "read_bytes",
                }
