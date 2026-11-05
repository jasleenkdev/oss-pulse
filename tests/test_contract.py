import shutil

import duckdb

from oss_pulse.config import CONTRACTS_DIR
from oss_pulse.contract import load_contract, validate

CONTRACT = load_contract(CONTRACTS_DIR / "firstpr_export_v1.yml")


def export(pipeline):
    return pipeline.gold_dir / "firstpr_export.parquet"


def mutate(pipeline, tmp_path, select_sql):
    target = tmp_path / "mutated.parquet"
    source = export(pipeline)
    duckdb.execute(
        f"copy (select {select_sql} from read_parquet('{source}')) to '{target}' (format parquet)"
    )
    return target


def test_fixture_export_conforms(pipeline):
    assert validate(export(pipeline), CONTRACT) == []


def test_export_has_rows(pipeline):
    assert duckdb.sql(f"select count(*) from read_parquet('{export(pipeline)}')").fetchall()[0][0]


def test_contract_covers_every_column(pipeline, tmp_path):
    copy = tmp_path / "copy.parquet"
    shutil.copy(export(pipeline), copy)
    assert not [v for v in validate(copy, CONTRACT) if "undeclared" in v]


def test_detects_a_missing_column(pipeline, tmp_path):
    target = mutate(pipeline, tmp_path, "* exclude (language)")
    assert "missing column: language" in validate(target, CONTRACT)


def test_detects_an_undeclared_column(pipeline, tmp_path):
    target = mutate(pipeline, tmp_path, "*, 1 as surprise")
    assert "undeclared column: surprise" in validate(target, CONTRACT)


def test_detects_a_type_change(pipeline, tmp_path):
    target = mutate(pipeline, tmp_path, "* replace (cast(repo_id as varchar) as repo_id)")
    assert any(v.startswith("repo_id: type VARCHAR") for v in validate(target, CONTRACT))


def test_detects_nulls_in_a_required_column(pipeline, tmp_path):
    target = mutate(pipeline, tmp_path, "* replace (cast(null as varchar) as repo_name)")
    assert any("non-nullable" in v for v in validate(target, CONTRACT))


def test_detects_out_of_range_scores(pipeline, tmp_path):
    target = mutate(pipeline, tmp_path, "* replace (cast(150 as double) as friendliness_score)")
    assert any("above 100" in v for v in validate(target, CONTRACT))


def test_detects_duplicate_keys(pipeline, tmp_path):
    source = export(pipeline)
    target = tmp_path / "dupes.parquet"
    duckdb.execute(
        f"""copy (select * from read_parquet('{source}') union all
                  select * from read_parquet('{source}'))
            to '{target}' (format parquet)"""
    )
    assert any("duplicate" in v for v in validate(target, CONTRACT))
