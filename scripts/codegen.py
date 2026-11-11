"""Fetch pinned JMA sources and regenerate the XML dataclasses and sample corpus."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import os
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
GENERATED = ROOT / "jmadantic" / "_generated"
XSDATA_VERSION = "26.10"
BODY_NAMESPACES = {
    "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/": "MeteBody",
    "http://xml.kishou.go.jp/jmaxml1/body/seismology1/": "SeisBody",
    "http://xml.kishou.go.jp/jmaxml1/body/volcanology1/": "VolcBody",
}


def acquire(filename: str, expected_hash: str) -> Path:
    """Reuse verified downloads; never silently accept a changed upstream artifact."""
    target = VENDOR / filename
    if not target.exists():
        url = "https://xml.kishou.go.jp/" + urllib.parse.quote(filename)
        req = urllib.request.Request(url, headers={"User-Agent": "jmadantic-codegen/0.1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise RuntimeError(f"SHA-256 mismatch for {filename}")
        target.write_bytes(data)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError(f"SHA-256 mismatch for {target}; remove it to download again")
    return target


def extract(archive: Path, destination: Path, suffix: str) -> None:
    """Copy only flat, uniquely named source files from the pinned archives."""
    destination.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    with ZipFile(archive) as source:
        for entry in sorted(source.infolist(), key=lambda item: item.filename):
            if entry.is_dir() or not entry.filename.lower().endswith(suffix):
                continue
            name = Path(entry.filename).name
            if name in names:
                raise RuntimeError(f"Duplicate archive filename: {name}")
            names.add(name)
            (destination / name).write_bytes(source.read(entry))


def patch_nullable(source: str) -> tuple[str, int]:
    """Add None only to generated scalar values using the XSD Nullable unions.

    xsdata emits a required dataclass field for the union of a scalar and the
    empty-string enum. Empty XML elements supply no value, so the field needs
    a default. AST ranges avoid matching comments or unrelated attributes.
    """
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, list[str]]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "value":
            continue
        if not any(
            isinstance(child, ast.Name) and "Nullable" in child.id
            for child in ast.walk(node.annotation)
        ):
            continue
        if not isinstance(node.value, ast.Call) or node.end_lineno is None:
            raise RuntimeError("Unexpected nullable field format")
        if any(kw.arg == "default" for kw in node.value.keywords):
            raise RuntimeError("Nullable field already has a default; review xsdata output")
        node.annotation = ast.BinOp(node.annotation, ast.BitOr(), ast.Constant(None))
        node.value.keywords.insert(0, ast.keyword(arg="default", value=ast.Constant(None)))
        segment = [" " * node.col_offset + ast.unparse(node) + "\n"]
        edits.append((node.lineno - 1, node.end_lineno, segment))
    if not edits:
        raise RuntimeError("No nullable fields patched; review xsdata output")
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = replacement
    return "".join(lines), len(edits)


def body_aliases(source: str) -> str:
    aliases: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef):
            continue
        meta = next(
            (
                child
                for child in node.body
                if isinstance(child, ast.ClassDef) and child.name == "Meta"
            ),
            None,
        )
        if meta is None:
            continue
        values: dict[str, str] = {}
        for field in meta.body:
            if (
                not isinstance(field, ast.Assign)
                or not isinstance(field.value, ast.Constant)
                or not isinstance(field.value.value, str)
            ):
                continue
            for target in field.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = field.value.value
        if values.get("name", node.name) != "Body":
            continue
        alias = BODY_NAMESPACES.get(values.get("namespace", ""))
        if alias is not None:
            if alias in aliases:
                raise RuntimeError(f"Multiple Body classes for {alias}")
            aliases[alias] = node.name
    if set(aliases) != set(BODY_NAMESPACES.values()):
        raise RuntimeError(f"Missing Body classes: {aliases}")
    return "".join(
        f"from .jmx import {name} as {alias}\n" for alias, name in sorted(aliases.items())
    )


def main() -> None:
    version = importlib.metadata.version("xsdata")
    if version != XSDATA_VERSION:
        raise RuntimeError(f"Expected xsdata {XSDATA_VERSION}, got {version}")
    manifest = tomllib.loads((ROOT / "scripts" / "manifest.toml").read_text(encoding="utf-8"))
    VENDOR.mkdir(exist_ok=True)
    paths = {key: acquire(value["filename"], value["sha256"]) for key, value in manifest.items()}
    extract(paths["schema"], VENDOR / "schema", ".xsd")
    extract(paths["samples"], ROOT / "tests" / "data" / "samples", ".xml")
    extract(paths["codes"], VENDOR / "codes", ".xlsx")
    # xsdata invokes ruff as a subprocess. Include the current venv on Windows.
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    # xsdata normalizes leading underscores in package names and writes parent
    # __init__.py files. Stage its output so public exports cannot be overwritten.
    with tempfile.TemporaryDirectory(dir=VENDOR) as staging:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "xsdata",
                "generate",
                str(VENDOR / "schema" / "jmx.xsd"),
                "--package",
                "jmadantic._generated.jmx",
                "--structure-style",
                "single-package",
            ],
            cwd=staging,
            env=env,
            check=True,
        )
        source = (Path(staging) / "jmadantic" / "generated" / "jmx.py").read_text(encoding="utf-8")
    patched, count = patch_nullable(source)
    header = (
        "# Generated by scripts/codegen.py; do not edit.\n"
        f"# Source: {manifest['schema']['filename']}\n"
        f"# SHA-256: {manifest['schema']['sha256']}\n"
        f"# Retrieved: {manifest['schema']['retrieved']}; xsdata: {version}\n"
    )
    GENERATED.mkdir(parents=True, exist_ok=True)
    model = GENERATED / "jmx.py"
    model.write_text(header + patched, encoding="utf-8", newline="\n")
    (GENERATED / "__init__.py").write_text(header, encoding="utf-8", newline="\n")
    (GENERATED / "aliases.py").write_text(
        header + body_aliases(patched), encoding="utf-8", newline="\n"
    )
    print(f"Patched {count} nullable value fields")


if __name__ == "__main__":
    main()
