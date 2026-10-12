# Source Profiling Report
 
**Version:** 1.0 · **Code:** `src/analysis/profile_sources.py` · **Related:** [`source_inventory.md`](source_inventory.md), [`business_rules.md`](business_rules.md), [`data_dictionary.md`](data_dictionary.md), `config/mappings.yaml`
 
What each source contains, what its raw data actually looks like, the quality issues we found, how the pipeline handles each one, and what limitations remain. Full provider details (URLs, licences, access dates) are in [`source_inventory.md`](source_inventory.md); this page is about the data itself.
 
Every number here comes from a real run: either the ticket where it was first observed (in brackets, e.g. ING-3) or the final-run profile, [`evidence/profiling_summary.md`](evidence/profiling_summary.md) (generated 2026-10-11 from the batches named in section 2).
 
---
 
## 1. Source summary
 
| # | source_code | Provider | Access | Raw format | Role | Coverage used | Size at source |
|---|---|---|---|---|---|---|---|
| 1 | `owq_gemstat` | UNEP GEMS/Water via Open Water Quality | Scripted export (GET) | CSV with 7 `#` comment lines | Observations: Latin America stratum (Mexico in the sample); Africa and Asia strata configured but empty | Raw extract: Mexico, India, Uruguay, Canada, United States; 2015–2023 | ~400K observations (all years) |
| 2 | `owq_eionet` | EEA / Eionet bathing water via Open Water Quality | Scripted export (GET) | CSV with 7 `#` comment lines | Observations: Europe stratum; main marine source | Europe, 2015–2021 (no data after 2021) | ~2.4M observations (all years) |
| 3a | `wqp_summary` | Water Quality Portal (USGS, EPA, NWQMC) | REST API, one request per state | CSV (zip) | Per-site annual sample counts, used **only for sampling** | US | ~6.9M fecal indicator observations nationally |
| 3b | `wqp_results` | Water Quality Portal | REST API, POST, 50 sites per request | CSV (zip), 63 columns | Observations: US stratum | Sampled US sites, 2015–2025 | as 3a |
| 4 | `open_meteo` | Open-Meteo (ERA5 reanalysis) | REST API, one request per 0.25° cell | JSON | Daily rainfall and temperature | Cells of sampled sites, 2015–2025 | Global, 1940 onward |
| 5 | `natural_earth` | Natural Earth | File download | Shapefile (zip) | Admin-1 regions for aggregation | Global | 4,596 features (ING-5) |
 
The Open Water Quality compilation behind sources 1 and 2 holds about 11.1 million observations from nine public sources ([`problem_statement.md`](problem_statement.md)).
 
## 2. How profiling was done
 
Profiling runs on the **raw** layer, before any cleaning, so it shows the data as delivered. It is read-only and makes no network calls.
 
```powershell
docker compose run --rm -T pipeline python -m src.analysis.profile_sources | Out-File -FilePath outputs\doc2_profiling_log.txt -Encoding utf8
```
 
For each source it reads the latest successful raw batch, only the files named by `data_files` in `config/schemas/{source_code}.yaml`, and writes `outputs/profiling/{source_code}.json` plus `outputs/profiling/profiling_summary.md`.
 
| Measure | Tabular sources (WQP, OWQ) | Open-Meteo | Natural Earth |
|---|---|---|---|
| Volume | rows, files, columns | cells, cell-days | features |
| Completeness | blank share per column | missing precipitation / temperature share | features with `iso_a2 = -99` |
| Coverage | distinct sites, date range, rows per year | days per cell (min / max) | countries |
| Vocabulary | top values of indicator, unit, detection condition, activity type, media, status, water body, region | n/a | CRS, invalid geometries |
| Values | numeric share, non-numeric texts, negatives, quantiles, most repeated values | max precipitation, dry-day share | n/a |
| Uniqueness | duplicate (site, date, indicator) rows | n/a | n/a |
 
Copy `outputs/profiling/profiling_summary.md` to `docs/evidence/profiling_summary.md` to commit it (`outputs/` is git-ignored). The committed copy is from the final run.
 
### Profiling results (final run)
 
| source_code | batch_id | rows | distinct sites | date range | blank share (key columns) |
|---|---|---|---|---|---|
| `owq_gemstat` | `owq_gemstat_cbe19092b675` | 263,711 | 5,691 | 2015-01-01 to 2023-08-02 | 0.0% |
| `owq_eionet` | `owq_eionet_e86ef04d7716` (ING-1) | 1,085,694 | 27,390 | 2015-01-02 to 2021-12-21 | 0.0% |
| `wqp_summary` | `wqp_summary_9fe8e48f2a31` | 540,786 | 130,918 | n/a (yearly; raw year values 1 to 2206, see 3.3) | 0.0% |
| `wqp_results` | `wqp_results_8c80b98f221b` | 13,240 | 120 | 2015-01-05 to 2025-12-29 | 17.3% |
| `open_meteo` | `open_meteo_1265e632620d` | 1,028,608 cell-days | 256 cells | 2015-01-01 to 2025-12-31 | 0.0% (precipitation and temperature) |
| `natural_earth` | `natural_earth_e47c2a7cb821` | 4,596 features | n/a | n/a | 0.0% |

Blank share is the mean over the columns listed as required in `config/schemas/{source_code}.yaml`; per-column shares are in the evidence file. Row counts here are data files only. The raw-batch table in [`eda_report.md`](eda_report.md) also counts the helper files the pipeline writes into a batch (`sampled_sites.csv`, `grid_cells.csv`), so its totals are slightly higher for `wqp_summary` and `open_meteo`.

## 3. Findings per source
 
### 3.1 GEMStat (`owq_gemstat`)
 
| Finding | Evidence | Handling |
|---|---|---|
| Responses capped at 100,000 rows | `X-Row-Count` / `X-Row-Capped` headers (ING-2 spike) | Extractor chunks by year, then splits by `loc_type` when a chunk is capped |
| 7 `#` attribution lines before the header | STG-1 | Readers skip comment lines (`comment_prefix: "#"` in the schema file) |
| No site ID or record ID column; 9 columns only (`date`, `indicator`, `value`, `unit`, `latitude`, `longitude`, `source`, `region`, `water_body`) | ING-1 | Site ID = coordinates rounded to 5 decimals; record ID = SHA-1 of site, date, indicator (`mappings.yaml › record_id`) |
| Already harmonized by OWQ: MPN treated as CFU, censored values pre-filled at half the limit, cross-source duplicates removed at ~1 km | [`source_inventory.md`](source_inventory.md) | Accepted; the same censoring rule is applied to WQP so all sources match |
| Values cluster at **24,196** and **2,419,600** MPN/100 mL (lab reporting maximums, "at least this much") | README §15 | Exceedance and hotspot flags unaffected; severity understated for Latin America. In the sampled data 21.9% of GEMStat *E. coli* values (34.2% of fecal coliform, 49.4% of total coliform) sit at a laboratory upper limit ([`eda_report.md`](eda_report.md) §6). Stated as a limitation |
| `region` can contain non-target countries (Canada 2,024 rows, United States 413) | ING-2, final profile | Strata assigned from the spatially joined country; US and CA excluded from `gemstat_latin_america` |
| **No African rows at all.** The raw extract holds five regions only: Mexico 168,254 rows, India 86,489, Uruguay 6,531, Canada 2,024, United States 413 | Final profile | `gemstat_africa` stratum is empty. Reported as a data-availability finding |
| **India (the only Asian region) has no *E. coli* rows:** fecal coliform 54,858, total coliform 27,272, enterococci 4,359, all at freshwater water-body types. Freshwater is scored on *E. coli*, so no Asian site meets the eligibility rule (2,067 candidate sites, 0 eligible) | Final profile; [`eda_report.md`](eda_report.md) §7 | `gemstat_asia` stratum is empty. Coliforms are never scored and enterococci is the marine indicator. Reported as a finding, not a defect |
| Mexico (168,254 rows) and Uruguay (983 *E. coli* rows) are the only Latin American countries; all 60 sampled GEMStat sites are in Mexico | [`eda_report.md`](eda_report.md) §7 | Stated on the dashboard and in the findings; the stratum is shown as Mexico (GEMStat) |
| Implausible maximum value: 3,500,000,000 | Final profile | Far above the 1,000,000 flag of VAL-2 `value_range`; not in the sampled sites (largest staged value 2,419,600) |
| 370 rows repeat a (site, date, indicator) | Final profile | Same-day replicates are collapsed to one sample-day in MART-1 |
| Sparse, irregular sampling in many countries | [`source_inventory.md`](source_inventory.md) | Eligibility filter: ≥ 24 primary-indicator samples across ≥ 3 years |
 
### 3.2 Eionet bathing water (`owq_eionet`)
 
| Finding | Evidence | Handling |
|---|---|---|
| Same layout, comment lines and row cap as GEMStat | ING-1 / ING-2 | Same extractor and readers |
| **Zero** fecal or total coliform rows in 2015–2025 | ING-1 | Expected (the bathing-water dataset covers E. coli and enterococci only); logged as expected-empty, not an error |
| **Zero E. coli / enterococci rows from 2022 onward** | ING-1 | Cause not established (reporting lag or the cutoff of the OWQ compilation); only the provider can confirm it. The last sample date in the raw batch is 2021-12-21. Persistence uses each site's most recent 5 *classified* years, so Europe effectively covers 2015–2021. Stated as a limitation |
| `water_body = "other"` is **65%** of Eionet rows | STG-1 | Excluded: cannot be reliably classified as fresh or marine, and the wrong realm means the wrong threshold. Europe marine still has 224 eligible sites for 60 slots |
| Bathing-season sampling only | [`source_inventory.md`](source_inventory.md) | Winter under-represented; stated as a limitation |
| French overseas regions are coded as France | STG-1 | Strata come from the country's continent (`pycountry_convert`, no overrides in `mappings.yaml`), so these sites would count as Europe. They are not excluded and the EDA does not break them out. Stated as a limitation (README §15) |
| Country imbalance: Spain (300,226 rows) and Germany (150,203) are 42% of 1,085,694 rows; 29 regions in total | Final profile | In the 120 sampled sites Spain (47) and Germany (36) are 69%. Stated on the dashboard and in the findings |
 
### 3.3 Water Quality Portal summary (`wqp_summary`)
 
| Finding | Evidence | Handling |
|---|---|---|
| Year column holds invalid values (raw years 1 to 2206) | Final profile | Rows outside 2015–2025 are dropped when site counts are built (`src/extract/wqp_sites.py`), so they never reach sampling |
| A national summary request times out | ING-2 | One request per US state; files named `summary_US-XX` (`:` is invalid in Windows file names) |
| Eligible pools: **9,052** freshwater and **1,484** marine sites | ING-2 | Far above K=60, so sampling (seed 42) keeps the US from dominating |
| `Enterococci` spelling returned **0** summary rows (`Enterococcus` is the name used) | ING-2 | Both spellings mapped, the second kept defensively |
| Site types outside scope (BEACH Program, canals, Great Lakes, stream subtypes), **~10,455 sites** | ING-2 | Excluded; only rivers/streams, lakes/reservoirs, estuaries, ocean |
 
### 3.4 Water Quality Portal results (`wqp_results`)
 
| Finding | Evidence | Handling |
|---|---|---|
| 63 columns; no result ID column | ING-3 | Record ID = SHA-1 of activity, characteristic, fraction, value, unit |
| POST search ignores date filters in the query string | ING-3 | Dates sent in the JSON body |
| Units seen: `#/100ml` (867 results), `MPN/100ml`, `cfu/100ml`. **Unmapped:** `MPN` (968), `CFU` (76), `count` (13) with no volume; `None` (278), `hours` (135) | ING-3 full run, 2026-10-03 | Volume-less and non-concentration units dropped as `unit_unmapped`: **1,449 WQP rows (~11%)**. Open question for PM (STG-2 follow-up) |
| Censoring texts: `Below Detection Limit` (9), `Not Detected at Reporting Limit` (6), value `*Non-detect` (160); unusable: `Not Reported` (19), `Detected Not Quantified` (1) | ING-3 | Mapped to `<` with limit / 2; unusable rows dropped as `non_numeric_value`. Censored share in WQP: **5–13%** (README §15) |
| 8 exact duplicate rows; 897 rows repeat a (site, date, indicator) | Final profile | Replicates are combined per sample-day (geometric mean) in MART-1; VAL-2 `obs_key_unique` passes on the final staging run |
| Quality-control activity types (blanks, field replicates) | ING-3 | Blanks dropped (`qc_blank`); field replicates kept and combined per day (geometric mean) |
| `Rejected` result status, non-water media | ING-3 | Dropped (`result_rejected`, `media_not_water`) |
| Thousands separators in values, e.g. `5,794.0` | STG-2 | Parsed as numbers (`harmonize.to_number`) |
| 400+ submitting organizations with inconsistent names and units | [`source_inventory.md`](source_inventory.md) | Full harmonization in staging; every dropped row counted in `_drop_log.parquet` |
 
### 3.5 Open-Meteo (`open_meteo`)
 
| Finding | Evidence | Handling |
|---|---|---|
| Long requests are weighted: locations × days/14 × variables/10. One cell for 2015–2025 with 2 variables ≈ **57 calls** | ING-4 | Hourly / daily budgets in `sources.yaml` (4,500 / 9,000); the run stops as `partial` and resumes next run (~156 cells/day) |
| One request per 0.25° cell, not per site | ING-4 | Sites in the same cell share weather (`site_cells.csv`) |
| Daily values are UTC days; sample dates are local | ING-4 / CUR-1 | The 48 h window absorbs most of the offset; stated as a limitation |
| Reanalysis, not station rainfall | [`source_inventory.md`](source_inventory.md) | Local convective rain may be missed; stated as a limitation |
| Missing days | Final profile: 0.0% missing precipitation and 0.0% missing temperature across 1,028,608 cell-days (256 cells × 4,018 days). Every observation has a rain value in the curated layer ([`eda_report.md`](eda_report.md) §9) | A window with any missing day gives null rain, never a partial sum; null weather counts as neither wet nor dry |
 
### 3.6 Natural Earth admin-1 (`natural_earth`)
 
| Finding | Evidence | Handling |
|---|---|---|
| **4,596** features, EPSG:4326 | ING-5 | Used as-is |
| `iso_a2 = "-99"` for some territories (STG-0); 0 features in the final profile | STG-0, final profile | Fall back to `adm0_a3` (kept as a guard) |
| 1 of 4,596 features has an invalid geometry | Final profile | Not repaired. It can only affect a site that falls inside that polygon. Stated as a limitation |
| Coastal and marine sites fall just outside land polygons | STG-1 | Nearest polygon within 25 km (`region_match = nearest`), else `none` |
| Some countries only at top-level regions (e.g. France); theme marked beta | [`source_inventory.md`](source_inventory.md) | Accepted; administrative, not watershed, boundaries |
 
## 4. Quality issues across sources
 
| # | Issue | Dimension | Sources | Impact if ignored | Pipeline handling | Check |
|---|---|---|---|---|---|---|
| Q1 | Different indicator names (`Escherichia coli`, `E. coli`, `Enterococcus`, `Enterococci`) | Consistency | all | Same indicator counted as different ones | `mappings.yaml › indicator_names` | VAL-2 `accepted_values` |
| Q2 | Different or missing units | Consistency, validity | WQP | Values on different scales compared | Unit factor table; unmapped rows dropped and counted | STG-2 drop log, VAL-3 `reconciliation` |
| Q3 | Censored values (`<10`, `Not Detected`) | Validity | WQP, OWQ | Non-numeric values lost or treated as exact | `<x` → x/2, `>x` → x (same as OWQ) | `is_censored`, `censor_direction` columns |
| Q4 | Lab upper-limit values | Accuracy | GEMStat | Severity understated | Documented limitation | — |
| Q5 | No record or site IDs | Uniqueness | OWQ | Duplicates, no lineage key | Deterministic SHA-1 keys, rounded-coordinate sites | VAL-2 `obs_key_unique` |
| Q6 | Same-day replicates | Uniqueness | WQP | One event counted several times | Collapsed to one sample-day (geometric mean) in MART-1 | — |
| Q7 | QC blanks, rejected results | Validity | WQP | Non-environmental values scored | Dropped with reasons | drop log |
| Q8 | Unclassifiable water body (`other`, 65% of Eionet) | Completeness | Eionet | Wrong threshold applied | Excluded | `water_body_excluded` in drop log |
| Q9 | Data gap from 2022 | Timeliness | Eionet | Recent years look clean | Most recent *classified* years used; flagged | VAL-2 `stratum_coverage` |
| Q10 | Empty strata (Africa, Asia) | Coverage | GEMStat | Rankings look global but aren't | Reported as a finding | VAL-2 `stratum_coverage` (warning) |
| Q11 | Missing or invalid coordinates | Validity | all | Site cannot be placed or matched to weather | Dropped as `bad_coordinates` | VAL-2 `coordinates_valid` |
| Q12 | Row cap / timeouts at source | Completeness | OWQ, WQP | Silent truncation | Chunking; manifest row counts | VAL-1 `row_count_matches` |
| Q13 | Rate limits | Completeness | Open-Meteo | Missing weather | Budgeted, resumable extract | VAL-3 `weather_coverage` (≥ 90%) |
 
In the final run VAL-2 raises two warnings, both expected: `stratum_coverage` (the stratum × realm combinations without sampled sites: Africa and Asia in both realms, and Latin America marine) and `value_range` (values above 1,000,000, which are the 2,419,600 laboratory upper limit; kept and flagged). All critical checks pass ([`evidence/final_run_evidence.txt`](evidence/final_run_evidence.txt)).

## 5. Sampling outcome
 
| Stratum | Source | Freshwater sites | Marine sites | Note |
|---|---|---|---|---|
| `us` | WQP | 60 | 60 | 120 in total; eligible pools 9,052 / 1,484; includes Puerto Rico (5) and US Virgin Islands (3) |
| `europe` | Eionet | 60 | 60 | 120 in total across 13 countries; 224 eligible marine; Spain 47, Germany 36 |
| `gemstat_latin_america` | GEMStat | 60 | 0 | 60 in total, all in Mexico; 1,463 eligible of 3,580 candidates; no marine sites |
| `gemstat_africa` | GEMStat | 0 | 0 | No rows in the raw extract |
| `gemstat_asia` | GEMStat | 0 | 0 | 2,067 candidate sites, none eligible: no *E. coli* rows |
| **Total** | | | | **300 sites** ([`business_rules.md`](business_rules.md) §6) |
 
The per-realm split is in `data/staging/sampled_sites/_manifest.json` (STG-1 sampling summary).
 
## 6. Limitations
 
1. **Geographic coverage.** Scored sites are in the United States, Europe (69% of them in Spain and Germany) and Mexico only. Africa has no rows in the GEMStat extract and Asia (India) has no *E. coli* rows, so neither can be scored. Results are not global comparisons. The gap reflects data sharing and indicator choice, not pollution levels.
2. **Different monitoring designs.** GEMStat river stations, Eionet bathing sites and WQP mixed networks sample differently, so cross-stratum comparisons are partly about design.
3. **Pre-harmonized OWQ data.** We cannot see OWQ's original censoring or units, so GEMStat/Eionet censored shares are unknown.
4. **Lab upper limits** understate severity in Latin America.
5. **Eionet gap after 2021** and bathing-season-only sampling.
6. **Dropped WQP units** (~11% of WQP rows) may hold usable data if their volume could be confirmed.
7. **Weather** is 0.25° reanalysis in UTC days, not station rainfall at the sampling time.
8. **Administrative regions**, not watersheds, so a polluted river can span several regions.
9. **MPN = CFU** is an approximation (the same one OWQ makes).
10. **GEMStat time coverage.** The sampled GEMStat sites have about 1,060 observations a year to 2018, then 225, 118 and 5 (2019–2021), so Latin America's recent years are mostly 2015–2018.
