import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "verify_readme", Path(__file__).resolve().parents[1] / "scripts" / "verify_readme.py"
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

SECTIONS = "## Scale\n\n{}\n\n## Findings\n\n{}\n\n## Data quality summary\n\n{}\n"


def document(scale="", findings="", quality=""):
    return SECTIONS.format(scale, findings, quality)


def test_matches_at_the_shown_precision():
    assert verify.matches("770,397", 770397)
    assert verify.matches("88.7%", 0.8866)
    assert verify.matches("8.8 h", 8.805)
    assert not verify.matches("8.9 h", 8.805)
    assert not verify.matches("88.7%", 0.87)


def test_strings_must_match_exactly():
    assert verify.matches("a/b", "a/b")
    assert not verify.matches("a/c", "a/b")


def test_passes_a_correct_document():
    text = document("Read <!--m:rows-->1,000<!--/m--> rows.")
    assert verify.check(text, {"rows": 1000}) == []


def test_flags_a_wrong_number():
    errors = verify.check(document("<!--m:rows-->999<!--/m-->"), {"rows": 1000})
    assert "rows: README shows 999, outputs say 1000" in errors


def test_flags_an_unknown_metric():
    errors = verify.check(document("<!--m:mystery-->1<!--/m-->"), {})
    assert "unknown metric: mystery" in errors


def test_flags_an_untagged_number_in_a_checked_section():
    errors = verify.check(document("<!--m:rows-->1<!--/m-->", "We saw 42 things."), {"rows": 1})
    assert any("untagged number in Findings" in error for error in errors)


def test_ignores_code_links_and_names():
    text = document(
        "<!--m:rows-->1<!--/m-->",
        "The p90 of `model_2` is in [the doc](https://x/1).\n1. A list item",
    )
    assert verify.check(text, {"rows": 1}) == []


def test_numbers_outside_checked_sections_are_allowed():
    text = document("<!--m:rows-->1<!--/m-->") + "\n## Other\n\nPort 8080.\n"
    assert verify.check(text, {"rows": 1}) == []


def test_missing_section_fails():
    assert any("missing section" in e for e in verify.check("## Scale\n", {}))


def test_requires_at_least_one_tag():
    assert "no tagged numbers found" in verify.check(document(), {})
