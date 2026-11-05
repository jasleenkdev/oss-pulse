import json

from oss_pulse.extracts import (
    build_extracts,
    denied_terms,
    filter_rows,
    is_denied,
    write_json,
)


def test_denylist_is_case_insensitive_and_checks_all_fields():
    term = denied_terms()[0]
    assert is_denied("safe", f"Some-{term.upper()}-Tool")
    assert not is_denied("safe", None)


def test_filter_counts_suppressed_rows():
    term = denied_terms()[0]
    kept, suppressed = filter_rows(
        [{"name": "ok"}, {"name": f"x/{term}-y"}, {"name": None}], "name"
    )
    assert [row["name"] for row in kept] == ["ok", None]
    assert suppressed == 1


def test_json_is_rounded_and_sorted(tmp_path):
    target = tmp_path / "a.json"
    write_json(target, {"b": 1.23456, "a": 1})
    assert list(json.loads(target.read_text())) == ["a", "b"]
    assert json.loads(target.read_text())["b"] == 1.235


def test_extracts_rebuild_byte_identically(pipeline, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    build_extracts(pipeline, first)
    build_extracts(pipeline, second)
    names = sorted(path.name for path in first.glob("*.json"))
    assert "repos.json" in names
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_extracts_carry_no_denied_text(pipeline, tmp_path):
    build_extracts(pipeline, tmp_path)
    blob = " ".join(path.read_text().lower() for path in tmp_path.glob("*.json"))
    assert not any(term in blob for term in denied_terms())
