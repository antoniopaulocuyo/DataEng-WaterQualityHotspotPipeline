"""BENCH-1: CSV vs JSON vs Parquet, and partition pruning on the staging dataset.

Datasets (real pipeline data, read-only):
    staging_observations   data/staging/observations (hive: source_code=/year=), typed
    owq_raw_observations   every raw OWQ chunk CSV of the latest successful GEMStat + Eionet batches,
                           with the types staging would give them (dates, floats). Only if --skip-raw is not set.

Format test: each dataset is written and read back in CSV, JSON Lines and Parquet (snappy), `repeats` times;
the median time is reported with file size, a 2-column read, and whether column types survive the round trip.
Pruning test: the staging dataset is read whole, then with a partition filter (one source, one year) through
pyarrow.dataset, which opens only the matching source_code=/year= folders.

Writes outputs/benchmark/{format_benchmark,partition_pruning}.csv and docs/format_benchmark.md.
Timings depend on the machine; run it in the pipeline container so results are comparable:
    python -m src.analysis.benchmark_formats [--repeats 3] [--skip-raw]   (~2-4 minutes with raw)
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from src.analysis.profile_sources import _leading_comments, data_files
from src.transform.sites import latest_success_batch
from src.utils.config import PROJECT_ROOT, load_yaml
from src.utils.log import get_logger
from src.utils.paths import staging_dir
from src.validation.core import outputs_dir

log = get_logger("analysis", "benchmark", None)
FORMATS = ["csv", "json", "parquet"]
OWQ_SOURCES = ["owq_gemstat", "owq_eionet"]


# ---------------------------------------------------------------- inputs
def load_staging() -> pd.DataFrame:
    root = staging_dir() / "observations"
    df = ds.dataset(root, format="parquet", partitioning="hive").to_table().to_pandas()
    df["source_code"] = df["source_code"].astype(str)          # hive partition column comes back as dictionary
    return df


def load_owq_raw() -> pd.DataFrame | None:
    frames = []
    for src in OWQ_SOURCES:
        try:
            batch = latest_success_batch(src)
        except FileNotFoundError:
            continue
        schema = load_yaml(f"schemas/{src}")
        for p in data_files(batch, schema):
            frames.append(pd.read_csv(p, skiprows=_leading_comments(p, "#"), dtype=str, keep_default_na=False))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("value", "latitude", "longitude"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------- format test
def _write(df: pd.DataFrame, fmt: str, path: Path) -> None:
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", lines=True, date_format="iso")
    else:
        df.to_parquet(path, index=False)


def _read(fmt: str, path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path, usecols=columns)
    if fmt == "json":
        # chunked: same parsing work, but peak memory stays well under Docker's 4 GB on ~1.4M rows
        df = pd.concat(pd.read_json(path, lines=True, chunksize=200_000), ignore_index=True)
        return df[columns] if columns else df
    return pd.read_parquet(path, columns=columns)


def _median_seconds(fn, repeats: int) -> float:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def _kind(s: pd.Series) -> str:
    """dtype, or for object columns the Python type of the values (a date column read back as text is a change)."""
    if s.dtype != object:
        return str(s.dtype)
    v = s.dropna()
    return "str" if v.empty else type(v.iloc[0]).__name__


def types_preserved(original: pd.DataFrame, back: pd.DataFrame) -> tuple[bool, list[str]]:
    """Columns whose type changed after the round trip (all string-like types count as the same)."""
    text = {"str", "string", "object", "category"}
    changed = []
    for c in original.columns:
        a, b = _kind(original[c]), (_kind(back[c]) if c in back else "missing")
        if a != b and not {a, b} <= text:
            changed.append(f"{c}: {a}→{b}")
    return not changed, changed


def bench_formats(name: str, df: pd.DataFrame, work: Path, repeats: int, two_cols: list[str]) -> list[dict]:
    rows = []
    for fmt in FORMATS:
        path = work / f"{name}.{'jsonl' if fmt == 'json' else fmt}"
        write_s = _median_seconds(lambda: _write(df, fmt, path), repeats)
        read_s = _median_seconds(lambda: _read(fmt, path), repeats)
        cols_s = _median_seconds(lambda: _read(fmt, path, two_cols), repeats)
        back = _read(fmt, path)
        kept, changed = types_preserved(df, back)
        rows.append({"dataset": name, "format": fmt, "rows": len(df), "columns": len(df.columns),
                     "size_mb": round(path.stat().st_size / 1e6, 3), "write_s": round(write_s, 4),
                     "read_all_s": round(read_s, 4), "read_2_cols_s": round(cols_s, 4),
                     "rows_round_trip_ok": len(back) == len(df), "types_preserved": kept,
                     "type_changes": "; ".join(changed[:6]) + (" …" if len(changed) > 6 else "")})
        log.info(f"{name} {fmt}: {rows[-1]['size_mb']} MB, write {write_s:.3f}s, read {read_s:.3f}s")
    return rows


# ---------------------------------------------------------------- pruning test
def bench_pruning(root: Path, repeats: int, source: str | None = None, year: int | None = None) -> list[dict]:
    dataset = ds.dataset(root, format="parquet", partitioning="hive")
    files_total = len(dataset.files)
    if source is None or year is None:                          # default: the newest year of the largest source
        t = dataset.to_table(columns=["source_code", "year"]).to_pandas()
        source = t["source_code"].astype(str).value_counts().idxmax()
        year = int(t.loc[t["source_code"].astype(str) == source, "year"].max())
    flt = (ds.field("source_code") == source) & (ds.field("year") == year)
    full_s = _median_seconds(lambda: dataset.to_table(), repeats)
    pruned_s = _median_seconds(lambda: dataset.to_table(filter=flt), repeats)
    files_pruned = len(list(dataset.get_fragments(filter=flt)))
    full_rows, pruned_rows = dataset.count_rows(), dataset.count_rows(filter=flt)
    return [{"read": "full scan", "filter": "none", "files_opened": files_total, "rows": full_rows,
             "median_s": round(full_s, 4)},
            {"read": "partition filter", "filter": f"source_code={source} AND year={year}",
             "files_opened": files_pruned, "rows": pruned_rows, "median_s": round(pruned_s, 4)}]


# ---------------------------------------------------------------- report
def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(("yes" if v else "no") if isinstance(v, bool) else
                                     (f"{v:,}" if isinstance(v, int) else str(v)) for v in r) + " |")
    return "\n".join(out)


def interpretation(fmt: pd.DataFrame, prune: pd.DataFrame) -> list[str]:
    """Findings written from the measured tables, so the text can never disagree with the numbers."""
    ratio = lambda a, b: a / max(b, 1e-9)
    big_name = fmt.loc[fmt["rows"].idxmax(), "dataset"]
    big = fmt[fmt["dataset"] == big_name].set_index("format")
    pq, csv, js = big.loc["parquet"], big.loc["csv"], big.loc["json"]
    kept = "; ".join(f"{d}: " + (", ".join(g.loc[g["types_preserved"], "format"]) or "none")
                     for d, g in fmt.groupby("dataset", sort=False))
    full, part = prune.iloc[0], prune.iloc[1]
    return [
        f"- **Size** (`{big_name}`, {int(pq['rows']):,} rows): Parquet is {pq['size_mb']} MB, CSV {csv['size_mb']} MB "
        f"({ratio(csv['size_mb'], pq['size_mb']):.0f}× larger) and JSON Lines {js['size_mb']} MB "
        f"({ratio(js['size_mb'], pq['size_mb']):.0f}× larger). Parquet is columnar and compressed, so repeated values "
        "(source, indicator, unit) cost little; JSON repeats every key on every row.",
        f"- **Speed:** reading the whole file takes {pq['read_all_s']} s in Parquet, {csv['read_all_s']} s in CSV "
        f"({ratio(csv['read_all_s'], pq['read_all_s']):.0f}× slower) and {js['read_all_s']} s in JSON "
        f"({ratio(js['read_all_s'], pq['read_all_s']):.0f}× slower). Reading 2 columns takes {pq['read_2_cols_s']} s from "
        f"Parquet, which reads only those columns, against {csv['read_2_cols_s']} s (CSV) and {js['read_2_cols_s']} s "
        "(JSON), which still scan or parse every row.",
        f"- **Schema:** formats that kept every column type in the round trip: {kept}. CSV and JSON are text, so readers "
        "must infer or re-cast types; JSON only looks type-safe when pandas guesses dates from a column name such as "
        "`date`. Parquet stores the schema in the file.",
        "- **Where each format is used:** CSV and JSON stay in the **raw** layer because that is how WQP, OWQ (CSV) and "
        "Open-Meteo (JSON) deliver data and raw must be source-faithful. **Staging and curated** use Parquet. CSV is also "
        "used for small hand-off files people open directly (`priority_ranking.csv`, `reconciliation.csv`) and for the "
        "bulk `COPY` into PostgreSQL.",
        f"- **Partition pruning:** `source_code` and `year` are how every downstream step slices the data. Reading "
        f"`{part['filter']}` opened {int(part['files_opened'])} of {int(full['files_opened'])} files and "
        f"{int(part['rows']):,} of {int(full['rows']):,} rows, in {part['median_s']} s against {full['median_s']} s for "
        f"the full scan ({ratio(full['median_s'], part['median_s']):.0f}× faster). The staging dataset is small, so the "
        "absolute times are milliseconds; the point is that read cost follows the slice requested, not the whole history."]


def build_report(fmt: pd.DataFrame, prune: pd.DataFrame, repeats: int, env: dict) -> str:
    lines = ["# File Format Benchmark and Partition Pruning", "",
             "*Generated by `python -m src.analysis.benchmark_formats`; do not edit by hand. "
             f"Run {env['when']} on {env['machine']} (Python {env['python']}, pandas {env['pandas']}, "
             f"pyarrow {env['pyarrow']}, {env['cpus']} CPUs). Times are the median of {repeats} runs.*", "",
             "## 1. Method", "",
             "- **Data:** the pipeline's own outputs, not synthetic data: " + ", ".join(
                 f"`{d}` ({n:,} rows)" for d, n in fmt.groupby("dataset", sort=False)["rows"].first().items())
             + ". `owq_raw_observations` is every raw OWQ row (GEMStat + Eionet) with staging's types applied.",
             "- **Formats:** CSV (`to_csv`/`read_csv`), JSON Lines (`to_json(orient='records', lines=True)`/"
             "`read_json(lines=True)`), Parquet with pyarrow and its default snappy compression.",
             "- **Measures:** file size; full write and read time; time to read only 2 columns; whether row count "
             "and column types survive the round trip.",
             "- **Pruning:** the staging dataset is partitioned as `source_code=/year=`. It is read once in full and "
             "once with a filter on both partition keys through `pyarrow.dataset`, which skips non-matching folders "
             "without opening them.", "",
             "## 2. Format comparison", "", _md(fmt), "",
             "## 3. Partition pruning (staging observations)", "", _md(prune), "",
             "## 4. Interpretation", ""] + interpretation(fmt, prune) + [""]
    return "\n".join(lines)


def run(repeats: int = 3, include_raw: bool = True, docs_dir: Path | None = None) -> Path:
    out = outputs_dir() / "benchmark"
    work = out / "files"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    stg = load_staging()
    two = ["indicator_code", "value_cfu_100ml"]
    rows = bench_formats("staging_observations", stg, work, repeats, two)
    if include_raw:
        raw = load_owq_raw()
        if raw is not None:
            rows += bench_formats("owq_raw_observations", raw, work, repeats, ["indicator", "value"])
            for p in work.glob("owq_raw_observations.*"):    # large; keep only the staging copies for inspection
                p.unlink()
    fmt = pd.DataFrame(rows)
    prune = pd.DataFrame(bench_pruning(staging_dir() / "observations", repeats))
    fmt.to_csv(out / "format_benchmark.csv", index=False)
    prune.to_csv(out / "partition_pruning.csv", index=False)
    env = {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "machine": platform.machine(),
           "python": platform.python_version(), "pandas": pd.__version__, "pyarrow": pa.__version__,
           "cpus": os.cpu_count()}
    docs = Path(docs_dir) if docs_dir else PROJECT_ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    report = docs / "format_benchmark.md"
    report.write_text(build_report(fmt, prune, repeats, env), encoding="utf-8")
    log.info(f"report {report}; tables in {out}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="BENCH-1: CSV/JSON/Parquet benchmark and partition pruning")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--skip-raw", action="store_true", help="benchmark the staging dataset only")
    args = parser.parse_args()
    print(run(args.repeats, include_raw=not args.skip_raw))


if __name__ == "__main__":
    main()
