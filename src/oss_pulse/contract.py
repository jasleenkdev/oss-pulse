"""Checks a Parquet export against a versioned YAML data contract."""

from __future__ import annotations

from pathlib import Path

import duckdb
import yaml


def load_contract(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _quote(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def validate(parquet_path: Path, contract: dict) -> list[str]:
    """Return every violation of the contract. An empty list means the export conforms."""
    connection = duckdb.connect()
    source = f"read_parquet('{parquet_path}')"
    described = connection.execute(f"describe select * from {source}").fetchall()
    actual = {row[0]: row[1] for row in described}
    expected = {column["name"]: column for column in contract["columns"]}
    violations: list[str] = []

    for name in expected.keys() - actual.keys():
        violations.append(f"missing column: {name}")
    for name in actual.keys() - expected.keys():
        violations.append(f"undeclared column: {name}")

    for name, spec in expected.items():
        if name not in actual:
            continue
        column = _quote(name)
        if actual[name] != spec["type"]:
            violations.append(f"{name}: type {actual[name]}, contract says {spec['type']}")
        if not spec.get("nullable", False):
            nulls = connection.execute(
                f"select count(*) from {source} where {column} is null"
            ).fetchone()[0]
            if nulls:
                violations.append(f"{name}: {nulls} nulls in a non-nullable column")
        if "min" in spec:
            below = connection.execute(
                f"select count(*) from {source} where {column} < {spec['min']}"
            ).fetchone()[0]
            if below:
                violations.append(f"{name}: {below} values below {spec['min']}")
        if "max" in spec:
            above = connection.execute(
                f"select count(*) from {source} where {column} > {spec['max']}"
            ).fetchone()[0]
            if above:
                violations.append(f"{name}: {above} values above {spec['max']}")
        if spec.get("unique"):
            duplicates = connection.execute(
                f"select count(*) - count(distinct {column}) from {source}"
            ).fetchone()[0]
            if duplicates:
                violations.append(f"{name}: {duplicates} duplicate values")
        if "equals" in spec:
            other = connection.execute(
                f"select count(*) from {source} where {column} <> '{spec['equals']}'"
            ).fetchone()[0]
            if other:
                violations.append(f"{name}: {other} rows differ from {spec['equals']}")
    return violations
