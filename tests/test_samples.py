from pathlib import Path

import pytest

from jmadantic import UnknownBody, parse

SAMPLES = sorted((Path(__file__).parent / "data" / "samples").glob("*.xml"))


def test_sample_corpus_is_complete():
    assert len(SAMPLES) == 546


@pytest.mark.parametrize("path", SAMPLES, ids=lambda path: path.name)
def test_official_sample(path: Path):
    report = parse(path, strict=True)
    assert not isinstance(report.body, UnknownBody)
    assert report.control.date_time.utcoffset() is not None
    assert report.head.report_date_time.utcoffset() is not None
    if report.head.target_date_time is not None:
        assert report.head.target_date_time.utcoffset() is not None
