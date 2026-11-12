from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pyjmaxml import (
    Element,
    Predicate,
    Stage,
    WarningKind,
    classify_flood,
    classify_mete,
    data_type_code,
    element_in,
    level_at_least,
    parse,
    rank,
    stage_at_least,
)

TESTS = Path(__file__).parent
NS = {
    "r": "http://xml.kishou.go.jp/jmaxml1/",
    "h": "http://xml.kishou.go.jp/jmaxml1/informationBasis1/",
    "m": "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/",
}
METE_GROUPS = {f"VPWW{number}" for number in range(55, 62)}
TARGET_GROUPS = METE_GROUPS | {"VPWS50", "VXKO", "VXSU"}
TARGET_TITLES = {
    f"気象警報・注意報（Ｒ０６）（{element}）"
    for element in ["大雨", "土砂", "高潮", "暴風", "波浪", "大雪", "その他注意報", "集約通報"]
} | {"指定河川洪水予報", "水位周知河川に関する情報"}
ALL_FILES = sorted((TESTS / "data" / "samples").glob("*.xml")) + sorted(
    (TESTS / "golden").rglob("*.xml")
)
# Sniff only the title for collection. Every selected file is then parsed in
# strict mode and checked against the public data_type_code API below.
TARGET_FILES = [
    path
    for path in ALL_FILES
    if ET.parse(path).findtext("r:Control/r:Title", namespaces=NS) in TARGET_TITLES
]


def kind_records(path: Path, group: str) -> list[tuple[str, str]]:
    root = ET.parse(path).getroot()
    if group in {"VXKO", "VXSU"}:
        info_type = (
            "指定河川洪水予報（予報区域）"
            if group == "VXKO"
            else "水位周知河川に関する情報（発表区間）"
        )
        nodes = root.findall(
            f"h:Head/h:Headline/h:Information[@type='{info_type}']/h:Item/h:Kind", NS
        )
    else:
        nodes = root.findall(
            "m:Body/m:Warning[@type='気象警報・注意報（市町村等）']/m:Item/m:Kind", NS
        )
    records = []
    namespace = NS["h"] if group in {"VXKO", "VXSU"} else NS["m"]
    for node in nodes:
        code = node.findtext(f"{{{namespace}}}Code")
        if code is None:
            continue  # The plan explicitly excludes kinds without Code (なし).
        records.append((code, node.findtext(f"{{{namespace}}}Name") or ""))
    return records


@pytest.mark.parametrize("path", TARGET_FILES, ids=lambda path: str(path.relative_to(TESTS)))
def test_all_supported_corpus_kinds_are_classified(path: Path):
    report = parse(path, strict=True)
    group = data_type_code(report)
    assert group in TARGET_GROUPS
    assert group is not None
    for code, name in kind_records(path, group):
        kind = (
            classify_flood(code, name, group)
            if group in {"VXKO", "VXSU"}
            else classify_mete(code, name)
        )
        assert kind.code == code and kind.name == name
        if code == "00" and group in METE_GROUPS | {"VPWS50"}:
            assert kind.stage is None  # Generic meteorological cancellation.
        else:
            assert kind.element != Element.UNKNOWN, (path, group, code, name)
            if code == "10" and group in {"VXKO", "VXSU"}:
                assert kind.stage is None  # Flood cancellation, not an advisory.
            else:
                assert kind.stage is not None
        if group in {"VXKO", "VXSU"}:
            assert kind.group == group
        elif code != "00":
            assert kind.group in METE_GROUPS
            if group != "VPWS50":
                assert kind.group == group


def test_supported_corpus_matches_pinned_plan_inventory():
    assert len(TARGET_FILES) == 46
    groups = set()
    codes = set()
    for path in TARGET_FILES:
        group = data_type_code(parse(path, strict=True))
        assert group is not None
        groups.add(group)
        codes.update(code for code, _ in kind_records(path, group))
    assert groups == TARGET_GROUPS
    assert len(codes) == 31


@pytest.mark.parametrize(
    ("code", "name", "group", "element", "stage", "level"),
    [
        ("10", "レベル２大雨注意報", "VPWW55", Element.HEAVY_RAIN, Stage.ADVISORY, 2),
        ("03", "レベル３大雨警報", "VPWW55", Element.HEAVY_RAIN, Stage.WARNING, 3),
        ("43", "レベル４大雨危険警報", "VPWW55", Element.HEAVY_RAIN, Stage.DANGER_WARNING, 4),
        ("33", "レベル５大雨特別警報", "VPWW55", Element.HEAVY_RAIN, Stage.EMERGENCY, 5),
        ("29", "レベル２土砂災害注意報", "VPWW56", Element.LANDSLIDE, Stage.ADVISORY, 2),
        ("09", "レベル３土砂災害警報", "VPWW56", Element.LANDSLIDE, Stage.WARNING, 3),
        ("49", "レベル４土砂災害危険警報", "VPWW56", Element.LANDSLIDE, Stage.DANGER_WARNING, 4),
        ("39", "レベル５土砂災害特別警報", "VPWW56", Element.LANDSLIDE, Stage.EMERGENCY, 5),
        ("19", "レベル２高潮注意報", "VPWW57", Element.STORM_SURGE, Stage.ADVISORY, 2),
        ("08", "レベル３高潮警報", "VPWW57", Element.STORM_SURGE, Stage.WARNING, 3),
        ("48", "レベル４高潮危険警報", "VPWW57", Element.STORM_SURGE, Stage.DANGER_WARNING, 4),
        ("38", "レベル５高潮特別警報", "VPWW57", Element.STORM_SURGE, Stage.EMERGENCY, 5),
        ("15", "強風注意報", "VPWW58", Element.STORM, Stage.ADVISORY, None),
        ("13", "風雪注意報", "VPWW58", Element.SNOWSTORM, Stage.ADVISORY, None),
        ("05", "暴風警報", "VPWW58", Element.STORM, Stage.WARNING, None),
        ("02", "暴風雪警報", "VPWW58", Element.SNOWSTORM, Stage.WARNING, None),
        ("35", "暴風特別警報", "VPWW58", Element.STORM, Stage.EMERGENCY, None),
        ("32", "暴風雪特別警報", "VPWW58", Element.SNOWSTORM, Stage.EMERGENCY, None),
        ("16", "波浪注意報", "VPWW59", Element.HIGH_WAVE, Stage.ADVISORY, None),
        ("07", "波浪警報", "VPWW59", Element.HIGH_WAVE, Stage.WARNING, None),
        ("37", "波浪特別警報", "VPWW59", Element.HIGH_WAVE, Stage.EMERGENCY, None),
        ("12", "大雪注意報", "VPWW60", Element.HEAVY_SNOW, Stage.ADVISORY, None),
        ("06", "大雪警報", "VPWW60", Element.HEAVY_SNOW, Stage.WARNING, None),
        ("36", "大雪特別警報", "VPWW60", Element.HEAVY_SNOW, Stage.EMERGENCY, None),
    ],
)
def test_meteorological_classification(code, name, group, element, stage, level):
    assert classify_mete(code, name) == WarningKind(name, code, group, element, stage, level)


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("14", "雷"),
        ("17", "融雪"),
        ("20", "濃霧"),
        ("21", "乾燥"),
        ("22", "なだれ"),
        ("23", "低温"),
        ("24", "霜"),
        ("25", "着氷"),
        ("26", "着雪"),
        ("27", "その他"),
    ],
)
def test_other_advisories(code, name):
    kind = classify_mete(code, name + "注意報")
    assert (kind.group, kind.element, kind.stage, kind.level) == (
        "VPWW61",
        Element.OTHER,
        Stage.ADVISORY,
        None,
    )


def test_levels_are_read_from_labels_only_for_the_designated_elements():
    assert classify_mete("43", "レベル4大雨危険警報").level == 4
    assert classify_mete("03", "大雨警報").level is None
    assert classify_mete("35", "レベル５暴風特別警報").level is None


@pytest.mark.parametrize("code", ["04", "18", "42", "45", "46", "47", "99"])
def test_unknown_meteorological_codes_are_preserved_and_logged(code, caplog):
    name = "レベル５未知の警報"
    with caplog.at_level("WARNING", logger="pyjmaxml.normalize.warning"):
        kind = classify_mete(code, name)
    assert kind == WarningKind(name, code, "", Element.UNKNOWN, None, None)
    assert any(code in record.message for record in caplog.records)


def test_meteorological_cancellation_is_not_logged_as_unknown(caplog):
    kind = classify_mete("00", "解除")
    assert (kind.code, kind.stage, kind.level) == ("00", None, None)
    assert not caplog.records


@pytest.mark.parametrize("group", ["VXKO", "VXSU"])
@pytest.mark.parametrize(
    ("code", "stage", "level"),
    [
        ("20", Stage.ADVISORY, 2),
        ("21", Stage.ADVISORY, 2),
        ("22", Stage.ADVISORY, 2),
        ("30", Stage.WARNING, 3),
        ("31", Stage.WARNING, 3),
        ("40", Stage.DANGER_WARNING, 4),
        ("41", Stage.DANGER_WARNING, 4),
        ("51", Stage.EMERGENCY, 5),
        ("53", Stage.EMERGENCY, 5),
    ],
)
def test_flood_stage_and_level_are_code_based_even_for_old_names(group, code, stage, level):
    kind = classify_flood(code, "旧名称も保持する", group)
    assert kind == WarningKind("旧名称も保持する", code, group, Element.FLOOD, stage, level)


@pytest.mark.parametrize("group", ["VXKO", "VXSU"])
def test_flood_cancellation(group, caplog):
    kind = classify_flood("10", "レベル２氾濫注意報解除", group)
    assert kind.element == Element.FLOOD
    assert kind.stage is kind.level is None
    assert not caplog.records


def test_unknown_flood_code_and_invalid_group(caplog):
    kind = classify_flood("99", "不明", "VXSU")
    assert kind == WarningKind("不明", "99", "VXSU", Element.UNKNOWN, None, None)
    assert any("99" in record.message for record in caplog.records)
    with pytest.raises(ValueError, match="group"):
        classify_flood("20", "氾濫注意報", "VPWW55")


def test_predicates_compose_and_do_not_match_missing_stage_or_level():
    danger = classify_mete("43", "レベル４大雨危険警報")
    wind = classify_mete("05", "暴風警報")
    other = classify_mete("14", "雷注意報")
    cancellation = classify_mete("00", "解除")
    selected = level_at_least(4) & element_in(Element.HEAVY_RAIN, Element.LANDSLIDE)
    assert selected(danger) and not selected(wind)
    assert (selected | element_in(Element.STORM))(wind)
    assert (~selected)(other)
    assert not stage_at_least(Stage.ADVISORY)(cancellation)
    assert not level_at_least(0)(wind)
    assert stage_at_least(Stage.WARNING)(wind)
    assert not stage_at_least(Stage.WARNING)(other)
    assert not element_in()(danger)


def test_predicate_boolean_operations_short_circuit():
    called = []
    kind = classify_mete("14", "雷注意報")

    def record(value):
        called.append(value)
        return True

    probe = Predicate(record)
    assert not (Predicate(lambda _: False) & probe)(kind)
    assert (Predicate(lambda _: True) | probe)(kind)
    assert called == []
    assert (Predicate(lambda _: True) & probe)(kind)
    assert called == [kind]


def test_rank_compares_stage_before_level_and_handles_missing_values():
    danger = classify_flood("40", "氾濫危険情報", "VXKO")
    emergency = classify_mete("35", "暴風特別警報")
    assert rank(danger) == (Stage.DANGER_WARNING, 4)
    assert rank(emergency) == (Stage.EMERGENCY, 0)
    assert rank(emergency) > rank(danger)
    assert rank(classify_mete("00", "解除")) == (-1, 0)
