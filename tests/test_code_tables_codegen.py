import ast
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from scripts.codegen import acquire, city_codes, generate_codes, main, river_codes


def workbook_bytes(book):
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def city_book():
    book = Workbook()
    city = book.active
    assert city is not None
    city.title = "AreaInformationCity"
    city.append(["city table"])
    city.append(["information products"])
    city.append(["@code", "region", "@name", "reading", "parent", "weather-warning flag"])
    city.append(["0110000", "札幌市", "札幌市", "", "016012", 1])
    # A different product's code need not have a weather forecast parent.
    city.append(["0110100", "中央区", "中央区", "", None, 0])
    city.append([2810700, "神戸市須磨区", "神戸市須磨区", "", "280011", 1])
    relation = book.create_sheet("AreaForecastLocalM（関係表　警報・注意報")
    relation.append(["relationship table"])
    relation.append(["grouping", "", "primary subdivision", "", "prefectural forecast"])
    relation.append(["コード\n(@code)", "@name"] * 3)
    relation.append(["016012", "石狩中部", "016010", "石狩地方", "016010", "石狩地方"])
    relation.append(["280011", "阪神", "280010", "南部", "280000", "兵庫県"])
    return book


def river_book(sheet="AreaFloodForecast", rows=()):
    book = Workbook()
    table = book.active
    assert table is not None
    table.title = sheet
    table.append(["code table"])
    table.append(["description"])
    table.append(["@code", "@name"])
    for row in rows:
        table.append(row)
    return book


def test_city_join_respects_explicit_parents_flags_and_numeric_source_cells():
    assert city_codes(workbook_bytes(city_book())) == {
        "0110000": ("札幌市", "016010", "016010"),
        "2810700": ("神戸市須磨区", "280000", "280010"),
    }


@pytest.mark.parametrize("change", ["short-numeric-code", "missing-parent", "duplicate", "header"])
def test_city_table_errors_are_not_repaired_by_guessing(change):
    book = city_book()
    table = book["AreaInformationCity"]
    if change == "short-numeric-code":
        table["A4"] = 110000  # Do not invent a missing leading zero.
    elif change == "missing-parent":
        table["E4"] = "999999"
    elif change == "duplicate":
        table["A6"] = "0110000"
    else:
        table["A3"] = "changed header"
    with pytest.raises(ValueError):
        city_codes(workbook_bytes(book))


@pytest.mark.parametrize(
    ("sheet", "width", "code"),
    [("AreaFloodForecast", 12, "010175000100"), ("AreaWaterLevelWarning", 10, "8201813100")],
)
def test_river_code_width_and_exact_names(sheet, width, code):
    data = workbook_bytes(river_book(sheet, [(code, "河川名　区間名")]))
    assert river_codes(data, sheet, width) == {code: "河川名　区間名"}


def test_header_only_water_level_table_is_valid_and_empty():
    data = workbook_bytes(river_book("AreaWaterLevelWarning"))
    assert river_codes(data, "AreaWaterLevelWarning", 10) == {}


@pytest.mark.parametrize(
    "rows",
    [
        [("123", "wrong width")],
        [("010175000100", None)],
        [("010175000100", "one"), ("010175000100", "duplicate")],
    ],
)
def test_invalid_river_table_is_rejected(rows):
    with pytest.raises(ValueError):
        river_codes(workbook_bytes(river_book(rows=rows)), "AreaFloodForecast", 12)


def code_archive(path):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "20261019_AreaInformationCity-AreaForecastLocalM.xlsx", workbook_bytes(city_book())
        )
        archive.writestr(
            "20260806_AreaFloodForecast.xlsx",
            workbook_bytes(river_book(rows=[("010175000100", "新川")])),
        )
        archive.writestr(
            "20241226_AreaWaterLevelWarning.xlsx",
            workbook_bytes(river_book("AreaWaterLevelWarning")),
        )
    return path


def test_generation_is_deterministic_and_only_contains_literal_dicts(tmp_path):
    archive = code_archive(tmp_path / "codes.zip")
    first, second = tmp_path / "first", tmp_path / "second"
    generate_codes(archive, first)
    generate_codes(archive, second)
    assert sorted(path.name for path in first.iterdir()) == [
        "_area_city.py",
        "_area_flood_forecast.py",
        "_area_water_level_warning.py",
    ]
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert len(tree.body) == 1
        assignment = tree.body[0]
        assert isinstance(assignment, ast.AnnAssign) and assignment.value is not None
        assert isinstance(ast.literal_eval(assignment.value), dict)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() in path.read_text(encoding="utf-8")


def test_offline_mode_fails_before_trying_to_download(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.codegen.VENDOR", tmp_path)

    def no_download(*args, **kwargs):
        raise AssertionError("Download must not be attempted")

    monkeypatch.setattr("scripts.codegen.urllib.request.urlopen", no_download)
    with pytest.raises(FileNotFoundError, match="offline"):
        acquire("missing.zip", "0" * 64, offline=True)


def test_offline_codes_only_cli_uses_verified_cache_without_xsdata(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    archive = code_archive(vendor / "codes.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (scripts / "manifest.toml").write_text(
        f'[codes]\nfilename = "codes.zip"\nsha256 = "{digest}"\n', encoding="utf-8"
    )
    monkeypatch.setattr("scripts.codegen.ROOT", tmp_path)
    monkeypatch.setattr("scripts.codegen.VENDOR", vendor)
    monkeypatch.setattr("sys.argv", ["codegen.py", "--offline", "--codes-only"])

    def forbidden(*args, **kwargs):
        raise AssertionError("Neither download nor xsdata should run in this mode")

    monkeypatch.setattr("scripts.codegen.urllib.request.urlopen", forbidden)
    monkeypatch.setattr("scripts.codegen.subprocess.run", forbidden)
    main()
    assert (tmp_path / "jmadantic/codes/_area_city.py").is_file()
