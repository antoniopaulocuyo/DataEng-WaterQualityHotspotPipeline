# Analysis Findings

Final run, 2026-10-11. Numbers come from [`eda_report.md`](eda_report.md) (section numbers in brackets) and [`evidence/final_run_evidence.txt`](evidence/final_run_evidence.txt).

## Scope: what these results cover

The results cover **the United States (120 sites), Europe (120 sites, 13 countries) and Mexico (60 sites)**. They are **not global comparisons**. Africa has no rows in the GEMStat extract, and Asia (India) has no *E. coli* rows, so neither has scored sites [§7]. Within the sample, Spain (47) and Germany (36) are 69% of the European sites, and all 60 GEMStat sites are in Mexico.

## Key findings

- **Every row is accounted for.** 1,362,645 raw rows (1,349,405 OWQ and 13,240 WQP) became 25,108 staging rows, equal to 25,108 curated and `fact_observation` rows. Almost all dropped OWQ rows are sites that were not sampled, by design [§3, §8].
- **Mexico (GEMStat) is heavily polluted at the sampled sites.** *E. coli* median 750 CFU/100 mL against the 410 threshold, 56% of samples above it, and 53 of 60 sites (88%) are persistent hotspots [§6, §10].
- **European bathing sites are clean.** About 3% of samples exceed the thresholds (2.9% *E. coli*, 3.4% enterococci), medians are 10–15, and 5 of 120 sites are persistent hotspots [§6, §10].
- **The United States sits in between.** 14–15% of samples exceed the thresholds, and 26–31% of sites are persistent hotspots [§6, §10].
- **Key question 3: exceedance is higher after rain in the US and Mexico, but not visibly in Europe.** At the median site the exceedance rate is 0.80 on wet days against 0.52 on dry days in Mexico, 0.25 against 0.05 for US fresh water and 0.14 against 0.04 for US marine. In those groups 66–73% of sites with both conditions have a higher wet rate. In Europe both medians are 0.00 because most sites almost never exceed, so there is no wet/dry difference to find [§11]. The pooled row (0.09 against 0.04) is dominated by Europe's zeros and should not be read alone. This is an association, not proof that rain causes the exceedance.
- **Weather coverage is complete.** Every observation in all three sources has a rain value (100%), from 1,028,608 cell-days with 0% missing [§9].
- **Time coverage is very uneven.** WQP covers 2015–2025, Eionet ends in 2021, and the sampled GEMStat sites have about 1,060 observations a year to 2018, then 225, 118 and 5 (2019–2021). Mexico's "recent years" are mostly 2015–2018, so comparing strata compares different years [§5].
- **Validation:** all critical checks pass in the final run. Two warnings are expected: `stratum_coverage` (the five stratum × realm combinations with no sites) and `value_range` (values at the 2,419,600 laboratory upper limit) [`final_run_evidence.txt`].

## Current limitations

- **Coverage.** United States, Europe and Mexico only; Spain and Germany dominate the European sample. The dashboard states this next to the ranking, because a top-10 list built from this sample is dominated by Mexican regions.
- **Lab upper limits.** GEMStat values cluster at 24,196 and 2,419,600, the laboratory reporting maximums, meaning "at least this much". In the sample 21.9% of GEMStat *E. coli* values (34.2% of fecal coliform, 49.4% of total coliform) sit at an upper limit, so severity is understated for Mexico. Exceedance and hotspot results are unaffected, since those values are far above 410 [§6].
- **Censoring is visible only for WQP** (5–13%). OWQ filled censored values before export, so 0% for OWQ means "unknown", not "none".
- **Null columns.** About 55% of `activity_id`, `activity_type` and `result_status` are null because OWQ rows have no such fields [§8].
- **WQP unit drops.** 1,449 rows (about 11% of WQP) were dropped as unmapped units, mostly `MPN` and `CFU` without a volume. Recovering them is a future improvement and would add about 1,271 rows [§8].
- **Different monitoring designs.** GEMStat river stations, Eionet bathing sites and WQP mixed networks sample differently, so cross-stratum differences partly reflect design [§10].
- **Eionet ends in 2021** and samples only during the bathing season.
