"""Fetch pinned JMA sources and regenerate the XML dataclasses and sample corpus."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
GENERATED = ROOT / "pyjmaxml" / "_generated"
XSDATA_VERSION = "26.10"
BODY_NAMESPACES = {
    "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/": "MeteBody",
    "http://xml.kishou.go.jp/jmaxml1/body/seismology1/": "SeisBody",
    "http://xml.kishou.go.jp/jmaxml1/body/volcanology1/": "VolcBody",
}


def acquire(filename: str, expected_hash: str, *, offline: bool = False) -> Path:
    """Reuse verified downloads; never silently accept a changed upstream artifact."""
    target = VENDOR / filename
    if not target.exists():
        if offline:
            raise FileNotFoundError(f"Missing cached source in offline mode: {target}")
        url = "https://xml.kishou.go.jp/" + urllib.parse.quote(filename)
        req = urllib.request.Request(url, headers={"User-Agent": "pyjmaxml-codegen/0.1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise RuntimeError(f"SHA-256 mismatch for {filename}")
        target.write_bytes(data)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError(f"SHA-256 mismatch for {target}; remove it to download again")
    return target


def _code(value: object, width: int) -> str:
    # The city workbook stores two seven-digit Kobe codes as numeric cells.
    # Convert those integers directly; never infer missing leading zeroes.
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or len(value) != width
    ):
        raise ValueError(f"Expected a {width}-digit code, got {value!r}")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected a nonempty area name, got {value!r}")
    return value


def city_codes(data: bytes) -> dict[str, tuple[str, str, str]]:
    """Read cities flagged for weather warnings and their explicit parent links."""
    book = load_workbook(BytesIO(data), read_only=True, data_only=False)
    try:
        city = book["AreaInformationCity"]
        relation = book["AreaForecastLocalM（関係表　警報・注意報"]
        if city["A3"].value != "@code" or city["C3"].value != "@name":
            raise ValueError("Unexpected AreaInformationCity columns")
        if any(relation[f"{column}3"].value != "コード\n(@code)" for column in "ACE"):
            raise ValueError("Unexpected AreaForecastLocalM relationship columns")
        parents: dict[str, tuple[str, str]] = {}
        for row in relation.iter_rows(min_row=4, max_col=6, values_only=True):
            if row[0] is None:
                continue
            code = _code(row[0], 6)
            if code in parents:
                raise ValueError(f"Duplicate grouping code: {code}")
            parents[code] = (_code(row[4], 6), _code(row[2], 6))
        result: dict[str, tuple[str, str, str]] = {}
        for row in city.iter_rows(min_row=4, max_col=6, values_only=True):
            # Column F explicitly marks use in weather warnings. Other rows
            # describe different information products and may have no parent.
            if row[5] != 1:
                continue
            code = _code(row[0], 7)
            parent = _code(row[4], 6)
            if code in result:
                raise ValueError(f"Duplicate city code: {code}")
            if parent not in parents:
                raise ValueError(f"Missing forecast parent {parent} for city {code}")
            prefecture, subdivision = parents[parent]
            result[code] = (_name(row[2]), prefecture, subdivision)
        if not result:
            raise ValueError("No weather-warning cities found")
        return result
    finally:
        book.close()


def river_codes(data: bytes, sheet: str, width: int) -> dict[str, str]:
    """Read the published code/name columns, allowing a header-only source."""
    book = load_workbook(BytesIO(data), read_only=True, data_only=False)
    try:
        table = book[sheet]
        if table["A3"].value != "@code" or table["B3"].value != "@name":
            raise ValueError(f"Unexpected {sheet} columns")
        result: dict[str, str] = {}
        for row in table.iter_rows(min_row=4, max_col=2, values_only=True):
            if row == (None, None):
                continue
            code = _code(row[0], width)
            if code in result:
                raise ValueError(f"Duplicate river code: {code}")
            result[code] = _name(row[1])
        return result
    finally:
        book.close()


def city_parent_codes(data: bytes) -> dict[str, str]:
    """Relate subdivisions only to parent codes present in the same source sheet."""
    book = load_workbook(BytesIO(data), read_only=True, data_only=False)
    try:
        sheet = book["AreaInformationCity"]
        if sheet["A3"].value != "@code":
            raise ValueError("Unexpected AreaInformationCity columns")
        codes = {
            _code(row[0], 7)
            for row in sheet.iter_rows(min_row=4, max_col=1, values_only=True)
            if row[0] is not None
        }
        return {
            code: code[:5] + "00"
            for code in codes
            if not code.endswith("00") and code[:5] + "00" in codes
        }
    finally:
        book.close()


def generate_codes(archive: Path, destination: Path) -> None:
    """Generate deterministic dict constants from the verified code archive."""
    with ZipFile(archive) as source:
        tables = [
            ("AreaInformationCity-AreaForecastLocalM", "_area_city.py", "AREA_CITY"),
            ("AreaInformationCity-AreaForecastLocalM", "_area_city_parent.py", "AREA_CITY_PARENT"),
            ("AreaFloodForecast", "_area_flood_forecast.py", "AREA_FLOOD_FORECAST"),
            ("AreaWaterLevelWarning", "_area_water_level_warning.py", "AREA_WATER_LEVEL_WARNING"),
        ]
        outputs: dict[str, str] = {}
        for table, filename, constant in tables:
            members = [name for name in source.namelist() if name.endswith(f"_{table}.xlsx")]
            if len(members) != 1:
                raise ValueError(f"Expected one workbook for {table}, got {members}")
            member = members[0]
            data = source.read(member)
            if constant == "AREA_CITY":
                values = city_codes(data)
            elif constant == "AREA_CITY_PARENT":
                values = city_parent_codes(data)
            else:
                values = river_codes(data, table, 12 if table == "AreaFloodForecast" else 10)
            value_type = "tuple[str, str, str]" if constant == "AREA_CITY" else "str"
            header = (
                "# Generated by scripts/codegen.py; do not edit.\n"
                f"# Archive: {archive.name}\n"
                f"# Archive SHA-256: {hashlib.sha256(archive.read_bytes()).hexdigest()}\n"
                f"# Workbook: {member}\n"
                f"# Workbook SHA-256: {hashlib.sha256(data).hexdigest()}\n"
            )
            lines = [header, f"\n{constant}: dict[str, {value_type}] = {{\n"]
            for code, value in sorted(values.items()):
                formatted = (
                    "(" + ", ".join(json.dumps(part, ensure_ascii=False) for part in value) + ")"
                    if isinstance(value, tuple)
                    else json.dumps(value, ensure_ascii=False)
                )
                lines.append(f"    {json.dumps(code)}: {formatted},\n")
            lines.append("}\n")
            if not values:
                lines = [header, f"\n{constant}: dict[str, {value_type}] = {{}}\n"]
            outputs[filename] = "".join(lines)
            print(f"{constant}: {len(values)} entries")
        # Validate all tables before writing any generated module.
        destination.mkdir(parents=True, exist_ok=True)
        for filename, text in outputs.items():
            (destination / filename).write_text(text, encoding="utf-8", newline="\n")


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Require verified cached sources")
    parser.add_argument(
        "--codes-only", action="store_true", help="Regenerate only area code tables"
    )
    args = parser.parse_args()
    manifest = tomllib.loads((ROOT / "scripts" / "manifest.toml").read_text(encoding="utf-8"))
    VENDOR.mkdir(exist_ok=True)
    keys = ["codes"] if args.codes_only else list(manifest)
    paths = {
        key: acquire(manifest[key]["filename"], manifest[key]["sha256"], offline=args.offline)
        for key in keys
    }
    if args.codes_only:
        generate_codes(paths["codes"], ROOT / "pyjmaxml" / "codes")
        return
    version = importlib.metadata.version("xsdata")
    if version != XSDATA_VERSION:
        raise RuntimeError(f"Expected xsdata {XSDATA_VERSION}, got {version}")
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
                "pyjmaxml._generated.jmx",
                "--structure-style",
                "single-package",
            ],
            cwd=staging,
            env=env,
            check=True,
        )
        source = (Path(staging) / "pyjmaxml" / "generated" / "jmx.py").read_text(encoding="utf-8")
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
    generate_codes(paths["codes"], ROOT / "pyjmaxml" / "codes")


if __name__ == "__main__":
    main()
