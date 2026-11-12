import logging
from pathlib import Path

import pytest

from pyjmaxml import EarthquakeInfo, Intensity, earthquake_info, parse

TESTS = Path(__file__).parent
SAMPLES = TESTS / "data" / "samples"
REAL = TESTS / "data" / "earthquake"
FILES = sorted(SAMPLES.glob("*_VXSE5[123].xml")) + sorted(REAL.glob("*.xml"))
# 2026-11-08 01:04 静岡県西部 M5.7, 最大震度5強.
SOKUHO = REAL / "20261107160611_0_VXSE51_010000.xml"
SHINGEN = REAL / "20261107160721_0_VXSE52_010000.xml"
FIRST = REAL / "20261107160836_0_VXSE53_010000.xml"
SECOND = REAL / "20261107161257_0_VXSE53_010000.xml"


def load(path: Path) -> EarthquakeInfo:
    return earthquake_info(parse(path, strict=True))


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_every_intensity_is_classified(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = load(path)
    assert result.group in path.name
    assert all(cell.intensity is not None or cell.unreceived for cell in result.intensities)
    if result.info_type == "取消":
        assert result.text and not result.intensities and result.hypocenter is None
    elif result.group != "VXSE51":
        assert result.hypocenter is not None and result.origin_time is not None
    assert not caplog.records


def test_intensity_order_and_labels() -> None:
    assert Intensity.FOUR < Intensity.FIVE_LOWER < Intensity.FIVE_UPPER < Intensity.SIX_LOWER
    # FIVE_UPPER is rank 6; printing must not suggest 震度6.
    assert int(Intensity.FIVE_UPPER) == 6
    assert str(Intensity.FIVE_UPPER) == "震度5強"
    assert f"{Intensity.SIX_LOWER}" == "震度6弱"
    assert f"{Intensity.SEVEN:>5}" == "  震度7"


def test_vxse51_has_areas_only() -> None:
    result = load(SOKUHO)
    assert result.hypocenter is None and result.magnitude is None
    assert result.max_intensity is Intensity.FIVE_UPPER
    assert {cell.level for cell in result.intensities} == {"pref", "area"}
    assert [(c.name, c.intensity) for c in result.by_area("451")] == [
        ("愛知県西部", Intensity.FIVE_UPPER)
    ]
    assert result.by_city("2322400") == ()


def test_vxse52_hypocenter_and_magnitude() -> None:
    result = load(SHINGEN)
    assert result.event_id == "20261108010441"
    assert result.intensities == () and result.max_intensity is None
    hypocenter = result.hypocenter
    assert hypocenter is not None
    assert (hypocenter.name, hypocenter.code) == ("静岡県西部", "443")
    assert (hypocenter.latitude, hypocenter.longitude, hypocenter.depth_km) == (34.9, 137.7, 40.0)
    assert result.magnitude is not None
    assert (result.magnitude.value, result.magnitude.type) == (5.7, "Mj")
    assert result.forecast_comment == "この地震による津波の心配はありません。"


def test_vxse53_cities_and_stations() -> None:
    result = load(FIRST)
    assert (result.serial, result.max_intensity) == ("1", Intensity.FIVE_UPPER)
    assert result.origin_time is not None and result.origin_time.isoformat() == (
        "2026-11-08T01:04:00+09:00"
    )
    assert [(c.level, c.name, c.intensity) for c in result.by_city("2322400")] == [
        ("city", "知多市", Intensity.FIVE_UPPER),
        ("station", "知多市緑町＊", Intensity.FIVE_UPPER),
    ]
    station = result.by_city("2322400")[1]
    assert (station.pref_code, station.area_code, station.city_code) == ("23", "451", "2322400")
    area = result.by_area("451")
    assert area[0].level == "area" and {c.area_code for c in area} == {"451"}
    assert result.forecast_comment_codes == ("0215", "0241")
    assert result.var_comment == "＊印は気象庁以外の震度観測点についての情報です。"


def test_revisions_are_kept() -> None:
    result = load(SECOND)
    assert result.serial == "2"
    revised = {(c.level, c.name): c.revise for c in result.intensities if c.revise}
    assert revised[("city", "岡崎市")] == "上方修正"
    assert revised[("station", "岡崎市樫山町＊")] == "追加"
    assert revised[("area", "広島県南西部")] == "追加"


def test_unreceived_intensity() -> None:
    result = load(SAMPLES / "32-35_06_03_240613_VXSE53.xml")
    # A station that has not reported carries the note as its Int.
    [station] = [c for c in result.intensities if c.code == "0321532"]
    assert (station.intensity, station.unreceived, station.raw) == (
        None,
        True,
        "震度５弱以上未入電",
    )
    # A city with no reporting station has only the Condition.
    [town] = [c for c in result.intensities if c.level == "city" and c.code == "0338100"]
    assert (town.intensity, town.unreceived) == (None, True)
    # Next to MaxInt the Condition means the value covers only reporting stations.
    [village] = [c for c in result.intensities if c.level == "city" and c.code == "0636500"]
    assert (village.intensity, village.unreceived) == (Intensity.FOUR, True)


def test_shallow_and_unknown_depth() -> None:
    shallow = load(REAL / "20261106185412_0_VXSE53_270000.xml").hypocenter
    assert shallow is not None and shallow.depth_km == 0.0
    assert str(shallow.depth_km) == "0.0"
    distant = load(SAMPLES / "32-39_05_04_100831_VXSE53.xml")
    assert distant.hypocenter is not None
    assert (distant.hypocenter.name, distant.hypocenter.detailed_name) == (
        "南米西部",
        "チリ中部沿岸",
    )
    assert (distant.hypocenter.latitude, distant.hypocenter.longitude) == (-36.1, -72.6)
    assert distant.hypocenter.depth_km is None
    assert distant.max_intensity is None and distant.intensities == ()


def test_undetermined_magnitude() -> None:
    result = load(SAMPLES / "32-39_11_05_240613_VXSE53.xml")
    assert result.max_intensity is Intensity.SEVEN
    assert result.magnitude is not None
    assert (result.magnitude.value, result.magnitude.condition) == (None, "不明")
    assert result.magnitude.description == "Ｍ８を超える巨大地震"


def test_cancellation_has_only_text() -> None:
    result = load(SAMPLES / "32-35_06_06_100915_VXSE53.xml")
    assert (result.info_type, result.event_id) == ("取消", "20080614084350")
    assert result.text == "先ほどの、震源・震度情報を取り消します。"
    assert result.origin_time is None and result.magnitude is None


def test_unknown_intensity_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    text = SOKUHO.read_text(encoding="utf-8").replace("<MaxInt>4</MaxInt>", "<MaxInt>8</MaxInt>", 1)
    with caplog.at_level(logging.WARNING):
        result = earthquake_info(parse(text, strict=True))
    unknown = [c for c in result.intensities if c.raw == "8"]
    assert unknown and unknown[0].intensity is None and not unknown[0].unreceived
    assert caplog.records


def test_unsupported_coordinate_is_rejected() -> None:
    text = SHINGEN.read_text(encoding="utf-8").replace("+34.9+137.7-40000/", "+34.9/")
    with pytest.raises(ValueError, match="coordinate"):
        earthquake_info(parse(text, strict=True))


def test_other_reports_are_rejected() -> None:
    with pytest.raises(ValueError, match="Not an earthquake information report"):
        earthquake_info(parse(SAMPLES / "15_16_03_241226_VPWW55.xml", strict=True))
