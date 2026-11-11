import json
from pathlib import Path

import pytest

from jmadantic import WarningState, parse

CASES = sorted((Path(__file__).parent / "golden").glob("*/case.json"))
assert len(CASES) == 12, "The pinned golden corpus must contain all 12 cases"


@pytest.mark.parametrize("case_path", CASES, ids=lambda path: path.parent.name)
def test_golden(case_path: Path):
    case = json.loads(case_path.read_text(encoding="utf-8"))
    state = WarningState()
    for step_number, step in enumerate(case["steps"], 1):
        context = f"{case_path.parent.name} step {step_number} ({step['file']})"
        if step.get("roundtrip_before", False):
            serialized = state.to_json()
            state = WarningState.from_json(serialized)
            assert state.to_json() == serialized, context
        result = state.apply(parse(case_path.parent / step["file"], strict=True))
        expect = step["expect"]
        if "applied" in expect:
            assert result.applied == expect["applied"], context
        if "skip_reason" in expect:
            assert result.skip_reason == expect["skip_reason"], context
        for code, names in expect.get("cities", {}).items():
            assert {kind.name for kind in state.by_city(code)} == set(names), (
                f"{context} city {code}"
            )
        rivers = state.rivers()
        for event_id, expected in expect.get("rivers", {}).items():
            assert event_id in rivers, f"{context} river {event_id}"
            river = rivers[event_id]
            assert {
                "group": river.group,
                "kinds": sorted(kind.name for kind in river.kinds),
                "cities": sorted(river.cities),
            } == {
                **expected,
                "kinds": sorted(expected["kinds"]),
                "cities": sorted(expected["cities"]),
            }, f"{context} river {event_id}"
        for event_id in expect.get("rivers_absent", []):
            assert event_id not in rivers, f"{context} absent river {event_id}"
        if "changes" in expect:
            expected = expect["changes"]
            if "count" in expected:
                assert len(result.changes) == expected["count"], f"{context} changes count"
            actual = {(c.scope, c.area, c.group, c.type) for c in result.changes}
            for change in expected.get("contains", []):
                key = (change["scope"], change["area"], change["group"], change["type"])
                assert key in actual, f"{context} missing change {key}"
            for area in expected.get("excludes_areas", []):
                assert not any(c.area == area for c in result.changes), f"{context} excluded {area}"
