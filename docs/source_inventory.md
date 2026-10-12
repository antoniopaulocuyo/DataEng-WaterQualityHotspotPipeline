# Source Inventory
 
**Owner:** Labilles · **Started:** 2026-09-25 (first commit) · **Last updated:** 2026-10-11

"Accessed" = date the source was pulled or its documentation checked. "Final batch" = the raw batch used in the final run (2026-10-11). "Terms checked" = date the licence or data policy was read on the provider's site. Profiling numbers for each batch are in [`source_profiling.md`](source_profiling.md).
 
---
 
## 1. GEMStat (via Open Water Quality export)
 
| Field | Value |
|---|---|
| Original provider | UNEP GEMS/Water (GEMStat) |
| Harmonized by | Open Water Quality project: UNU-INWEH, Colorado State University, University of Colorado Boulder |
| URL | https://openwaterquality.org/ (Data tab) · original: https://gemstat.org/ |
| Format | CSV (observations), GeoJSON (sites) |
| Retrieval method | Scripted export request (confirmed ING-2 spike). Endpoint: `https://lume-inventory-api.evan-thomas-3d8.workers.dev/api/wq/export` — separate Cloudflare Worker domain, not `openwaterquality.org` itself. `GET`, no auth, CORS open. Params: `year_from`, `year_to`, `var` (indicator code), `source=GEMStat`, `loc_type`, `format`. Responses capped at 100,000 rows (`X-Row-Count`/`X-Row-Capped` headers); extractor chunks by year with a loc_type-split fallback on cap. |
| Coverage | The OWQ GEMStat extract holds five regions only: Mexico, India, Uruguay, Canada and the United States (263,711 rows, 2015–2023 in our pull). Used for the Latin America stratum (Mexico in the sample). It has no African rows, and India has no *E. coli* rows, so no Asian site is scored ([`source_profiling.md`](source_profiling.md) §3.1) |
| Size (OWQ, all years) | ~400K observations |
| Update frequency | OWQ is a research compilation, so treat it as a periodic snapshot: in our pull GEMStat rows thin out after 2020 and end 2023-08-02. GEMStat itself publishes its Global Freshwater Quality Archive in versioned updates (https://gemstat.org/update-gfqa/) |
| License / terms | Observations remain the property of the contributing programmes and must be cited on reuse. Each raw file starts with 7 `#` attribution lines, copied to [`evidence/owq_attribution.txt`](evidence/owq_attribution.txt). GEMStat's data policy (https://gemstat.org/update-gfqa/) has an open tier equivalent to CC BY 4.0 (any use with attribution) and a limited tier equivalent to CC BY-NC 4.0 (non-commercial only). This project is non-commercial and cites the source, so both tiers are compatible. Terms checked 2026-10-11 |
| Accessed | 2026-09-27 (ING-2 spike + real extraction run) |
| Final batch | `owq_gemstat_cbe19092b675` |
| Known limitations | Already harmonized by OWQ (MPN treated as CFU; censored values filled at half the detection limit; cross-source dedupe at ~1 km). Sparse, irregular sampling in many countries. Original GEMStat access is manual. `region` field can include non-target countries (Canada, United States), so strata are assigned from the spatially joined country, not from `source`. |
 
## 2. Eionet bathing water (via Open Water Quality export)
 
| Field | Value |
|---|---|
| Original provider | European Environment Agency (EEA) / Eionet |
| Harmonized by | Open Water Quality project (as above) |
| URL | https://openwaterquality.org/ (Data tab) |
| Format | CSV, GeoJSON |
| Retrieval method | Same scripted endpoint as GEMStat, `source=Eionet`. Confirmed via ING-2 spike; same cap/chunking behavior applies. |
| Coverage | Europe; main source of marine / enterococci observations |
| Size (OWQ, all years) | ~2.4M observations |
| Update frequency | Bathing-water monitoring is seasonal (the bathing season, May to September). The OWQ snapshot in our pull ends 2021-12-21; whether newer seasons exist at EEA or only missed the OWQ compilation is not established |
| License / terms | OWQ attribution as above (see [`evidence/owq_attribution.txt`](evidence/owq_attribution.txt)). The EEA data catalogue lists the bathing-water data as CC BY 4.0, free reuse with attribution (https://sdi.eea.europa.eu/catalogue/srv/api/records/53ef1ba4-4aff-4bf3-9509-de5a43f4e15f). Terms checked 2026-10-11 |
| Accessed | 2026-09-27 (ING-2 spike + real extraction run) |
| Final batch | `owq_eionet_e86ef04d7716` (1,085,694 rows, 2015–2021, 29 regions) |
| Known limitations | Bathing sites only, sampled mainly during the bathing season, so winter conditions are under-represented. Pre-harmonized by OWQ. Originally obtained by OWQ via web scraping. Zero fecal/total coliform data across the full 2015–2025 pull (dataset is scoped to E. coli/enterococci only — expected, not a bug). Zero E. coli/enterococci data from 2022 onward: cause not established (reporting lag or the cutoff of the OWQ compilation), so Europe effectively covers 2015–2021. |

### Confirmed `var` codes (ING-2 spike)

| Indicator | `var` code |
|---|---|
| E. coli | `ecoli` |
| Enterococci | `entero` |
| Fecal coliform | `fc` |
| Total coliform | `tc` |
 
## 3. Water Quality Portal (WQP)
 
| Field | Value |
|---|---|
| Provider | USGS, US EPA, National Water Quality Monitoring Council |
| URL | https://www.waterqualitydata.us/ · web services: https://www.waterqualitydata.us/webservices_documentation/ |
| Format | CSV (also available: TSV, Excel, KML) |
| Retrieval method | REST API (site catalog, then results for sampled sites) |
| Coverage | United States; ~6.9M fecal indicator observations |
| Update frequency | Continuous, as contributing agencies submit data; records are added or improved at irregular intervals |
| License / terms | US federal public data, free to use. Cite as: *Water Quality Portal*, National Water Quality Monitoring Council, USGS and US EPA, https://doi.org/10.5066/P9QRKUVJ (catalogue record: https://water.usgs.gov/catalog/datasets/b971c11a-0d87-496b-bb11-d78a950fcc9e). Terms checked 2026-10-11 |
| Accessed | 2026-09-26 |
| Final batches | `wqp_summary_9fe8e48f2a31` (540,786 summary rows, used only for sampling), `wqp_results_8c80b98f221b` (13,240 result rows) |
| Known limitations | Data submitted by 400+ organizations with inconsistent units, characteristic names, and detection-limit reporting. WQX 3.0 profiles are in beta; we use the current (non-beta) services. Raw data needs full harmonization in staging. |
 
## 4. Open-Meteo Historical Weather API
 
| Field | Value |
|---|---|
| Provider | Open-Meteo (based on ERA5 / ERA5-Land reanalysis) |
| URL | https://open-meteo.com/en/docs/historical-weather-api · endpoint: https://archive-api.open-meteo.com/v1/archive |
| Format | JSON |
| Retrieval method | REST API, one request per 0.25° grid cell containing sampled sites |
| Variables used | `precipitation_sum`, `temperature_2m_mean` (daily) |
| Coverage | Global, 1940 onward |
| Update frequency | The archive grows continuously; the most recent days lag behind real time. The final run uses 2015-01-01 to 2025-12-31, complete for all 256 cells |
| License / terms | Free for non-commercial use without an API key (limit 10,000 calls a day); data under CC BY 4.0, so attribution to Open-Meteo.com is required (https://open-meteo.com/). Terms checked 2026-10-11 |
| Accessed | 2026-09-26 |
| Final batch | `open_meteo_1265e632620d` (256 cells, 1,028,608 cell-days) |
| Known limitations | Gridded model reanalysis, not station measurements; local convective rainfall may be under- or over-estimated. Rate limits apply to the free tier. |
 
## 5. Natural Earth Admin-1 States/Provinces (10m)
 
| Field | Value |
|---|---|
| Provider | Natural Earth |
| URL | https://www.naturalearthdata.com/?p=480 |
| Format | Shapefile (zip) |
| Retrieval method | Automated file download (URL pinned in `config/sources.yaml`) |
| Coverage | Global first-order administrative divisions |
| Update frequency | Irregular versioned releases |
| License / terms | Public domain |
| Accessed | 2026-09-26 |
| Final batch | `natural_earth_e47c2a7cb821` (4,596 features) |
| Known limitations | Theme marked beta by Natural Earth. Some countries (e.g. France) are represented at top-level regions only. Administrative, not watershed, boundaries. |
 
---
 
## Excluded sources
 
| Source | Reason |
|---|---|
| WPdx | ~1,300 observations globally; too few repeat samples per site to assess persistence |
| UK Open WIMS, DataStream, Hub'Eau, NMMP, LAWA | Out of scope for the 7-day build; listed as future improvements (native API ingestion) |