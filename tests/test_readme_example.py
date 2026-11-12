import ast
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from feed_helpers import feed

from jmadantic import WarningState
from jmadantic.feed import FeedClient, FeedKind, HttpRequest, HttpResponse, UrllibHttpClient

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / "tests/data/samples/15_16_03_241226_VPWW55.xml"
README = (ROOT / "README.md").read_text(encoding="utf-8")
BLOCK = README.split("```python\n", 1)[1].split("```", 1)[0]


class FakeHttp:
    def __init__(self, body: bytes | Exception) -> None:
        self.responses = iter([HttpResponse(200, {}, feed("sample")), body])

    def send(self, req: HttpRequest) -> HttpResponse:
        response = next(self.responses, HttpResponse(304, {}, b""))
        if isinstance(response, Exception):
            raise response
        if isinstance(response, bytes):
            return HttpResponse(200, {}, response)
        return response


def test_readme_example_runs_with_local_sample(capsys):
    http = FakeHttp(SAMPLE.read_bytes())
    with patch.object(UrllibHttpClient, "send", side_effect=http.send):
        namespace = {}
        exec(compile(BLOCK, "README.md", "exec"), namespace)
    assert namespace["state"].by_city("0121400")
    output = capsys.readouterr().out
    assert "出典：気象庁ホームページ" in output
    assert "実行者が加工して作成" in output


def test_runnable_example_uses_the_readme_processing_function():
    example = ast.parse((ROOT / "examples/poll_warnings.py").read_text(encoding="utf-8"))
    readme = ast.parse(BLOCK)
    functions = [
        next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        for tree in (example, readme)
    ]
    assert ast.dump(functions[0]) == ast.dump(functions[1])


@pytest.mark.parametrize("failure", [None, "apply", "parse", "fetch"])
def test_readme_ack_and_retry_behavior(failure, caplog):
    # Execute only the imports, logger and function, with no live client construction.
    tree = ast.parse(BLOCK)
    function_index = next(
        i for i, node in enumerate(tree.body) if isinstance(node, ast.FunctionDef)
    )
    tree.body = tree.body[: function_index + 1]
    assert isinstance(tree.body[-1], ast.FunctionDef)
    namespace = {}
    exec(compile(tree, "README.md", "exec"), namespace)
    body = SAMPLE.read_bytes()
    if failure == "parse":
        body = b"<invalid"
    response = OSError("test fetch failure") if failure == "fetch" else body
    seen = set()
    client = FeedClient(
        FeedKind.EXTRA,
        http=FakeHttp(response),
        seen=seen,
        clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
        min_interval=0,
        unsafe_min_interval=True,
    )
    state = WarningState()
    with patch.object(
        state,
        "apply",
        wraps=state.apply,
        side_effect=ValueError("test apply failure") if failure == "apply" else None,
    ):
        namespace["update_once"](client, state)
    if failure == "fetch":
        assert not seen
        assert [entry.id for entry in client.poll()] == ["sample"]
    else:
        assert seen == {"sample"}
        assert client.poll() == []
    if failure is None:
        assert state.by_city("0121400")
    else:
        assert not state.by_city("0121400")
        assert "sample" in caplog.text
        assert caplog.records[-1].exc_info is not None


def test_offline_script_uses_only_injected_http(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "poll_warnings", ROOT / "examples/poll_warnings.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", ["poll_warnings", "--offline-sample", str(SAMPLE)])
    module.main()
    assert "現在の発表状況ではありません" in capsys.readouterr().out
