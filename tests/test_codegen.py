import ast

import pytest

from scripts.codegen import BODY_NAMESPACES, acquire, body_aliases, patch_nullable


def test_nullable_patch_handles_single_and_multiline_fields():
    source = """
from dataclasses import dataclass, field
from enum import Enum
class NullablefloatValue(Enum):
    EMPTY = ''
@dataclass(kw_only=True)
class Speed:
    value: float | NullablefloatValue = field()
@dataclass(kw_only=True)
class Distance:
    value: float | NullablefloatValue = field(
        metadata={'type': 'Value'}
    )
@dataclass(kw_only=True)
class Other:
    value: str = field()
"""
    result, count = patch_nullable(source)
    assert count == 2
    # The postprocessor must produce valid Python and keep field metadata.
    namespace = {}
    exec(compile(result, "<generated>", "exec"), namespace)
    assert namespace["Speed"]().value is None
    assert namespace["Distance"]().value is None
    assert namespace["Distance"].__dataclass_fields__["value"].metadata == {"type": "Value"}
    with pytest.raises(TypeError):
        namespace["Other"]()


def test_nullable_patch_fails_when_generator_format_changes():
    with pytest.raises(RuntimeError, match="No nullable fields"):
        patch_nullable("value: float = field()")
    with pytest.raises(RuntimeError, match="already has a default"):
        patch_nullable("value: float | NullablefloatValue = field(default=None)")


def test_body_aliases_follow_namespaces_instead_of_class_numbers():
    source = "\n".join(
        f"class Body{index}:\n    class Meta:\n"
        f"        name = 'Body'\n        namespace = {namespace!r}\n"
        for index, namespace in enumerate(BODY_NAMESPACES, 91)
    )
    aliases = body_aliases(source)
    ast.parse(aliases)
    assert "Body91 as MeteBody" in aliases
    assert "Body92 as SeisBody" in aliases
    assert "Body93 as VolcBody" in aliases
    with pytest.raises(RuntimeError, match="Missing Body classes"):
        body_aliases("")


def test_download_cache_rejects_a_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.codegen.VENDOR", tmp_path)
    (tmp_path / "source.zip").write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        acquire("source.zip", "0" * 64)
