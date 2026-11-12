# Development Roadmap

This roadmap structures the build into verifiable milestones. Each milestone concludes with automated tests, documentation updates, and a clean Git commit.

---

## Phase 1: Research, Architecture & Foundation *(Current Phase)*
- Inspect local development environment (`uv`/Python 3.12, Node 24, Git).
- Audit `public-apis/public-apis` and specialist geological/EO APIs; run live endpoint verification probes.
- Finalize technology stack, modular architecture, PostGIS schema, UI/UX plan, testing strategy, and risk register.
- Initialize clean repository structure, `.gitignore`, `.env.example`, and core documentation.
- **Exit Gate:** User review and explicit approval of Phase 1 deliverables.

---

## Phase 2: Backend Core, PostGIS & Real Data Ingestion (MVP Foundation)
- **M2.1 — Infrastructure & DB Setup:** Docker Compose (`postgres:16` + `postgis:3.4`, Redis), Alembic migrations for all core tables, FastAPI app skeleton with structured logging and `/health` endpoint.
- **M2.2 — External API Adapters:** Implement typed async clients with retry/backoff and caching for:
  - `Macrostrat v2` (lithology/geology lookup & map units)
  - `USGS MRDS` (bulk loader + WFS fallback)
  - `Microsoft Planetary Computer STAC` + `Element 84 Earth Search` fallback
  - `Open Topo Data` / `Open-Meteo Elevation` / `OpenTopography`
  - `OSM Nominatim` & `OpenAlex`
- **M2.3 — AOI & Ingestion APIs:** CRUD for Areas of Interest (`/api/v1/aois`), async ingestion orchestration, `data_sources` health check endpoint, and PostGIS `ST_AsMVT` vector tile endpoint.
- **Exit Gate:** Real mineral occurrences, geology polygons, and STAC metadata ingested and queryable for a real test AOI (e.g., Nevada Walker Lane or Sudbury Basin) with unit & integration tests passing.

---

## Phase 3: Geospatial Processing Engine & Baseline ML Prospectivity
- **M3.1 — Raster & Terrain Engine:** Windowed COG reading (`rasterio`/`rioxarray`), cloud masking (SCL band), mineral alteration indices (Iron Oxide, Clay/Hydroxyl, Ferrous, NDVI bare-earth mask), and DEM terrain derivatives (slope, aspect, TPI).
- **M3.2 — Grid Feature Matrix:** UTM grid tessellation over AOI, zonal statistics per cell, distance-to-fault/contact computation, and missingness (`data_coverage_pct`) tracking.
- **M3.3 — Prospectivity ML Engine:**
  - Spatial block cross-validation pipeline (`scikit-learn` Logistic Regression baseline + `XGBoost` classifier with PU/class-imbalance handling).
  - Calibration, Prediction-Area (P-A) curve, ensemble/bootstrap uncertainty estimation, and `SHAP` feature attribution.
  - Spatial clustering of top-scoring cells into ranked `exploration_targets`.
- **Exit Gate:** End-to-end reproducible prospectivity run producing calibrated scores, uncertainty tiers, SHAP explanations, and GeoTIFF/PostGIS outputs verified against spatial CV tests.

---

## Phase 4: Frontend GIS Workbench & 3D Visualization
- **M4.1 — Shell & Navigation:** React + TypeScript + Tailwind CSS dark scientific workbench layout across all 9 planned routes.
- **M4.2 — MapLibre GL JS Exploration Workbench:** Vector tile rendering (`MVT`), COG/spectral tile overlays, interactive layer controls, cell evidence inspector, and AOI drawing tool.
- **M4.3 — Interactive Dashboards:** Satellite STAC browser, Geological Data Explorer, ML Prediction Runner & SHAP charts, and Exploration Target Ranking workspace.
- **M4.4 — CesiumJS 3D Mode:** Synchronized 3D terrain & prospectivity/occurrence visualization for selected targets.
- **Exit Gate:** Frontend build, component tests, and Playwright E2E smoke tests covering AOI creation, map layer toggling, prediction inspection, and target ranking.

---

## Phase 5: AI Geological Assistant, Automated Reporting & Hardening
- **M5.1 — AI Geological Assistant:** Grounded tool-calling assistant querying PostGIS target evidence, Macrostrat definitions, and OpenAlex peer-reviewed literature with explicit citations and non-reserve disclaimers.
- **M5.2 — Automated Reporting Module:** Generate downloadable Markdown, PDF, and GeoJSON exploration dossiers containing provenance tables, spatial CV metrics, target rankings, and field-verification recommendations.
- **M5.3 — Optional Advanced Extensions (Gated by Justification):**
  - NASA `EMITL2BMIN_001` hyperspectral mineral validation overlay.
  - PyTorch multi-band spatial patch CNN benchmark (only if multi-AOI training coverage demonstrates measurable spatial-CV lift over XGBoost).
- **M5.4 — Production Hardening:** Security audit, rate-limit verification, full regression test suite, and deployment documentation.

