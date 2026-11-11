from dataclasses import replace
from pathlib import Path

import pytest

from jmadantic import data_type_code, parse

SHARED = Path(__file__).parent / "golden" / "_shared"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("気象警報・注意報（Ｒ０６）（大雨）", "VPWW55"),
        ("気象警報・注意報（Ｒ０６）（土砂）", "VPWW56"),
        ("気象警報・注意報（Ｒ０６）（高潮）", "VPWW57"),
        ("気象警報・注意報（Ｒ０６）（暴風）", "VPWW58"),
        ("気象警報・注意報（Ｒ０６）（波浪）", "VPWW59"),
        ("気象警報・注意報（Ｒ０６）（大雪）", "VPWW60"),
        ("気象警報・注意報（Ｒ０６）（その他注意報）", "VPWW61"),
        ("気象警報・注意報（Ｒ０６）（集約通報）", "VPWS50"),
        ("気象警報・注意報時系列情報（Ｒ０６）", "VPWP50"),
        ("指定河川洪水予報", "VXKO"),
        ("水位周知河川に関する情報", "VXSU"),
        ("気象警報・注意報（Ｈ２７）", "VPWW54"),
        ("気象特別警報・警報・注意報", "VPWW53"),
        ("震度速報", "VXSE51"),
        ("噴火速報", "VFVO56"),
        ("未知の電文", None),
        ("気象警報・注意報（R06）（大雨）", None),
        ("台風解析・予報情報（３日予報）", None),
        ("南海トラフ地震関連解説情報", None),
    ],
)
def test_exact_control_title_lookup(title, expected):
    report = parse(SHARED / "vpww55_wakkanai_20200622T2300.xml", strict=True)
    report = replace(report, control=replace(report.control, title=title))
    assert data_type_code(report) == expected
