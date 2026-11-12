# Phase 3 Acceptance Audit — AI Mineral Reserve Mapping Assistant

**Audit Date:** 2026-11-12  
**Audited Commit:** `9d9a438e1a1d861ad17f9184ab378cbd8db4e2c9`  
**Repository:** `https://github.com/JohnSamuelJohnSamuelTitus/ai-mineral-reserve-mapping.git`  
**Branch:** `main`  

---

## 1. Executive Summary

This acceptance audit evaluated all four Phase 3 workstreams (**3A** geological normalization & satellite discovery, **3B** raster processing & feature engineering, **3C** interactive GIS workbench, **3D** spatial ML dataset preparation & readiness gates) against source code, test suites, persistent local data (`data/`), live external data providers, and a live Chrome DevTools Protocol (CDP) browser session against the running FastAPI + Vite application.

**Summary Verdict Table**

| Component | Implemented | Synthetic Tested | Live Tested | Real Data Processed | Status |
|---|---|---|---|---|---|
| 3A — Multi-format Geological Importer (CSV/GeoJSON/GPKG/SHP ZIP), Normalization, Quarantine & Quality Reports | Yes | Yes (`pytest`) | Partial (live MRDS/Macrostrat parsed via script; UI button 404) | Partial (in temp audit session; 0 rows persisted in `data/mineral_dev.db`) | **PARTIAL** |
| 3A — STAC Discovery (Planetary Computer, Earth Search, NASA CMR) & Auth/Size Guardrails | Yes | Yes (`pytest`) | Yes (all 3 catalogs + MPC SAS token signing) | Partial (metadata discovered live; `aster-l1t` & NASA CMR EMIT not downloaded) | **PASS** |
| 3A — Bounded Windowed COG Downloader & UI Trigger | Yes | Yes (`pytest`) | Yes in Python; **FAIL in Web UI (HTTP 404)** | Yes in temp session (COP-30 DEM `0.0335 MB` + 7 S2 bands `~0.93 MB`); 0 on disk in `data/rasters/` | **PARTIAL** |
| 3B — Raster Alignment (`TargetGridSpec` UTM), Safety Bounds & DEM Terrain Derivatives | Yes | Yes (`pytest`) | Yes (`EPSG:32643`, Khetri) | **PARTIAL** (COP-30 `N28_00` covered only `48.04%` of Khetri AOI; southern tile `N27_00` not mosaicked) | **PARTIAL** |
| 3B — Sentinel-2 Spectral Indices & SCL Cloud Masking | Yes | Yes (`pytest`) | Yes via Python (`S2C_43REL_20261112_0_L2A`) | Yes in Python (`93.93%` valid px across 7 ratios/masks); **NOT reachable via HTTP API / Web UI** | **PARTIAL** |
| 3B — ASTER Spectral Indices | Yes | Yes (`pytest` synthetic bands) | Search only (3 MPC `aster-l1t` scenes found) | **No** (MPC grouped `VNIR/SWIR/TIR` COGs not unpacked/processed; HTTP API cannot accept them) | **PARTIAL** |
| 3B — Geological Proximity & Non-Fabrication Policy | Yes | Yes (`pytest`) | Yes (Macrostrat + MRDS Khetri) | Partial (`dist_to_occurrence_m` + `geology_unit_index` computed; 0 faults/intrusives/contacts ingested; not fabricated) | **PASS** |
| 3C — Interactive GIS Workbench (MapLibre, AOI Persistence, Layers, GIBS Warning, Inspector) | Yes | Yes (`Vitest` + `Testing Library`) | Yes (headless Chrome CDP on `localhost:5173`) | Partial (Khetri AOI + STAC footprints + OSM tiles rendered; Live Ingest & Download buttons **FAIL 404**) | **FAIL** |
| 3D — PU Spatial ML Dataset Builder, Leakage Checks & Readiness Gates (`HTTP 422` Block) | Yes | Yes (`pytest`) | Yes (on real Khetri feature stack) | Yes — correctly **BLOCKED** (`quality_passed=False`: `1` positive pixel in `1` block < `10` min positives / `3` blocks) | **PASS** |
| 3D — GroupKFold Spatial Baseline Evaluation (`LogReg` & `RandomForest`) | Yes | Yes (`pytest` synthetic 14-occ AOI) | Tested refusal on sparse real Khetri | **No** (rightly blocked on Khetri; no ML-ready real AOI persisted in `data/`) | **PARTIAL** |

**Overall Phase 4 Readiness Decision:** **C. NOT READY** (see Section 13 for evidence and remediation prerequisites).

---

## 2. Git and Repository State

Inspected via `git status`, `git branch -vv`, `git rev-parse`, `git log -n 10 --oneline`, and `git diff`:

- **Current branch:** `main` tracking `origin/main` (`[origin/main]`).
- **Commit parity:** Local `HEAD` and `origin/main` both equal `9d9a438e1a1d861ad17f9184ab378cbd8db4e2c9`.
- **Commit history reviewed:**
  - `9d9a438` `docs(phase3): add scientific documentation and completion report`
  - `222f513` `feat(phase3d): add spatial ML dataset preparation`
  - `3335763` `feat(phase3c): build interactive GIS workbench`
  - `6d0be94` `feat(phase3b): implement raster and geospatial feature engineering`
  - `d316fc7` `feat(phase3a): add geological data normalization and satellite discovery`
  - `004675e` `feat(phase2): implement SQLite geospatial backend, resilient adapters, ingestion pipeline, and frontend shell`
  - `a395e4e` `chore: initialize Phase 1 architecture, API catalog, and project foundation`
- **Working tree state at audit start:** **Not clean** — 6 Phase 3 documentation files (`FEATURE_ENGINEERING_GUIDE.md`, `GEOLOGICAL_DATA_QUALITY.md`, `ML_DATASET_GUIDE.md`, `PHASE3_COMPLETION_REPORT.md`, `RASTER_PROCESSING_GUIDE.md`, `SATELLITE_DATA_GUIDE.md`) showed unstaged `+1` trailing blank-line additions (`LF`/`CRLF` warning) created after `9d9a438`. No tracked Python or TypeScript source files were modified.
- **`.gitignore` / ignored workspace directories:** `data/raw/`, `data/interim/`, `data/processed/`, `data/cache/`, `*.tif`, `*.tiff`, `*.db`, `.env`, `node_modules/` are ignored. Note: `data/rasters/` itself is not listed by directory in `.gitignore` (only raster extensions like `*.tif` are ignored).
- **Persistent repository state at rest (`data/`):**
  - `data/mineral_dev.db` (`184,320` bytes): contains `alembic_version` (`1` row) and `data_sources` (`15` seeded rows). All operational tables (`areas_of_interest`, `mineral_occurrences`, `geological_units`, `ingestion_jobs`, `raster_assets`, `occurrence_quarantined`, `dataset_quality_reports`, `processing_jobs`, `feature_manifests`, `ml_dataset_versions`) contain **`0` rows**.
  - `data/raw/`, `data/interim/`, `data/processed/`, `data/rasters/`: **`0` downloaded rasters, `0` feature stacks, `0` ML datasets**.

---

## 3. Phase 3A Findings — Geological Data & Satellite Discovery

### Geological Data Pipeline
- **Implemented & Verified via `pytest`:**
  - `backend/app/geological/importers.py` handles `.csv`, `.geojson`/`.json`, `.gpkg`, and `.zip`/`.shp` (zip-slip path containment guard via `sanitize_filename` + `relative_to`, reprojection from `input_epsg` to `EPSG:4326`).
  - `backend/app/geological/normalizer.py` normalizes heterogeneous commodity names via `COMMODITY_SYNONYMS` and delimited tokens (`parse_commodity_list`), validates finite WGS84 coordinates, rejects `(0, 0)` null-island coordinates, quarantines invalid/missing-coordinate/duplicate rows (`QuarantinedRecord`), and records spatial AOI clipping.
  - `backend/app/geological/quality.py` persists `dataset_quality_reports` with completeness %, commodity counts, and mandatory `SCIENTIFIC_BIAS_WARNING`.
  - `backend/app/api/v1/geology_routes.py` exposes `/api/v1/geology/aois/{aoi_id}/import`, `/quality-reports`, and `/quarantine` (note: documented inconsistently in `PHASE3_COMPLETION_REPORT.md` as `/quarantined`).
- **Live External Defect Discovered (`USGSMRDSAdapter`):**
  - Live USGS MRDS WFS 1.0.0 (`mrds-low`) returns commodity tags under `<code_list>CU</code_list>`, not `<commod1>` or `<commodity>`.
  - Because `backend/app/integrations/usgs_mrds.py` (`lines 124–127`) only reads `commod1`/`commod2`/`commod3`/`commodity`, **100% of live WFS `mrds-low` records parsed with `commodity_primary = None` and `commodities_all = []`** (`Khetri Copper Belt` had `code_list='CU'`, stored as `None`).

### Satellite Discovery & Bounded Downloads
- **Implemented & Live Tested:**
  - `STACSearchAdapter` (`backend/app/integrations/stac.py`) cleanly discovers items from Element 84 Earth Search (`https://earth-search.aws.element84.com/v1`), Microsoft Planetary Computer (`https://planetarycomputer.microsoft.com/api/stac/v1`), and NASA CMR LPCLOUD (`https://cmr.earthdata.nasa.gov/stac/LPCLOUD`).
  - `BAND_ALIASES` normalizes asset names across catalogs; nighttime TIR-only ASTER items are tagged `aster_tir_only`; `requires_auth=True` blocks unauthenticated NASA CMR downloads with `HTTP 403` (`satellite_routes.py:232-236`); `estimate_clipped_raster_mb` estimates clipped transfer size; cloud-cover filtering `eo:cloud_cover <= max_cloud_cover` works for MPC and Earth Search.
  - Ephemeral MPC SAS signing (`sign_mpc_asset_url`) verified live against `aster-l1t` (`signed? True`).
  - NASA GIBS layers (`backend/app/integrations/nasa_gibs.py`) are flagged `is_quantitative_science_product: false` and kept strictly out of scientific raster ingestion.
- **Windowed Download Pipeline (`downloader.py` vs API/UI):**
  - `download_cog_window_for_aoi` works reliably via windowed `rasterio.open(...)` + `from_bounds(...)`, clamping strictly to raster extent, checking free disk space & size caps, and writing deflated GeoTIFFs with SHA-256 checksums.
  - **Defect:** Backend route `POST /api/v1/satellite/scenes/{asset_id}/download-clipped` mismatches `frontend/src/services/api.ts` (`POST /api/v1/satellite/assets/{assetId}/download`), returning `HTTP 404` in the live UI. Also `RasterAsset` stores only one scalar `local_path`, preventing multi-band Sentinel-2 storage per scene through `/download-clipped`.

---

## 4. Phase 3B Findings — Raster & Geospatial Feature Engineering

### Core Implementation Inspection
- `raster_ops.py`: `build_aoi_target_grid` dynamically selects UTM via `choose_utm_epsg` (`EPSG:32643` for Khetri), rounds metric bounds outward cleanly, enforces a `<= 4096 x 4096` dimension cap, and aligns layers with `reproject_to_grid` and `DEFAULT_NODATA = -9999.0`.
- `spectral.py`: Computes all 6 Sentinel-2 indices (`ndvi`, `ndwi`, `ndbi`, `s2_iron_oxide_ratio`, `s2_ferrous_iron_ratio`, `s2_clay_hydroxyl_ratio`) plus `s2_bare_earth_mask`, masking `SCL` cloud/shadow/snow classes (`0, 1, 3, 8, 9, 10, 11`) and guarding divide-by-zero / non-finite / negative reflectance pixels.
- `terrain.py`: Rejects geographic degrees (`is_projected_metric=False`), computes Horn 3x3 `elevation_m`, `slope_deg`, `aspect_deg`, `hillshade`, `tri`, `tpi`, `curvature`, and `drainage_proxy` verified analytically in `pytest`.
- `proximity.py`: Computes metric Euclidean distance in UTM and rasterizes geological units. When fault, intrusive, or contact layers are absent, it does **not** fabricate values — emitting explicit `warnings_json` messages instead.

### Critical Gaps in 3B
1. **Sentinel-2 & ASTER HTTP API Disconnect:** `extract_aoi_features(...)` in `pipeline.py` accepts `sentinel_band_paths` and `aster_band_paths` in Python, **but** `FeatureExtractRequest` and `_execute_feature_job_with_session` (`features_routes.py:83-90`) only pass `dem_asset_id`, `resolution_m`, and `include_geology`. Neither the REST API nor the Web UI can run Sentinel-2 or ASTER spectral feature extraction yet.
2. **DEM Tile Boundary Mosaicking Gap (`48.04%` Coverage on Khetri):** Khetri (`27.98°N–28.02°N`) straddles two 1° COP-30 tiles (`N28_00` and `N27_00`). Because `_find_downloaded_dem_asset` selects only one `RasterAsset`, southern Khetri (`51.96%` of grid pixels) became `-9999.0` NoData across all 8 terrain bands.
3. **ASTER Real Asset Schema Mismatch:** `compute_aster_features` expects separate single-band inputs named `B01`, `B02`, `B05`, `B06`, `B07`, `B10`, `B13`, whereas live Planetary Computer `aster-l1t` delivers 3 grouped multi-band files (`VNIR`, `SWIR`, `TIR`). No real ASTER scene was downloaded or processed.
4. **Fault & Intrusive Layers Unwired:** Neither `IngestionPipeline` nor `/features/aois/{aoi_id}/extract` populates `verified_fault_geometries_wgs84` or `verified_intrusive_geometries_wgs84`. Fault and intrusive proximity features remain unavailable for Khetri (honestly warned, not fabricated).

---

## 5. Phase 3C Findings — Interactive GIS Workbench

Verified both via `Vitest` (`3/3` passing with mocked `fetch` and mocked `maplibre-gl`) and **live headless Chrome CDP** (`audit_browser_cdp.py` against `uvicorn` + `vite dev` on `http://localhost:5173/`, screenshot saved at [phase3_audit_workbench.png](file:///C:/Users/Admin/.gemini/antigravity/brain/f8974c0b-6b6c-4013-bd91-fefa91e631c1/phase3_audit_workbench.png)):

- **Verified Working Live in Chrome:**
  - Initial load & empty state (`DB: SQLITE`, empty AOI prompt, zero console errors/JS exceptions).
  - AOI creation (`+ Khetri Preset`, `27.2 km² · EPSG:32643`) and persistence across full page reload (`Page.reload`).
  - MapLibre GL JS rendering with OpenStreetMap basemap tiles, active AOI polygon, STAC scene footprints, scale bar (`1 km`), and coordinate readout.
  - Basemap switching to `nasa_gibs` displays the non-quantitative visualization warning banner.
  - Layer stack tab toggles, z-order controls, and opacity sliders (2 sliders shown: `feature_overlay` and `geology_units`; note `mineral_occurrences`, `aoi_boundary`, and `raster_footprints` have fixed UI opacity).
  - Satellite STAC Search via Earth Search (`Discovered Rasters (8)`, saved to catalog).
  - Feature extraction empty-prerequisite error toast (`HTTP 422`: `"No valid features could be produced for this AOI..."`) and Right Drawer tabs (`Inspector`, `AOI Health` coverage metrics grid, `Features & ML`).
- **Verified Broken Live in Chrome (`HTTP 404`):**
  - **"Ingest Live Macrostrat & USGS MRDS"** -> `POST /api/v1/aois/{aoi_id}/ingest` -> **`404 Not Found`** (actual backend route is `POST /api/v1/ingestion/aois/{aoi_id}/run`).
  - **"Clip & Download Window"** -> `POST /api/v1/satellite/assets/{asset_id}/download?aoi_id=...&run_sync=true` -> **`404 Not Found`** (actual backend route is `POST /api/v1/satellite/scenes/{asset_id}/download-clipped`).
- **Not Interactively Driven in Live Canvas:** Freehand map polygon click-drawing, vertex dragging, and interactive bowtie drawing in the canvas were verified via Vitest unit tests (`polygonGeometry.test`) rather than mouse-click CDP events. Because Live Ingest & Download failed 404 in the UI, live occurrence markers, live geological unit polygons, and live raster PNG overlays could not populate through UI clicks alone.

---

## 6. Phase 3D Findings — Spatial ML Dataset Readiness

- **Implemented & Verified (`pytest` + Live Real Khetri Run):**
  - `build_spatial_ml_dataset` (`backend/app/ml/dataset_builder.py`) strictly labels `PU_KNOWN_OCCURRENCE = "known_occurrence"` (`1`), `PU_UNLABELED_BACKGROUND = "unlabeled_background"` (`-1`), and enforces `explicit_negative_count = 0` (never inventing negative mineral labels).
  - Deterministically assigns UTM spatial blocks `B_{bx}_{by}` (default `1000m`), enforces a positive-to-background exclusion halo (`max(resolution_m * 1.5, block_size_m * 0.25) = 250m` at 60m/1000m), excludes non-ML-trainable sources (`mindat_v1`), strips `dist_to_occurrence_m` by default (flagging `target_leakage_detected = True` if forced), and refuses non-`real` datasets.
  - `evaluate_spatial_baseline` (`backend/app/ml/baseline.py`) uses `GroupKFold` grouped strictly by `spatial_block_id` with explicit block-disjoint assertions, evaluating `LogisticRegression` and `RandomForestClassifier` with explicit PU-proxy metrics/disclaimers.
  - **Refusal Gate Verified:** Returning `HTTP 422` whenever `quality_passed=False` or `leakage_checked=False` works accurately in both `pytest` and live Khetri testing.

---

## 7. Live Provider Verification

Bounded live requests executed 2026-11-12 during this audit (no large downloads performed):

| Provider | Live Request Performed | Response / Status | Result Count & Data Format | Parsed & Used? | Restrictions / Caveats |
|---|---|---|---|---|---|
| **OSM Nominatim** | Geocode `"Khetri, Rajasthan"` | `OK` (`HTTP 200`, JSONv2) | `2` places (`28.000337, 75.784133`) | Parsed in adapter; wired to `/api/v1/search/geocode` | ODbL 1.0, `1 req/s` cap, custom `User-Agent` |
| **Macrostrat v2** | `/geologic_units/map?lat=28&lng=75.79` | `OK` (`HTTP 200`, JSON) | `1` unit (`Cenozoic sedimentary rocks`) | Parsed & stored in audit session; coarse regional scale | CC BY 4.0; lacks district-scale Proterozoic Khetri subunits & faults |
| **USGS MRDS WFS** | Khetri tight/wide + Walker Lane NV (`mrds-low`) | `OK` (`HTTP 200`, GML2 XML) | Khetri tight: `2`; Khetri wide: `6`; Walker Lane: `20` | Parsed & stored, **but `commodity_primary=None`** due to `code_list` bug | Public Domain; sparse non-US coverage (`2` occurrences in Khetri collapsing to `1` pixel) |
| **Element 84 Earth Search STAC** | Khetri bbox (`cop-dem-glo-30`, `sentinel-2-l2a`) | `OK` (`HTTP 200`, STAC JSON) | DEM: `2` tiles (`N28_00`, `N27_00`); S2: `3` items (`cloud <= 15%`) | Parsed, stored in browser session, COG windows downloaded & processed in Python | Copernicus Open Access; UI download button hits 404 bug |
| **Planetary Computer STAC** | Khetri bbox (`sentinel-2-l2a`, `aster-l1t`) + SAS sign | `OK` (`HTTP 200`, STAC JSON + SAS token) | S2: `3` (`0.11%` cloud); ASTER: `3` (`aster_multispectral`) | Metadata parsed & SAS URL signed (`signed=True`); no pixel download tested | Ephemeral SAS required; ASTER bands grouped in `VNIR/SWIR/TIR` |
| **NASA CMR LPCLOUD STAC** | Khetri bbox (`EMITL2BMIN_001`, `AST_L1T_003`) | `OK` (`HTTP 200`, STAC JSON) | `EMIT`: `3`; `AST_L1T`: `0` | Discovery only; `requires_auth=True` enforced cleanly | NASA Earthdata bearer token required (not configured locally: `earthdata_set=False`) |
| **Open Topo Data (`srtm30m`)** | Point `(28.00, 75.79)` | `OK` (`HTTP 200`, JSON) | `1` point (`elev_m = 401.0`) | Parsed cleanly | `1 req/s`, max 100 pts/req, 1000/day |
| **Open-Meteo Elevation** | Point `(28.00, 75.79)` | `OK` (`HTTP 200`, JSON) | `1` point (`elev_m = 399.0`) | Parsed cleanly (fallback adapter) | CC BY 4.0 non-commercial unless commercial plan |
| **OpenAlex Works** | Search `"Khetri copper belt"` | `OK` (`HTTP 200`, JSON) | `3` works (top: 1979 Rb-Sr paper) | Parsed cleanly (`openalex_set=False` shared pool) | CC0 metadata; higher quota needs optional free `OPENALEX_API_KEY` |

---

## 8. Actual Raster and Feature Inventory

### Persistent Repository Inventory (`data/` at rest)
- `data/rasters/`: **0 downloaded raster files**.
- `data/mineral_dev.db`: **0 `RasterAsset` rows, 0 `FeatureManifest` rows, 0 `MLDatasetVersion` rows**.

### Audit-Session Real Khetri Downloads & Feature Stack (Temporary Verification Session, Independently Verified via `rasterio`)

All rasters below were clipped live to the Khetri AOI `(75.77, 27.98, 75.81, 28.02)` (`17.44 km²`) from **real** external STAC COGs during audit testing:

1. **Copernicus DEM (`earth_search_stac`, `cop-dem-glo-30`, `Copernicus_DSM_COG_10_N28_00_E075_00_DEM`)**
   - Band: `data` | CRS: `EPSG:4326` | Resolution: `0.000278°` (~30m) | Clipped dims: `144 x 72` | Size: `0.0335 MB` | NoData: `None` | Range: `376.98 m` to `566.08 m`
   - Complete/Readable: Yes, independently read with `rasterio`, **but covers only northern half (`lat >= 28.00°N`) of Khetri AOI**.
2. **Sentinel-2 L2A (`earth_search_stac`, `sentinel-2-l2a`, `S2C_43REL_20261112_0_L2A`, acquired `2026-11-12T05:51:17Z`, `5.50%` cloud)**
   - Bands downloaded clipped: `blue` (`0.2396 MB`, `396x446`), `green` (`0.2439 MB`), `red` (`0.2506 MB`), `nir` (`0.2571 MB`), `swir16` (`0.0661 MB`, `198x223`), `swir22` (`0.0660 MB`), `scl` (`0.0040 MB`) | CRS: `EPSG:32643` | NoData: `0.0`.
   - Complete/Readable: Yes, processed into stacked GeoTIFF in Python (`extract_aoi_features`).
3. **Output Feature Stack (`feature_stack.tif`, Data Origin: `real`, Grid: `75 rows x 67 cols`, `EPSG:32643`, Pixel Size: `60.0 m`, Size: `0.1953 MB`, NoData: `-9999.0`)**
   - Independently opened and verified via `rasterio` (17 bands, `completed`):

| Feature Band | Valid Pixels (of 5,025) | Valid % | NoData % | Min | Mean | Max |
|---|---|---|---|---|---|---|
| `elevation_m` | 2,414 | 48.04% | 51.96% | 378.6142 | 426.8701 | 557.7957 |
| `slope_deg` | 2,414 | 48.04% | 51.96% | 0.0605 | 7.8671 | 32.6910 |
| `aspect_deg` | 2,414 | 48.04% | 51.96% | 0.0214 | 165.1158 | 359.7608 |
| `hillshade` | 2,414 | 48.04% | 51.96% | 61.7445 | 175.3381 | 234.2210 |
| `tri` | 2,414 | 48.04% | 51.96% | 0.5141 | 9.8340 | 43.7286 |
| `tpi` | 2,414 | 48.04% | 51.96% | -21.1643 | 0.0388 | 37.6559 |
| `curvature` | 2,414 | 48.04% | 51.96% | -2.3043 | 0.0026 | 3.1244 |
| `drainage_proxy` | 2,414 | 48.04% | 51.96% | 0.0000 | 13.1836 | 224.9673 |
| `ndvi` | 4,720 | 93.93% | 6.07% | -0.0390 | 0.4537 | 0.7697 |
| `ndwi` | 4,720 | 93.93% | 6.07% | -0.7154 | -0.4731 | 0.1324 |
| `ndbi` | 4,720 | 93.93% | 6.07% | -0.2519 | -0.0142 | 0.2450 |
| `s2_iron_oxide_ratio` | 4,720 | 93.93% | 6.07% | 1.0766 | 1.5475 | 2.3441 |
| `s2_ferrous_iron_ratio` | 4,720 | 93.93% | 6.07% | 0.2995 | 0.6770 | 1.2985 |
| `s2_clay_hydroxyl_ratio` | 4,720 | 93.93% | 6.07% | 1.0484 | 1.4803 | 1.9952 |
| `s2_bare_earth_mask` | 4,720 | 93.93% | 6.07% | 0.0000 | 0.0595 | 1.0000 |
| `dist_to_occurrence_m` *(excluded from ML)* | 5,025 | 100.00% | 0.00% | 0.0000 | 1852.5527 | 3768.0764 |
| `geology_unit_index` | 5,025 | 100.00% | 0.00% | 0.0000 | 0.9719 | 1.0000 |

---

## 9. ML Dataset Readiness Assessment (Real Khetri Evaluation)

- **Known Occurrences:** `2` MRDS records (`Khetri Copper Belt`, `Khetri / Kolihan / Chandmari`) collapsing to **`1` unique 60m positive pixel (`positive_count = 1`)**. (`0` GSI/NGDR/IBM files imported in persistent workspace.)
- **Occurrences by Commodity:** Reported as `None` (`UNKNOWN`) due to the `code_list` WFS parser bug (live XML carried `code_list='CU'`).
- **Geographic & Spatial Block Distribution:** `19` total `1000m` UTM spatial blocks (`positive_spatial_blocks = 1` — `0` spatial diversity).
- **Usable Predictors:** `16` features (`dist_to_occurrence_m` automatically excluded). Note: 8 terrain predictors have `51.96%` missing values across southern Khetri, and fault/intrusive/contact predictors are absent.
- **Sample Counts:** `positive_count = 1`, `unlabeled_count = 50`, `explicit_negative_count = 0`, `duplicate_pixel_overlap = 0`, severe class & block scarcity (`1:50`), positive-to-background buffer `250.0 m`.
- **Provenance & Leakage Audit:** `data_origin = "real"`, `excluded_target_leakage_columns = ["dist_to_occurrence_m"]`, `target_leakage_detected = False`, `excluded_non_ml_occurrences = 0`, `random_split_used = False`.
- **Readiness Gate Result:** **FAILS (`quality_passed = False`)** with explicit blocking reasons:
  1. `Insufficient ML-eligible positive occurrences: 1 found inside valid raster coverage (minimum required: 10).`
  2. `Insufficient spatial diversity across blocks: positives span 1 spatial block(s) (minimum required: 3 at 1000m block size).`
- Baseline model training is **not** justified and is correctly **blocked** (`HTTP 422`). Note also that even if terrain predictors are repaired, Khetri cannot support a valid spatial ML baseline from USGS MRDS WFS alone — authorized GSI/NGDR/IBM district occurrence records across multiple distinct deposits/blocks (or a denser benchmark district such as Nevada Walker Lane alongside USGS MRDS commodity parsing fix) are required.

---

## 10. Tests Executed During This Audit

All checks ran cleanly on 2026-11-12 without modifying application logic:

| Check | Command | Exact Observed Result |
|---|---|---|
| **Ruff Lint** | `backend\.venv\Scripts\ruff.exe check backend/app backend/tests` | `All checks passed!` (exit `0`) |
| **Backend Pytest** | `backend\.venv\Scripts\pytest.exe -c backend/pyproject.toml --rootdir=backend backend/tests -v` | **`36 passed, 23 warnings in 16.23s`** (exit `0`; unit, integration, geospatial, Phase 3A/3B/3D tests) |
| **Alembic Migrations** | Temp SQLite `upgrade head` (`0001_initial_phase2` -> `0002_phase3_tables`) -> `downgrade base` -> `upgrade head` | `ALEMBIC_AUDIT_OK` (exit `0`) |
| **Frontend Build & Typecheck** | `npm.cmd --prefix frontend run build` (`tsc --noEmit && vite build`) | `✓ 39 modules transformed.`, **`✓ built in 21.24s`** (exit `0`) |
| **Frontend Vitest** | `frontend\node_modules\.bin\vitest.cmd run --config frontend/vitest.config.ts src/test/workbench.test.tsx` | **`Test Files 1 passed (1)`, `Tests 3 passed (3)`** in `10.08s` (exit `0`) |
| **Live Browser CDP Audit** | Headless Chrome against live `uvicorn` + `vite dev` | **PARTIAL/FAIL**: Steps 1,2,3,5,7,8 passed (`[]` console errors/JS exceptions); Steps 4 & 6 download failed **`HTTP 404`** due to `api.ts` route mismatches |

---

## 11. Defects and Limitations Found

1. **Defect (Critical — UI 404):** [`frontend/src/services/api.ts`](frontend/src/services/api.ts#L81-L89) sends ingestion requests to `POST /api/v1/aois/{aoiId}/ingest`, whereas [`backend/app/api/v1/routes.py`](backend/app/api/v1/routes.py#L269) exposes `POST /api/v1/ingestion/aois/{aoi_id}/run`. Clicking **Ingest Live Macrostrat & USGS MRDS** always fails (`404 Not Found`).
2. **Defect (Critical — UI 404 & Async Mismatch):** [`frontend/src/services/api.ts`](frontend/src/services/api.ts#L136-L142) calls `POST /api/v1/satellite/assets/{assetId}/download?aoi_id=...&run_sync=true`, whereas [`backend/app/api/v1/satellite_routes.py`](backend/app/api/v1/satellite_routes.py#L220) exposes `POST /api/v1/satellite/scenes/{asset_id}/download-clipped` (background task, no `run_sync`). Clicking **Clip & Download Window** always fails (`404 Not Found`).
3. **Defect (Major — Unwired Spectral Feature API/DB):** [`backend/app/api/v1/features_routes.py`](backend/app/api/v1/features_routes.py#L83-L90) and `FeatureExtractRequest` do not pass `sentinel_band_paths` or `aster_band_paths` to `extract_aoi_features`, and `RasterAsset` stores only a single `local_path` string. Multi-band Sentinel-2 and ASTER features cannot be generated through the HTTP API or Web UI.
4. **Defect (Major — Partial DEM Coverage on Tile Borders):** `_find_downloaded_dem_asset` selects only one DEM `RasterAsset` without mosaicking intersecting DEM tiles, causing `51.96%` NoData across southern Khetri (`lat < 28.00°N`).
5. **Defect (Major — Live USGS MRDS Commodity Loss):** [`backend/app/integrations/usgs_mrds.py`](backend/app/integrations/usgs_mrds.py#L124-L128) ignores the `<code_list>` XML attribute returned by `mrds-low` WFS, dropping commodity tags (`CU`) on all live MRDS occurrences.
6. **Defect (Moderate — ASTER Asset Structure Gap):** `compute_aster_features` expects `B01`/`B02`/`B05`–`B07`/`B10`/`B13`, whereas MPC `aster-l1t` ships grouped multi-band `VNIR`/`SWIR`/`TIR` GeoTIFFs; real ASTER scenes remain untested end-to-end.
7. **Limitation (Frontend Sync Verification):** Phase 3C `Vitest` tests mocked `fetch` with optimistic endpoints, hiding the two live `404` route mismatches until this audit tested the live backend + frontend together.
8. **Documentation Errata:** [`PHASE3_COMPLETION_REPORT.md`](PHASE3_COMPLETION_REPORT.md) and [`SATELLITE_DATA_GUIDE.md`](SATELLITE_DATA_GUIDE.md) cited `/quarantined` instead of `/quarantine` and `/satellite/assets/{asset_id}/download` instead of `/satellite/scenes/{asset_id}/download-clipped`.

---

## 12. Recommended Corrections (Before Authorizing Phase 4)

1. **Fix Frontend API Route Mappings & Job Polling (`frontend/src/services/api.ts` & `App.tsx`):**
   - Point `runIngestion` to `/api/v1/ingestion/aois/${aoiId}/run`.
   - Point `downloadRasterAsset` to `/api/v1/satellite/scenes/${assetId}/download-clipped?band_key=...`, handle multi-band downloads cleanly (e.g., `band_metadata.downloaded_bands` map in `RasterAsset`), and poll `/api/v1/satellite/jobs` until completion.
2. **Wire Sentinel-2 & ASTER Band Extraction Into HTTP API:**
   - Support storing/downloading required Sentinel-2 bands (`B02`, `B03`, `B04`, `B08`, `B8A`, `B11`, `B12`, `SCL`) per scene (`local_bands_json` or child band records) and resolve/unpack multi-band `aster-l1t` `VNIR`/`SWIR`/`TIR` files before passing them to `extract_aoi_features`.
3. **Add DEM Tile Mosaicking in `extract_aoi_features`:**
   - Merge all downloaded DEM `RasterAsset`s intersecting the AOI (`rasterio.merge` or iterative grid warping) so cross-tile AOIs like Khetri achieve ~100% DEM coverage instead of `48.04%`.
4. **Fix `USGSMRDSAdapter.parse_gml2` Commodity Parsing:**
   - Parse `attrs.get("code_list")` (and normalize via `COMMODITY_SYNONYMS`) alongside `commod1`/`commod2`/`commod3`.
5. **Add Real End-to-End API Integration Tests Without Route Mocking:**
   - Add automated contract check verifying every URL in `frontend/src/services/api.ts` exists in FastAPI `app.openapi()["paths"]`.
6. **Populate At Least One Genuine ML-Ready Benchmark Dataset in `data/`:**
   - Either import real authorized GSI/NGDR/IBM multi-occurrence Khetri data (`>= 10` valid occurrences across `>= 3` spatial blocks) + verified fault/lithology layers, or prepare a second real benchmark AOI (e.g., Walker Lane, NV with USGS MRDS `code_list` fixed + Macrostrat + complete DEM + cloud-masked Sentinel-2) and confirm `quality_passed = True`.

---

## 13. Phase 4 Readiness Decision

**Decision: C. NOT READY FOR PHASE 4 MODEL DEVELOPMENT**

**Justification:** While the underlying Phase 3 Python geospatial mathematics (`raster_ops`, `spectral`, `terrain`, `proximity`), geological quarantine rules, STAC discovery adapters, Alembic migrations, and Phase 3D anti-leakage / PU readiness gates are well engineered and enforce strict scientific honesty, **five critical gaps prevent Phase 4 authorization**:
1. Core web UI workflows for live geological ingestion and clipped raster download fail with **`HTTP 404` route mismatches** against the FastAPI backend.
2. Sentinel-2 and ASTER spectral feature computation is **unreachable from the REST API and UI**, and live ASTER grouped GeoTIFFs have never been processed.
3. Khetri DEM extraction only achieves **`48.04%` coverage** (`51.96%` NoData) due to single-tile selection across a 1° tile boundary (`N28_00` / `N27_00`).
4. Live USGS MRDS WFS ingestion drops all commodity symbols because `<code_list>` is not parsed.
5. Zero real rasters, occurrences, feature stacks, or ML datasets currently reside in the default database/workspace, and Khetri live open data has **only `1` positive pixel in `1` spatial block** (`quality_passed = False`, readiness gate blocked).

Remediation of the above defects and verification of a real multi-block benchmark dataset should precede Phase 4 prospectivity modeling.
