# Development Roadmap

This roadmap structures the build into verifiable milestones. Each milestone concludes with automated tests, documentation updates, and a clean Git commit.

---

## Phase 1: Research, Architecture & Foundation *(Completed)*
- Inspected local Windows development environment, audited public/specialist APIs, verified live endpoints, and finalized architecture/schema/roadmap/testing docs.

---

## Phase 2: Native Windows Backend Core, SQLite Abstraction & Real Data Ingestion *(Completed)*
- Implemented native Windows FastAPI + SQLAlchemy 2 + Alembic (`0001_initial_phase2`) + SQLite backend without Docker/WSL, plus PostGIS migration plan and in-memory cache interface.
- Built real adapters (`Macrostrat`, `USGS MRDS`, `Microsoft Planetary Computer` / `Earth Search STAC`, `Open-Meteo Elevation`, `OpenAlex`, `OSM Nominatim`, `India GSI/NGDR/IBM` scaffolding) and initial React + Vite + MapLibre UI.

---

## Phase 3: Geospatial Intelligence, Satellite Processing, Feature Engineering, GIS Workbench & Spatial ML *(Completed)*
- **Phase 3A — Geological Quality & Satellite Discovery:** Canonical mineral occurrence normalization (`COMMODITY_SYNONYMS`), `occurrence_quarantined` & `dataset_quality_reports`, Alembic `0002_phase3_tables`, STAC provider normalization with auth gating & clipped COG estimator, NASA GIBS visualization catalog, and bounded COG downloader.
- **Phase 3B — Raster & Geospatial Feature Engine:** UTM `TargetGridSpec` reprojection (`raster_ops.py`), spectral alteration & SCL cloud masking (`spectral.py`), DEM Horn 3x3 slope/aspect/TPI/TRI/ruggedness (`terrain.py`), geological unit/proximity features with strict non-fabrication policy (`proximity.py`), multi-band feature stack GeoTIFF + `FeatureManifest`, PNG/JSON overlay generation, and live Khetri COP-30 DEM verification.
- **Phase 3C — Interactive GIS Workbench:** Full-bleed MapLibre GL JS workbench with basemap switcher, polygon draw/edit & self-intersection validator (`PUT /api/v1/aois/{id}`), layer visibility/z-order/opacity controls, Inspector / AOI Health / Features & ML tabs, NASA GIBS quantitative guardrail banner, Vitest suite, and headless Chrome CDP live verification.
- **Phase 3D — Spatial ML Dataset Preparation:** Positive-Unlabeled (PU) dataset builder (`known_occurrence` vs `unlabeled_background`, zero auto-invented negatives), deterministic `B_{bx}_{by}` spatial blocking, positive exclusion buffer, automatic exclusion & detection of target leakage (`dist_to_occurrence_m`), Mindat `is_ml_training_allowed=False` enforcement, readiness quality gates, and gated `GroupKFold` Logistic Regression / Random Forest baseline evaluation.

---

## Phase 4: Advanced Prospectivity Modeling, 3D Mode & Target Ranking *(Planned)*
- **M4.1 — XGBoost + SHAP + Target Clustering:** Calibrated prospectivity scoring, Prediction-Area (P-A) curves, uncertainty tiers, SHAP feature attributions, and clustered `exploration_targets`.
- **M4.2 — Multi-Page Routes & CesiumJS 3D Mode:** Dedicated `/satellite`, `/geology`, `/predict`, and `/targets` views with synchronized 3D terrain visualization.
- **M4.3 — PostgreSQL 16 + PostGIS 3.4 Activation:** Enable `ST_AsMVT` vector tiles and Spatial GIST indexing per [POSTGIS_MIGRATION_PLAN.md](POSTGIS_MIGRATION_PLAN.md).

---

## Phase 5: AI Geological Assistant, Automated Reporting & Hardening *(Planned)*
- **M5.1 — AI Geological Assistant:** Grounded tool-calling assistant querying PostGIS target evidence, Macrostrat definitions, and OpenAlex peer-reviewed literature with explicit citations and non-reserve disclaimers.
- **M5.2 — Automated Reporting Module:** Generate downloadable Markdown, PDF, and GeoJSON exploration dossiers containing provenance tables, spatial CV metrics, target rankings, and field-verification recommendations.
- **M5.3 — Optional Advanced Extensions (Gated by Justification):**
  - NASA `EMITL2BMIN_001` hyperspectral mineral validation overlay.
  - PyTorch multi-band spatial patch CNN benchmark (only if multi-AOI training coverage demonstrates measurable spatial-CV lift over XGBoost).
- **M5.4 — Production Hardening:** Security audit, rate-limit verification, full regression test suite, and deployment documentation.

