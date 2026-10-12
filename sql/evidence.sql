-- Final-run evidence: row counts, load runs and validation summary, straight from the warehouse.
-- One command, so every number in the evidence comes from the same database state:
--   docker compose exec -T postgres psql -U wq_user -d water_quality < sql/evidence.sql
-- PowerShell (UTF-8 file):
--   Get-Content -Raw sql/evidence.sql | docker compose exec -T postgres psql -U wq_user -d water_quality | Out-File -FilePath docs/evidence/final_run_evidence.txt -Encoding utf8

\echo '== 1. Row count per table'
SELECT 'dim_source' AS table_name, COUNT(*) AS row_count FROM dim_source
UNION ALL SELECT 'dim_indicator',       COUNT(*) FROM dim_indicator
UNION ALL SELECT 'dim_region',          COUNT(*) FROM dim_region
UNION ALL SELECT 'dim_grid_cell',       COUNT(*) FROM dim_grid_cell
UNION ALL SELECT 'dim_site',            COUNT(*) FROM dim_site
UNION ALL SELECT 'fact_weather_daily',  COUNT(*) FROM fact_weather_daily
UNION ALL SELECT 'fact_observation',    COUNT(*) FROM fact_observation
UNION ALL SELECT 'mart_site_hotspot',   COUNT(*) FROM mart_site_hotspot
UNION ALL SELECT 'mart_region_priority', COUNT(*) FROM mart_region_priority
UNION ALL SELECT 'etl_batch_log',       COUNT(*) FROM etl_batch_log
UNION ALL SELECT 'dq_results',          COUNT(*) FROM dq_results
ORDER BY table_name;

\echo ''
\echo '== 2. Observations per source (matches reconciliation: staging rows = fact_observation rows)'
SELECT s.source_code                      AS source,
       COUNT(*)                           AS observations,
       COUNT(DISTINCT f.site_key)         AS sites,
       MIN(f.sample_date)                 AS first_date,
       MAX(f.sample_date)                 AS last_date,
       ROUND(100.0 * COUNT(f.rain_48h_mm) / COUNT(*), 1) AS pct_with_rain
FROM fact_observation f
JOIN dim_site s ON s.site_key = f.site_key
GROUP BY s.source_code
ORDER BY s.source_code;

\echo ''
\echo '== 3. Sampled sites per stratum and realm'
SELECT stratum, realm, COUNT(*) AS sites
FROM dim_site
GROUP BY stratum, realm
ORDER BY stratum, realm;

\echo ''
\echo '== 4. Load runs (one row per run; a rerun of the same data shows the same rows_out)'
SELECT dag_run_id,
       status,
       COUNT(*)                       AS tables,
       SUM(rows_out)                  AS rows_out,
       MIN(started_at)::timestamp(0)  AS started_at,
       MAX(finished_at)::timestamp(0) AS finished_at
FROM etl_batch_log
WHERE stage = 'load'
GROUP BY dag_run_id, status
ORDER BY MIN(started_at);

\echo ''
\echo '== 5. Validation summary, latest run per stage'
WITH latest AS (
    SELECT DISTINCT ON (stage) stage, run_id
    FROM dq_results
    ORDER BY stage, checked_at DESC
)
SELECT d.stage,
       d.run_id,
       COUNT(*)                                          AS checks,
       COUNT(*) FILTER (WHERE d.status = 'pass')         AS passed,
       COUNT(*) FILTER (WHERE d.status = 'fail' AND d.severity = 'critical') AS failed_critical,
       COUNT(*) FILTER (WHERE d.status = 'fail' AND d.severity = 'warning')  AS failed_warning
FROM dq_results d
JOIN latest l ON l.stage = d.stage AND l.run_id = d.run_id
GROUP BY d.stage, d.run_id
ORDER BY CASE d.stage WHEN 'raw' THEN 1 WHEN 'staging' THEN 2 ELSE 3 END;

\echo ''
\echo '== 6. Every check in the latest run per stage (failures are listed first)'
WITH latest AS (
    SELECT DISTINCT ON (stage) stage, run_id
    FROM dq_results
    ORDER BY stage, checked_at DESC
)
SELECT d.stage, d.check_name, d.source_code, d.severity, d.status, d.failed_count
FROM dq_results d
JOIN latest l ON l.stage = d.stage AND l.run_id = d.run_id
ORDER BY (d.status = 'pass'), CASE d.stage WHEN 'raw' THEN 1 WHEN 'staging' THEN 2 ELSE 3 END, d.check_name, d.source_code;