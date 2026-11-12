"""Run both accepted and deliberately rejected Tracker calls in CI."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("source", "errors"), [("tracker_valid.py", 0), ("tracker_invalid.py.txt", 1)]
)
def test_tracker_area_literal_diagnostics(tmp_path, source, errors):
    target = tmp_path / "probe.py"
    target.write_bytes((ROOT / "tests/typecheck" / source).read_bytes())
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        json.dumps(
            {
                "include": ["probe.py"],
                "extraPaths": [ROOT.as_posix()],
                "venvPath": ROOT.as_posix(),
                "venv": ".venv",
                "pythonVersion": "3.11",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["uv", "run", "pyright", "--outputjson", "--project", str(config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == (1 if errors else 0), result.stderr + result.stdout
    output = json.loads(result.stdout)
    assert output["summary"]["filesAnalyzed"] == 1
    assert output["summary"]["errorCount"] == errors
    assert output["summary"]["warningCount"] == 0
    if errors:
        (diagnostic,) = output["generalDiagnostics"]
        assert diagnostic["rule"] == "reportArgumentType"
        assert diagnostic["range"]["start"]["line"] == 3
