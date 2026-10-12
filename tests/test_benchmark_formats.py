"""BENCH-1: format benchmark and partition pruning on staging data written with the real writer."""
import pandas as pd

from src.analysis import benchmark_formats as bf
from tests.test_eda import make_staging


def test_benchmark_report_and_pruning(isolated_dirs, tmp_path, monkeypatch):
    data, _ = isolated_dirs
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    obs, _ = make_staging(data)
    report = bf.run(repeats=1, include_raw=False, docs_dir=tmp_path / "docs")
    text = report.read_text(encoding="utf-8")
    assert "## 2. Format comparison" in text and "## 3. Partition pruning" in text
    assert "larger)" in text and "files and" in text and "formats that kept every column type" in text

    fmt = pd.read_csv(tmp_path / "out" / "benchmark" / "format_benchmark.csv")
    assert list(fmt["format"]) == ["csv", "json", "parquet"]
    assert fmt["rows_round_trip_ok"].all() and (fmt["rows"] == len(obs)).all()
    by = fmt.set_index("format")
    assert by.loc["parquet", "types_preserved"] and not by.loc["csv", "types_preserved"]   # dates/bools lost in CSV
    assert by.loc["json", "size_mb"] > by.loc["parquet", "size_mb"]

    prune = pd.read_csv(tmp_path / "out" / "benchmark" / "partition_pruning.csv")
    full, part = prune.iloc[0], prune.iloc[1]
    assert part["files_opened"] == 1 < full["files_opened"]
    assert 0 < part["rows"] < full["rows"] == len(obs)


def test_pruning_filter_matches_pandas(isolated_dirs):
    data, _ = isolated_dirs
    obs, _ = make_staging(data)
    rows = bf.bench_pruning(data / "staging" / "observations", 1, source="wqp", year=2017)
    expected = int(((obs["source_code"] == "wqp") & (obs["year"] == 2017)).sum())
    assert rows[1]["rows"] == expected and rows[1]["filter"] == "source_code=wqp AND year=2017"
