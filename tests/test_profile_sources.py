"""DOC-2 raw profiler: synthetic raw batches written with the real manifest writer."""
import json

from src.analysis import profile_sources as ps
from src.utils.manifest import count_csv_rows, file_entry, write_manifest
from src.utils.paths import raw_batch_dir


def _batch(source, files: dict[str, str], status="success"):
    d = raw_batch_dir(source, f"{source}_test")
    entries = []
    for name, text in files.items():
        p = d / name
        p.write_text(text, encoding="utf-8")
        rows = count_csv_rows(p) if name.endswith(".csv") else None
        entries.append(file_entry(p, name.rsplit(".", 1)[-1], rows))
    write_manifest(d, source_code=source, batch_id=f"{source}_test", params={}, requests_log=[],
                   files=entries, status=status)
    return d


OWQ = ("# attribution line 1\n# attribution line 2\n"
       "date,indicator,value,unit,latitude,longitude,source,region,water_body\n"
       "2016-05-01,E. coli,120,#/100ml,40.1,-3.2,Eionet,Europe,river\n"
       "2016-05-01,E. coli,120,#/100ml,40.1,-3.2,Eionet,Europe,river\n"          # exact duplicate
       "2017-06-02,Enterococci,<10,CFU/100mL,41.0,-3.0,Eionet,Europe,ocean\n"
       "bad-date,E. coli,,CFU/100mL,41.0,-3.0,Eionet,Europe,other\n")


def test_owq_profile_keeps_hash_units_and_counts_issues(isolated_dirs):
    _batch("owq_eionet", {"owq_eionet_2016_chunk1.csv": OWQ, "sampled_sites.csv": "a,b\n1,2\n"})
    p = ps.profile_source("owq_eionet")
    assert p["status"] == "profiled" and p["files"] == 1               # helper file skipped via data_files
    assert p["rows"] == 4 and p["columns"] == 9
    assert p["vocabulary"]["unit"]["#/100ml"] == 2                       # '#' inside a value is not a comment
    assert p["exact_duplicate_rows"] == 1 and p["duplicate_site_date_indicator"] == 1
    assert p["distinct_sites"] == 2 and p["unparseable_dates"] == 1
    assert p["date_min"] == "2016-05-01" and p["rows_per_year"] == {"2016": 2, "2017": 1}
    assert p["value"]["non_numeric_texts"] == {"<10": 1} and p["blank_share"]["value"] == 0.25
    assert p["region_indicator"] == {"Europe": {"E. coli": 3, "Enterococci": 1}}


def test_open_meteo_and_missing_sources(isolated_dirs):
    cell = {"daily": {"time": ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"],
                      "precipitation_sum": [0.0, 12.5, None, 0.0], "temperature_2m_mean": [5, 6, 7, None]},
            "daily_units": {}}
    _batch("open_meteo", {"cell_a.json": json.dumps(cell), "grid_cells.csv": "cell_id\na\n"})
    p = ps.profile_source("open_meteo")
    assert p["cells"] == 1 and p["cell_days"] == 4 and p["precipitation_missing_share"] == 0.25
    assert p["dry_day_share"] == 0.5 and p["max_precipitation_mm"] == 12.5
    assert ps.profile_source("natural_earth")["status"] == "no successful batch"


def test_partial_batch_is_not_profiled(isolated_dirs):
    _batch("owq_gemstat", {"owq_gemstat_2016_chunk1.csv": OWQ}, status="partial")
    assert ps.profile_source("owq_gemstat")["status"] == "no successful batch"


def test_run_writes_json_and_summary(isolated_dirs, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    _batch("owq_eionet", {"owq_eionet_2016_chunk1.csv": OWQ})
    summary = ps.run()
    text = summary.read_text(encoding="utf-8")
    assert "| `owq_eionet` | `owq_eionet_test` | 4 | 2 | 2016-05-01 to 2017-06-02 |" in text
    assert "| `wqp_results` | no successful batch |" in text
    assert "  - Europe: E. coli 3, Enterococci 1" in text
    assert (tmp_path / "out" / "profiling" / "owq_eionet.json").exists()