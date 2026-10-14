"""Tests for REPRO-1's verify_run (src/analysis/verify_run.py). No database needed."""
import json

from src.analysis import verify_run as vr

EXPECTED = {
    "pipeline_mode": "snapshot",
    "row_counts": {"dim_site": 300, "fact_observation": 25108},
    "hotspots_by_stratum_realm": {"europe/marine": 2, "us/freshwater": 16},
    "top_regions": [{"region_code": "MEX-2723", "rank": 1, "score": 0.762436},
                    {"region_code": "MEX-2730", "rank": 2, "score": 0.7125}],
}


def fresh() -> dict:
    return json.loads(json.dumps(EXPECTED))


def failures(actual: dict) -> list[str]:
    return [name for name, ok, _, _ in vr.compare(EXPECTED, actual) if not ok]


# ---------------------------------------------------------------- compare()

def test_identical_results_pass():
    assert failures(fresh()) == []


def test_different_row_count_fails_only_that_item():
    actual = fresh()
    actual["row_counts"]["fact_observation"] += 1
    assert failures(actual) == ["row_counts:fact_observation"]


def test_missing_and_extra_items_fail():
    actual = fresh()
    del actual["row_counts"]["dim_site"]
    actual["hotspots_by_stratum_realm"]["gemstat_asia/freshwater"] = 1
    assert failures(actual) == ["row_counts:dim_site", "hotspots_by_stratum_realm:gemstat_asia/freshwater"]


def test_reordered_top_regions_fail():
    actual = fresh()
    actual["top_regions"].reverse()
    assert failures(actual) == ["top_regions:1", "top_regions:2"]


def test_shorter_top_list_fails():
    actual = fresh()
    actual["top_regions"].pop()
    assert failures(actual) == ["top_regions:2"]


def test_different_mode_fails():
    actual = fresh()
    actual["pipeline_mode"] = "live"
    assert failures(actual) == ["pipeline_mode"]


# ---------------------------------------------------------------- file and CLI

def test_write_expected_is_deterministic(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    vr.write_expected(EXPECTED, first)
    vr.write_expected(fresh(), second)
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text()) == EXPECTED


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vr, "get_engine", lambda: None)
    monkeypatch.setattr(vr, "collect", lambda engine: fresh())
    path = tmp_path / "expected.json"
    assert vr.main(["--expected", str(path)]) == 1                       # no expected file yet
    assert vr.main(["--write-expected", "--expected", str(path)]) == 0
    assert vr.main(["--expected", str(path)]) == 0                       # matches
    tampered = fresh()
    tampered["row_counts"]["dim_site"] = 1
    vr.write_expected(tampered, path)
    assert vr.main(["--expected", str(path)]) == 1                       # differs
    assert "FAIL  row_counts:dim_site" in capsys.readouterr().out


def test_pipeline_mode_defaults_to_snapshot(monkeypatch):
    monkeypatch.delattr(vr.cfg, "pipeline_mode", raising=False)  # Antonio's function not merged yet
    monkeypatch.setattr(vr.cfg, "load_env", lambda: None)         # ignore any local .env
    monkeypatch.delenv("PIPELINE_MODE", raising=False)
    assert vr.pipeline_mode() == "snapshot"