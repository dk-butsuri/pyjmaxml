import ast
import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from feed_helpers import feed

from pyjmaxml import WarningState
from pyjmaxml.feed import (
    AsyncFeedClient,
    FeedClient,
    FeedKind,
    FeedTransportError,
    HttpRequest,
    HttpResponse,
    UrllibHttpClient,
)

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / "tests/data/samples/15_16_03_241226_VPWW55.xml"
# The guide holds the detailed examples moved out of the README.
README = "\n".join(
    (ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "docs/guide.md")
)
BLOCK = next(
    block.split("```", 1)[0]
    for block in README.split("```python\n")[1:]
    if "def update_once(client: FeedClient" in block.split("```", 1)[0]
)


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


def test_runnable_example_keeps_the_readme_processing_body():
    example = ast.parse((ROOT / "examples/poll_warnings.py").read_text(encoding="utf-8"))
    readme = ast.parse(BLOCK)
    functions = [
        next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        for tree in (example, readme)
    ]
    # The script additionally forwards an explicit clock value for online runs.
    # All fetch/parse/apply/ack control flow must stay the same as the README.
    for node in ast.walk(functions[0]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "apply":
                node.keywords = [keyword for keyword in node.keywords if keyword.arg != "now"]
    assert [ast.dump(node) for node in functions[0].body] == [
        ast.dump(node) for node in functions[1].body
    ]


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
    # The bundled transports report connection and read failures as FeedTransportError.
    response = FeedTransportError("test fetch failure") if failure == "fetch" else body
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


@pytest.mark.parametrize("offline", [False, True])
def test_script_only_supplies_current_time_online(monkeypatch, offline):
    spec = importlib.util.spec_from_file_location(
        "poll_warnings", ROOT / "examples/poll_warnings.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = set()
    client = FeedClient(FeedKind.EXTRA, http=FakeHttp(SAMPLE.read_bytes()), seen=seen)
    state = WarningState()
    monkeypatch.setattr(module, "FeedClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(module, "WarningState", lambda: state)
    argv = ["poll_warnings"] + (["--offline-sample", str(SAMPLE)] if offline else [])
    monkeypatch.setattr("sys.argv", argv)
    before = datetime.now(UTC)
    with patch.object(state, "apply", wraps=state.apply) as apply:
        module.main()
    supplied_now = apply.call_args.kwargs["now"]
    if offline:
        assert supplied_now is None
        assert state.by_city("0121400")
    else:
        assert before <= supplied_now <= datetime.now(UTC)
        assert not state.by_city("0121400")
    assert seen == {"sample"}  # Time-rejected reports are also acknowledged.


def test_readme_tracker_examples_run_offline(monkeypatch, capsys):
    from tracker_helpers import BASE, WARNING, FakeHttp, atom_entries

    from pyjmaxml import Tracker, parse

    blocks = [
        block.split("```", 1)[0]
        for block in README.split("```python\n")[1:]
        if "from pyjmaxml import Tracker" in block.split("```", 1)[0]
    ]
    assert len(blocks) == 2
    for block in blocks:
        http = FakeHttp()
        entry = http.document(WARNING, "011000")
        http.queue(BASE + "extra.xml", atom_entries(entry))
        monkeypatch.setattr(
            "pyjmaxml.Tracker",
            lambda *a, http=http, **kw: Tracker(
                *a, **kw, http=http, clock=lambda: parse(WARNING).control.date_time
            ),
        )
        namespace = {}
        exec(compile(block, "README.md", "exec"), namespace)
        assert namespace["tracker"].updated_at is not None
        assert not namespace["result"].errors
        # The sample's Hokkaido warning is filtered when watching Osaka/Nagano.
        assert http.counts[entry.url] == 0
    assert "出典：気象庁ホームページ" in capsys.readouterr().out


def test_tracker_example_script_runs_offline(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("track_areas", ROOT / "examples/track_areas.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", ["track_areas", "--offline-sample"])
    module.main()
    output = capsys.readouterr().out
    assert "現在の発表状況ではありません" in output
    assert "北海道稚内市" in output
    assert "大雨" in output


ASYNC_BLOCK = next(
    block.split("```", 1)[0]
    for block in README.split("```python\n")[1:]
    if "AsyncFeedClient" in block.split("```", 1)[0]
)


@pytest.mark.parametrize("failure", [None, "fetch"])
def test_readme_async_example(failure):
    # Execute only the imports and update_once, then drive it with an offline transport.
    tree = ast.parse(ASYNC_BLOCK)
    names = [node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
    assert names == ["update_once", "main"]
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.AsyncFunctionDef) and node.name == "main")
    ]
    namespace = {}
    exec(compile(tree, "README.md", "exec"), namespace)

    class FakeAsyncHttp:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    HttpResponse(200, {}, feed("broken", "sample")),
                    HttpResponse(200, {}, SAMPLE.read_bytes()),
                    FeedTransportError("test fetch failure")
                    if failure
                    else HttpResponse(200, {}, b"<invalid"),
                ]
            )

        async def send(self, req: HttpRequest) -> HttpResponse:
            response = next(self.responses, HttpResponse(304, {}, b""))
            if isinstance(response, Exception):
                raise response
            return response

    seen = set()
    client = AsyncFeedClient(
        FeedKind.EXTRA,
        http=FakeAsyncHttp(),
        seen=seen,
        clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
        min_interval=0,
        unsafe_min_interval=True,
        max_concurrency=1,
    )
    state = WarningState()
    asyncio.run(namespace["update_once"](client, state))
    assert state.by_city("0121400")
    if failure:
        assert seen == {"sample"}
        assert [entry.id for entry in asyncio.run(client.poll())] == ["broken"]
    else:
        # Unparsable reports are acknowledged and dropped.
        assert seen == {"sample", "broken"}
