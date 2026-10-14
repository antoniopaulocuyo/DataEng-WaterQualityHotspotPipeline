"""REPRO-1 (DE2): check that a pipeline run reproduces our expected results.

  python -m src.analysis.verify_run --write-expected   # write docs/expected_outputs.json from Postgres
  python -m src.analysis.verify_run                    # compare Postgres with it; exit code 1 on any FAIL

Compared items:
  - row count per warehouse table, except etl_batch_log and dq_results (logs that grow on every run)
  - persistent hotspots per stratum x realm
  - top-10 ranked regions: region_code, rank, priority score rounded to 6 decimals
  - pipeline mode
The JSON has sorted keys and no timestamp, so writing it twice from the same database
gives an identical file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.load.db import get_engine
from src.utils import config as cfg

EXPECTED_PATH = cfg.PROJECT_ROOT / "docs" / "expected_outputs.json"
RESULT_TABLES = [  # tables whose size is part of the result (the two log tables are left out)
    "dim_source", "dim_indicator", "dim_region", "dim_grid_cell", "dim_site",
    "fact_weather_daily", "fact_observation", "mart_site_hotspot", "mart_region_priority",
]
SCORE_DECIMALS = 6
TOP_N = 10

HOTSPOTS_SQL = """
SELECT COALESCE(s.stratum, 'none') AS stratum, COALESCE(h.realm, 'none') AS realm,
       SUM(CASE WHEN h.is_persistent_hotspot THEN 1 ELSE 0 END) AS hotspots
FROM mart_site_hotspot h
JOIN dim_site s ON s.site_key = h.site_key
GROUP BY 1, 2
ORDER BY 1, 2
"""

TOP_REGIONS_SQL = """
SELECT region_code, priority_rank, priority_score
FROM mart_region_priority
WHERE status = 'ranked'
ORDER BY priority_rank, region_code
LIMIT :n
"""


def pipeline_mode() -> str:
    """Antonio's config.pipeline_mode() once it is merged; until then the same env var and default."""
    fn = getattr(cfg, "pipeline_mode", None)
    return fn() if fn else cfg.get_env("PIPELINE_MODE", default="snapshot")


def collect(engine: Engine) -> dict:
    """The current results from Postgres, in the expected_outputs.json layout."""
    with engine.connect() as conn:
        row_counts = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                      for t in RESULT_TABLES}
        hotspots = {f"{stratum}/{realm}": int(n)
                    for stratum, realm, n in conn.execute(text(HOTSPOTS_SQL))}
        top_regions = [
            {"region_code": code, "rank": int(rank),
             "score": None if score is None else round(float(score), SCORE_DECIMALS)}
            for code, rank, score in conn.execute(text(TOP_REGIONS_SQL), {"n": TOP_N})
        ]
    return {"pipeline_mode": pipeline_mode(), "row_counts": row_counts,
            "hotspots_by_stratum_realm": hotspots, "top_regions": top_regions}


def compare(expected: dict, actual: dict) -> list[tuple[str, bool, object, object]]:
    """(item, passed, expected value, actual value) for every item on either side.

    Keys missing on one side count as a FAIL, so an extra or missing table, stratum or
    top region is caught, not only a different number.
    """
    results = [("pipeline_mode", expected.get("pipeline_mode") == actual.get("pipeline_mode"),
                expected.get("pipeline_mode"), actual.get("pipeline_mode"))]
    for section in ("row_counts", "hotspots_by_stratum_realm"):
        exp, act = expected.get(section, {}), actual.get(section, {})
        for key in sorted(set(exp) | set(act)):
            results.append((f"{section}:{key}", exp.get(key) == act.get(key), exp.get(key), act.get(key)))
    exp_top, act_top = expected.get("top_regions", []), actual.get("top_regions", [])
    for i in range(max(len(exp_top), len(act_top))):
        e = exp_top[i] if i < len(exp_top) else None
        a = act_top[i] if i < len(act_top) else None
        results.append((f"top_regions:{i + 1}", e == a, e, a))
    return results


def write_expected(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REPRO-1: verify a run against docs/expected_outputs.json")
    parser.add_argument("--write-expected", action="store_true",
                        help="write the expected file from the current database instead of comparing")
    parser.add_argument("--expected", type=Path, default=EXPECTED_PATH, help="expected file to read or write")
    args = parser.parse_args(argv)

    actual = collect(get_engine())
    if args.write_expected:
        write_expected(actual, args.expected)
        print(f"Wrote {args.expected} ({len(actual['row_counts'])} tables, "
              f"{len(actual['hotspots_by_stratum_realm'])} stratum x realm groups, "
              f"{len(actual['top_regions'])} top regions, mode={actual['pipeline_mode']})")
        return 0

    if not args.expected.exists():
        print(f"FAIL  {args.expected} not found: run with --write-expected after the reference run")
        return 1
    results = compare(json.loads(args.expected.read_text(encoding="utf-8")), actual)
    for name, ok, exp, act in results:
        print(f"PASS  {name} = {act!r}" if ok else f"FAIL  {name}: expected {exp!r}, got {act!r}")
    failed = sum(1 for _, ok, _, _ in results if not ok)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())