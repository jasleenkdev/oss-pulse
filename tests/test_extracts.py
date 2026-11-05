import json

from oss_pulse.extracts import build_extracts, write_json
from oss_pulse.reports import write_data_quality_report


def test_json_is_rounded_and_sorted(tmp_path):
    target = tmp_path / "a.json"
    write_json(target, {"b": 1.23456, "a": 1})
    assert list(json.loads(target.read_text())) == ["a", "b"]
    assert json.loads(target.read_text())["b"] == 1.2346


def test_extracts_rebuild_byte_identically(pipeline, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    build_extracts(pipeline, first)
    build_extracts(pipeline, second)
    names = sorted(path.name for path in first.glob("*.json"))
    assert "repos.json" in names
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_extracts_keep_every_ranked_repo(pipeline, tmp_path):
    build_extracts(pipeline, tmp_path)
    repos = json.loads((tmp_path / "repos.json").read_text())
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert len(repos) == meta["pipeline"]["repos_scored"]
    assert [repo["score_rank"] for repo in repos] == list(range(1, len(repos) + 1))


def test_extracts_pass_third_party_text_through_unchanged(pipeline, tmp_path):
    build_extracts(pipeline, tmp_path)
    bots = json.loads((tmp_path / "bots.json").read_text())
    assert "dependabot[bot]" in {account["login"] for account in bots["accounts"]}


def test_quality_report_names_no_accounts(pipeline, tmp_path):
    # The report is a tracked doc, so third-party account names stay on the dashboard.
    target = tmp_path / "data_quality.md"
    write_data_quality_report(pipeline, target)
    assert "[bot]" not in target.read_text()
