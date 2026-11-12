import ast
from pathlib import Path
from typing import get_args

from pyjmaxml.codes import (
    AREA_CITY,
    AREA_CITY_PARENT,
    AREA_FLOOD_FORECAST,
    AREA_WATER_LEVEL_WARNING,
    AreaName,
    Prefecture,
)
from pyjmaxml.codes._area_name import (
    AREA_CODE_BY_NAME,
    AREA_NAME_BY_CODE,
    AREAS_BY_PREFECTURE,
    PREFECTURE_CODE,
)


def test_published_area_tables_and_leading_zeroes():
    assert len(AREA_CITY) == 1805
    assert AREA_CITY["0110000"] == ("札幌市", "016010", "016010")
    assert AREA_CITY["0121400"] == ("稚内市", "011000", "011000")
    assert AREA_CITY["1310100"] == ("千代田区", "130000", "130010")
    assert AREA_CITY["2810700"] == ("神戸市須磨区", "280000", "280010")
    assert AREA_CITY["2810900"] == ("神戸市北区", "280000", "280010")
    for code, (name, prefecture, subdivision) in AREA_CITY.items():
        assert len(code) == 7 and code.isdecimal()
        assert name
        assert len(prefecture) == len(subdivision) == 6
    assert len(AREA_FLOOD_FORECAST) == 338
    assert AREA_FLOOD_FORECAST["840410000100"] == "小矢部川"
    assert AREA_FLOOD_FORECAST["010175000100"] == "札幌市新川水系　新川"
    # The pinned official workbook contains only its three header rows.
    assert AREA_WATER_LEVEL_WARNING == {}


def test_runtime_package_does_not_import_spreadsheet_libraries():
    for path in (Path(__file__).parents[1] / "pyjmaxml").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "openpyxl" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "openpyxl"


def test_published_city_parent_table():
    assert len(AREA_CITY_PARENT) == 166
    for child in ["0442101", "0442102"]:
        assert AREA_CITY_PARENT[child] == "0442100"
    for child in ["4621501", "4621502"]:
        assert AREA_CITY_PARENT[child] == "4621500"
    assert "0442100" not in AREA_CITY_PARENT
    assert "0442199" not in AREA_CITY_PARENT
    assert all(
        child[-2:] != "00" and parent == child[:5] + "00"
        for child, parent in AREA_CITY_PARENT.items()
    )


def test_area_names_are_a_bijection_over_warning_areas():
    assert len(AREA_CODE_BY_NAME) == len(AREA_NAME_BY_CODE) == len(AREA_CITY) == 1805
    assert set(AREA_NAME_BY_CODE) == set(AREA_CITY)
    assert len(set(AREA_NAME_BY_CODE.values())) == 1805
    assert get_args(AreaName) == tuple(AREA_NAME_BY_CODE[code] for code in sorted(AREA_CITY))
    assert {name: code for code, name in AREA_NAME_BY_CODE.items()} == AREA_CODE_BY_NAME
    examples = {
        "2721000": "大阪府枚方市",
        "1310100": "東京都千代田区",
        "2810100": "兵庫県神戸市東灘区",
        "2020111": "長野県長野市（長野）",
        "2020112": "長野県長野市（鬼無里戸隠）",
        "1410011": "神奈川県横浜市（横浜市北部）",
        "0148402": "北海道羽幌町（天売焼尻）",
        "0120601": "北海道釧路市（釧路市釧路）",
    }
    for code, name in examples.items():
        assert AREA_NAME_BY_CODE[code] == name


def test_prefectures_partition_all_warning_areas():
    assert len(PREFECTURE_CODE) == len(AREAS_BY_PREFECTURE) == 47
    assert len(set(PREFECTURE_CODE.values())) == 47
    assert get_args(Prefecture) == tuple(PREFECTURE_CODE)
    assert list(PREFECTURE_CODE.values()) == [f"{i:02}" for i in range(1, 48)]
    codes = []
    for prefecture, names in AREAS_BY_PREFECTURE.items():
        area_codes = [AREA_CODE_BY_NAME[name] for name in names]
        assert area_codes == sorted(area_codes)
        assert all(code[:2] == PREFECTURE_CODE[prefecture] for code in area_codes)
        codes.extend(area_codes)
    assert sorted(codes) == sorted(AREA_CITY)
    assert len(AREAS_BY_PREFECTURE["北海道"]) == 186
