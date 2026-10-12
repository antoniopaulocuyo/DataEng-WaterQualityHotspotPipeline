"""DOC-2: profile every source on the RAW layer, before any cleaning.

For each source it reads the latest successful raw batch, only the files named by `data_files` in
config/schemas/{source_code}.yaml, and writes:
    outputs/profiling/{source_code}.json      full profile
    outputs/profiling/profiling_summary.md    summary table + per-source details (copy to docs/evidence/)

Read-only, no network calls. A source without a successful batch is reported, not fatal.
Run:  python -m src.analysis.profile_sources
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.transform.sites import latest_success_batch
from src.utils.config import load_yaml
from src.utils.log import get_logger
from src.utils.manifest import read_manifest
from src.validation.core import outputs_dir

log = get_logger("analysis", "profile", None)
SOURCES = ["owq_gemstat", "owq_eionet", "wqp_summary", "wqp_results", "open_meteo", "natural_earth"]
TOP_N = 8

# Which raw columns play which role. Sites are coordinates for OWQ (it has no site ID column).
TABULAR = {
    "owq_gemstat": {"site": ["latitude", "longitude"], "date": "date", "indicator": "indicator",
                    "value": "value", "vocab": ["indicator", "unit", "region", "water_body", "source"]},
    "owq_eionet": {"site": ["latitude", "longitude"], "date": "date", "indicator": "indicator",
                   "value": "value", "vocab": ["indicator", "unit", "region", "water_body", "source"]},
    "wqp_results": {"site": ["MonitoringLocationIdentifier"], "date": "ActivityStartDate",
                    "indicator": "CharacteristicName", "value": "ResultMeasureValue",
                    "vocab": ["CharacteristicName", "ResultMeasure/MeasureUnitCode", "ResultDetectionConditionText",
                              "ActivityTypeCode", "ActivityMediaName", "ResultStatusIdentifier",
                              "ResultSampleFractionText"]},
    "wqp_summary": {"site": ["MonitoringLocationIdentifier"], "year": "YearSummarized",
                    "indicator": "CharacteristicName", "value": "ResultCount",
                    "vocab": ["CharacteristicName", "MonitoringLocationTypeName"]},
}


# ---------------------------------------------------------------- reading
def _schema(source: str) -> dict:
    return load_yaml(f"schemas/{source}")


def data_files(batch_dir: Path, schema: dict) -> list[Path]:
    names = [f["name"] for f in (read_manifest(batch_dir) or {}).get("files", [])]
    pattern = schema.get("data_files")
    return [batch_dir / n for n in names if not pattern or fnmatch.fnmatch(n, pattern)]


def _leading_comments(path: Path, prefix: str) -> int:
    """Count leading comment lines only. pandas' `comment=` would also cut values such as '#/100ml'."""
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            if not line.startswith(prefix):
                break
            n += 1
    return n


def read_csvs(files: list[Path], schema: dict) -> pd.DataFrame:
    prefix = schema.get("comment_prefix")
    frames = [pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig",
                          skiprows=_leading_comments(p, prefix) if prefix else 0) for p in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------- measures
def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().eq("")


def _top(s: pd.Series, n: int = TOP_N) -> dict:
    return {str(k): int(v) for k, v in s[~_blank(s)].value_counts().head(n).items()}


def profile_tabular(df: pd.DataFrame, spec: dict, required: list[str]) -> dict:
    out: dict = {"rows": len(df), "columns": len(df.columns), "column_names": list(df.columns)}
    out["blank_share"] = {c: round(float(_blank(df[c]).mean()), 4) for c in df.columns}
    out["distinct"] = {c: int(df[c].nunique()) for c in df.columns}
    key = [c for c in required if c in df.columns]
    out["blank_share_key_columns"] = round(float(np.mean([out["blank_share"][c] for c in key])), 4) if key else None
    out["exact_duplicate_rows"] = int(df.duplicated().sum())

    site_cols = [c for c in spec["site"] if c in df.columns]
    if site_cols:
        out["distinct_sites"] = int(df[site_cols].drop_duplicates().shape[0])
    if spec.get("date") in df.columns:
        d = pd.to_datetime(df[spec["date"]], errors="coerce")
        out["unparseable_dates"] = int(d.isna().sum() - _blank(df[spec["date"]]).sum())
        out["date_min"] = str(d.min().date()) if d.notna().any() else None
        out["date_max"] = str(d.max().date()) if d.notna().any() else None
        out["rows_per_year"] = {str(int(y)): int(n) for y, n in d.dt.year.value_counts().sort_index().items()}
        dup_cols = site_cols + [spec["date"], spec["indicator"]]
        out["duplicate_site_date_indicator"] = int(df.duplicated(subset=dup_cols).sum())
    if spec.get("year") in df.columns:
        y = pd.to_numeric(df[spec["year"]], errors="coerce")
        out["year_min"], out["year_max"] = (int(y.min()), int(y.max())) if y.notna().any() else (None, None)

    raw = df[spec["value"]] if spec["value"] in df.columns else pd.Series(dtype=str)
    num = pd.to_numeric(raw.str.replace(",", "", regex=False), errors="coerce")
    present = ~_blank(raw)
    out["value"] = {
        "column": spec["value"],
        "numeric_share": round(float(num[present].notna().mean()), 4) if present.any() else None,
        "non_numeric_texts": _top(raw[present & num.isna()]),
        "negatives": int((num < 0).sum()),
        "quantiles": {q: (None if num.dropna().empty else float(num.quantile(float(q))))
                      for q in ("0.0", "0.25", "0.5", "0.75", "0.95", "1.0")},
        "most_repeated": {str(k): int(v) for k, v in num.value_counts().head(5).items()},
    }
    out["vocabulary"] = {c: _top(df[c]) for c in spec["vocab"] if c in df.columns}
    if {"region", "indicator"} <= set(df.columns):          # OWQ: which indicators each region actually reports
        ct = df[~_blank(df["region"])].groupby(["region", "indicator"]).size()
        out["region_indicator"] = {r: {i: int(n) for i, n in g.droplevel(0).sort_values(ascending=False).items()}
                                   for r, g in ct.groupby(level=0)}
    return out


def profile_open_meteo(files: list[Path]) -> dict:
    cells, cell_days, missing_p, missing_t, max_p, dry, dmin, dmax, lens = 0, 0, 0, 0, 0.0, 0, None, None, []
    for p in files:
        daily = json.loads(p.read_text(encoding="utf-8")).get("daily", {})
        t = daily.get("time", [])
        prec = pd.to_numeric(pd.Series(daily.get("precipitation_sum", []), dtype=object), errors="coerce")
        temp = pd.to_numeric(pd.Series(daily.get("temperature_2m_mean", []), dtype=object), errors="coerce")
        cells += 1
        cell_days += len(t)
        lens.append(len(t))
        missing_p += int(prec.isna().sum())
        missing_t += int(temp.isna().sum())
        dry += int((prec == 0).sum())
        if prec.notna().any():
            max_p = max(max_p, float(prec.max()))
        if t:
            dmin = min(dmin or t[0], t[0])
            dmax = max(dmax or t[-1], t[-1])
    return {"cells": cells, "cell_days": cell_days, "date_min": dmin, "date_max": dmax,
            "days_per_cell_min": min(lens) if lens else None, "days_per_cell_max": max(lens) if lens else None,
            "precipitation_missing_share": round(missing_p / cell_days, 4) if cell_days else None,
            "temperature_missing_share": round(missing_t / cell_days, 4) if cell_days else None,
            "max_precipitation_mm": max_p, "dry_day_share": round(dry / cell_days, 4) if cell_days else None}


def profile_natural_earth(files: list[Path], required: list[str]) -> dict:
    import geopandas as gpd
    g = pd.concat([gpd.read_file(p) for p in files], ignore_index=True) if files else gpd.GeoDataFrame()
    attrs = pd.DataFrame(g.drop(columns="geometry")) if len(g) else pd.DataFrame()
    key = [c for c in required if c in attrs.columns]
    return {"features": len(g), "columns": len(attrs.columns),
            "crs": str(g.crs) if len(g) else None,
            "invalid_geometries": int((~g.geometry.is_valid).sum()) if len(g) else 0,
            "iso_a2_minus_99": int((attrs.get("iso_a2", pd.Series(dtype=str)).astype(str) == "-99").sum()),
            "countries": int(attrs["adm0_a3"].nunique()) if "adm0_a3" in attrs else None,
            "blank_share_key_columns": round(float(np.mean([_blank(attrs[c].astype(str)).mean() for c in key])), 4)
            if key else None}


def profile_source(source: str) -> dict:
    try:
        batch = latest_success_batch(source)
    except FileNotFoundError as exc:
        log.warning(f"{source}: {exc}")
        return {"source_code": source, "status": "no successful batch"}
    schema = _schema(source)
    files = data_files(batch, schema)
    base = {"source_code": source, "status": "profiled", "batch_id": batch.name.removeprefix("batch_id="),
            "files": len(files), "format": schema.get("expected_format")}
    if source in TABULAR:
        base.update(profile_tabular(read_csvs(files, schema), TABULAR[source], schema.get("required_columns", [])))
    elif source == "open_meteo":
        base.update(profile_open_meteo(files))
    elif source == "natural_earth":
        base.update(profile_natural_earth(files, schema.get("required_columns", [])))
    log.info(f"{source}: profiled {base['files']} files from {base['batch_id']}")
    return base


# ---------------------------------------------------------------- report
def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def summary_row(p: dict) -> list[str]:
    if p["status"] != "profiled":
        return [f"`{p['source_code']}`", p["status"], "", "", "", ""]
    src = p["source_code"]
    if src == "open_meteo":
        rows, sites = f"{p['cell_days']:,} cell-days", f"{p['cells']:,} cells"
        dates, blank = f"{p['date_min']} to {p['date_max']}", f"precip. missing {_pct(p['precipitation_missing_share'])}"
    elif src == "natural_earth":
        rows, sites, dates = f"{p['features']:,} features", f"{p['countries']} countries", "n/a"
        blank = _pct(p["blank_share_key_columns"])
    else:
        rows, sites = f"{p['rows']:,}", f"{p.get('distinct_sites', 0):,}"
        dates = (f"{p['date_min']} to {p['date_max']}" if "date_min" in p
                 else f"{p.get('year_min')}–{p.get('year_max')} (yearly)")
        blank = _pct(p["blank_share_key_columns"])
    return [f"`{src}`", f"`{p['batch_id']}`", rows, sites, dates, blank]


def build_summary(profiles: list[dict]) -> str:
    head = ["source_code", "batch_id", "rows", "distinct sites", "date range", "blank share (key columns)"]
    lines = ["# Raw-layer profiling summary", "",
             "*Generated by `python -m src.analysis.profile_sources`; do not edit by hand.*", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(summary_row(p)) + " |" for p in profiles]
    for p in profiles:
        if p["status"] != "profiled":
            continue
        lines += ["", f"## {p['source_code']}", ""]
        if p["source_code"] in TABULAR:
            lines += [f"- {p['rows']:,} rows × {p['columns']} columns in {p['files']} files; "
                      f"{p['exact_duplicate_rows']:,} exact duplicate rows"]
            if "duplicate_site_date_indicator" in p:
                lines += [f"- {p['duplicate_site_date_indicator']:,} rows repeat a (site, date, indicator); "
                          f"{p['unparseable_dates']:,} unparseable dates"]
                lines += ["- Rows per year: " + ", ".join(f"{y}: {n:,}" for y, n in p["rows_per_year"].items())]
            v = p["value"]
            q = v["quantiles"]
            lines += [f"- `{v['column']}`: numeric share {_pct(v['numeric_share'])}, {v['negatives']} negatives; "
                      f"min {q['0.0']}, median {q['0.5']}, p95 {q['0.95']}, max {q['1.0']}",
                      f"- Most repeated values: {v['most_repeated']}",
                      f"- Non-numeric value texts: {v['non_numeric_texts'] or 'none'}"]
            hi = {c: s for c, s in p["blank_share"].items() if s > 0}
            lines += [f"- Blank share > 0: {', '.join(f'{c} {_pct(s)}' for c, s in sorted(hi.items(), key=lambda x: -x[1])) or 'none'}"]
            lines += [f"- `{c}` top values: {top}" for c, top in p["vocabulary"].items()]
            ri = p.get("region_indicator")
            if ri:
                lines += [f"- Rows by region and indicator ({min(len(ri), 15)} largest of {len(ri)} regions):"]
                for r, inds in sorted(ri.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
                    lines += [f"  - {r}: " + ", ".join(f"{i} {n:,}" for i, n in inds.items())]
        else:
            lines += [f"- {k}: {v}" for k, v in p.items() if k not in ("source_code", "status")]
    return "\n".join(lines) + "\n"


def run() -> Path:
    out = outputs_dir() / "profiling"
    out.mkdir(parents=True, exist_ok=True)
    profiles = [profile_source(s) for s in SOURCES]
    for p in profiles:
        (out / f"{p['source_code']}.json").write_text(json.dumps(p, indent=2, default=str), encoding="utf-8")
    summary = out / "profiling_summary.md"
    summary.write_text(build_summary(profiles), encoding="utf-8")
    log.info(f"profiling summary: {summary}")
    return summary


if __name__ == "__main__":
    print(run())