"""EDA report: runs on synthetic staging + curated data written with the real writers."""
from datetime import date

import numpy as np
import pandas as pd

from src.analysis import eda
from src.transform.staging import OBS_COLUMNS, OBS_DTYPES, write_partitions


def make_staging(data):
    rng = np.random.default_rng(0)
    rows = []
    for i in range(200):
        src = "wqp" if i % 2 else "owq_eionet"
        site = f"{src}:S{i % 6}"
        ind = "e_coli" if i % 3 else "enterococci"
        d = date(2016 + i % 6, 1 + i % 12, 1 + i % 27)
        v = float(rng.lognormal(4, 1.5))
        rows.append({"obs_key": f"{src}:{i}", "source_code": src, "source_record_id": str(i), "site_key": site,
                     "source_site_id": f"S{i % 6}", "activity_id": None, "activity_type": None, "indicator_code": ind,
                     "sample_date": d, "year": d.year, "value_cfu_100ml": v, "original_value": str(v),
                     "original_unit": "CFU/100mL", "is_censored": i % 10 == 0, "censor_direction": "<" if i % 10 == 0 else None,
                     "detection_limit": None, "result_status": None, "raw_batch_id": "b", "raw_file": "f"})
    obs = pd.DataFrame(rows)[OBS_COLUMNS].astype(OBS_DTYPES)
    write_partitions(obs, data / "staging" / "observations",
                     {"batch_id": "staging_t", "row_counts": {"wqp": {"rows_in": 120}, "owq_eionet": {"rows_in": 150}},
                      "unmapped_units": {"wqp": {"MPN": 7}}, "params": {"inputs": {}}})
    sites = pd.DataFrame([{"site_key": f"{s}:S{j}", "source_code": s, "stratum": "us" if s == "wqp" else "europe",
                           "realm": "freshwater" if j % 2 else "marine", "is_eligible": True, "is_sampled": True}
                          for s in ("wqp", "owq_eionet") for j in range(6)])
    (data / "staging" / "sites").mkdir(parents=True)
    sites.to_parquet(data / "staging" / "sites" / "sites.parquet", index=False)
    pd.DataFrame([{"stage": "observations", "source_code": "wqp", "reason": "unit_unmapped", "row_count": 7,
                   "batch_id": "staging_t"}]).to_parquet(data / "staging" / "_drop_log.parquet", index=False)
    return obs, sites


def test_report_tables_and_figures(isolated_dirs, tmp_path, monkeypatch):
    data, _ = isolated_dirs
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    make_staging(data)
    report = eda.run(docs_dir=tmp_path / "docs")
    text = report.read_text(encoding="utf-8")
    for heading in ("## 3. Volume by layer", "## 6. Values", "## 8. Data quality"):
        assert heading in text
    assert "200 harmonized observations" in text
    assert len(list((tmp_path / "docs" / "figures").glob("eda_*.png"))) == 4        # no curated data -> no hotspot figure
    assert (tmp_path / "out" / "eda" / "values.csv").exists()
    assert "## 10." not in text                                                   # hotspots only when marts exist


def test_with_curated_marts(isolated_dirs, tmp_path, monkeypatch):
    data, _ = isolated_dirs
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    obs, sites = make_staging(data)
    cur = data / "curated"
    cur.mkdir()
    pd.DataFrame({"site_key": sites["site_key"], "stratum": sites["stratum"]}).to_parquet(cur / "dim_site.parquet")
    pd.DataFrame({"site_key": sites["site_key"], "realm": sites["realm"], "is_persistent_hotspot": [True, False] * 6,
                  "median_ratio_to_threshold": 0.5, "exceedance_rate": 0.2}).to_parquet(cur / "mart_site_hotspot.parquet")
    fo = obs[["obs_key"]].assign(rain_48h_mm=np.where(np.arange(len(obs)) % 2, 5.0, np.nan),
                                 is_wet=pd.array([True, None] * (len(obs) // 2), dtype="boolean"))
    fo.to_parquet(cur / "fact_observation.parquet")
    text = eda.run(docs_dir=tmp_path / "docs").read_text(encoding="utf-8")
    assert "## 9. Weather coverage" in text and "## 10. Persistent hotspots" in text
    hs = pd.read_csv(tmp_path / "out" / "eda" / "hotspots.csv", encoding="utf-8-sig")
    assert set(hs["stratum"]) == {"us", "europe"} and hs["hotspots"].sum() == 6 and hs["sites"].sum() == 12


def test_values_table_threshold_share():
    obs = pd.DataFrame({"source_code": "wqp", "indicator_code": "e_coli",
                        "value_cfu_100ml": [100.0, 500.0, 1000.0, 50.0], "is_censored": False})
    t = eda.table_value_stats(obs, {"e_coli": 410.0})
    assert t.loc[0, "pct_above_threshold"] == 50.0 and t.loc[0, "median"] == 300.0


# ---------------------------------------------------------------- DOC-2 revision: coverage, countries, wet vs dry
def test_raw_batches_listed_once():
    raw = pd.DataFrame({"source": ["owq_eionet", "owq_eionet", "wqp_results"], "batch_id": ["a", "a", "b"],
                        "status": "success", "files": 1, "rows": 5, "size_mb": 1.0})
    t = eda.table_raw(raw, {"params": {"inputs": {"owq_eionet": "a"}}})
    assert list(t["source"]) == ["owq_eionet", "wqp_results"] and list(t["used_by_staging"]) == [True, False]


def _sites():
    rows = [("us", "freshwater", "US", True, True)] * 3 + [("europe", "marine", "ES", True, True)] * 2 \
        + [("europe", "marine", "DE", True, True)] + [("gemstat_asia", "freshwater", "IN", False, False)] * 2
    return pd.DataFrame([{"site_key": f"s{i}", "stratum": s, "realm": r, "country_iso": c, "is_eligible": e,
                          "is_sampled": m} for i, (s, r, c, e, m) in enumerate(rows)])


SAMPLING = {"realms": {"freshwater": {}, "marine": {}},
            "strata": {"us": {}, "europe": {}, "gemstat_africa": {}, "gemstat_asia": {}}}


def test_sites_table_lists_empty_strata():
    t = eda.table_sites(_sites(), SAMPLING).set_index(["stratum", "realm"])
    assert t.loc[("gemstat_africa", "freshwater"), "status"] == "no sites found"        # absent from the data
    assert t.loc[("gemstat_asia", "freshwater"), "status"] == "no eligible sites"       # present but not eligible
    assert t.loc[("gemstat_asia", "freshwater"), "candidates"] == 2 and t.loc[("us", "freshwater"), "sampled"] == 3
    assert len(t) == 8                                                                   # 4 strata x 2 realms
    line = eda.coverage_line(eda.table_sites(_sites(), SAMPLING).reset_index(drop=True))
    assert "exist in us, europe" in line and "No sampled sites in gemstat_africa, gemstat_asia" in line
    assert "not global comparisons" in line


def test_countries_table_shows_concentration():
    t = eda.table_countries(_sites()).set_index("stratum")
    assert t.loc["europe", "sampled_sites"] == 3 and t.loc["europe", "countries"] == 2
    assert t.loc["europe", "top_countries"] == "ES 2, DE 1" and round(t.loc["europe", "top_country_share"], 2) == 0.67
    assert "gemstat_asia" not in t.index                                                 # not sampled
    assert eda.table_countries(_sites().drop(columns="country_iso")) is None


def test_wet_dry_table_known_answer():
    cur = {"dim_site": pd.DataFrame({"site_key": list("abcd"), "stratum": ["us", "us", "us", "europe"]}),
           "mart_site_hotspot": pd.DataFrame({
               "site_key": list("abcd"), "realm": ["freshwater"] * 4,
               "wet_exceedance_rate": [0.4, 0.2, np.nan, 0.1], "dry_exceedance_rate": [0.2, 0.3, 0.1, 0.0]})}
    t = eda.table_wet_dry(cur).set_index("stratum")
    assert t.loc["us", "sites"] == 3 and t.loc["us", "sites_with_wet_and_dry"] == 2        # c has no wet days
    assert t.loc["us", "share_wet_higher"] == 0.5 and round(t.loc["us", "median_wet_rate"], 2) == 0.3
    assert t.loc["all", "sites_with_wet_and_dry"] == 3 and round(t.loc["all", "share_wet_higher"], 2) == 0.67
    assert eda.table_wet_dry({"dim_site": cur["dim_site"], "mart_site_hotspot": cur["mart_site_hotspot"].drop(
        columns="wet_exceedance_rate")}) is None


def test_weather_and_year_notes():
    full = pd.DataFrame({"pct_with_rain": [100.0, 99.0]})
    assert "at least 99%" in eda.weather_note(full) and "provisional" not in eda.weather_note(full)
    assert "provisional" in eda.weather_note(pd.DataFrame({"pct_with_rain": [12.0, 100.0]}))
    by_year = pd.DataFrame({"year": [2019, 2020, 2021], "wqp": [5, 6, 7], "owq": [4, 0, 0], "total": [9, 6, 7]})
    assert eda.last_year_line(by_year).startswith("Last year with data per source: wqp 2021, owq 2019")


def test_report_has_new_sections_and_no_stale_rain_text(isolated_dirs, tmp_path, monkeypatch):
    data, _ = isolated_dirs
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    obs, sites = make_staging(data)
    cur = data / "curated"
    cur.mkdir()
    pd.DataFrame({"site_key": sites["site_key"], "stratum": sites["stratum"]}).to_parquet(cur / "dim_site.parquet")
    pd.DataFrame({"site_key": sites["site_key"], "realm": sites["realm"], "is_persistent_hotspot": [True, False] * 6,
                  "median_ratio_to_threshold": 0.5, "exceedance_rate": 0.2, "wet_exceedance_rate": 0.3,
                  "dry_exceedance_rate": 0.1}).to_parquet(cur / "mart_site_hotspot.parquet")
    pd.DataFrame({"obs_key": obs["obs_key"], "rain_48h_mm": 5.0,
                  "is_wet": pd.array([True, False] * (len(obs) // 2), dtype="boolean")}).to_parquet(
        cur / "fact_observation.parquet")
    text = eda.run(docs_dir=tmp_path / "docs").read_text(encoding="utf-8")
    assert "## 11. Wet vs dry exceedance" in text and "**Coverage:**" in text and "Last year with data" in text
    assert "no sites found" in text                                  # Africa/Asia strata from config/sampling.yaml
    assert "Rain-based results are only meaningful once" not in text and "full weather pull" in text