import random
from pathlib import Path

from pyjmaxml import WarningState, parse

SHARED = Path(__file__).parent / "golden" / "_shared"


def final_state(reports):
    state = WarningState()
    for report in reports:
        try:
            state.apply(report)
        except ValueError:
            continue
    cities = {city: {kind.name for kind in kinds} for city, kinds in state.cities().items()}
    return cities, state.rivers()


def test_shared_reports_converge_when_reordered():
    reports = {path.name: parse(path, strict=True) for path in sorted(SHARED.glob("*.xml"))}
    assert len(reports) == 8
    chronological = sorted(reports.values(), key=lambda report: report.control.date_time)
    expected = final_state(chronological)
    reproduction = [
        reports["vpws50_20261112T0000.xml"],
        reports["vpww55_wakkanai_20200622T2300.xml"],
        reports["vpww55_wakkanai_20200623T0000_downgrade.xml"],
    ]
    assert final_state(reproduction)[0].get("0121400", set()) == set()
    rng = random.Random(0)
    for index in range(30):
        shuffled = chronological.copy()
        rng.shuffle(shuffled)
        assert final_state(shuffled) == expected, f"shuffle {index}"
