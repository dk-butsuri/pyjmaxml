import ast
from pathlib import Path

from pyjmaxml.codes import (
    AREA_CITY,
    AREA_CITY_PARENT,
    AREA_FLOOD_FORECAST,
    AREA_WATER_LEVEL_WARNING,
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
