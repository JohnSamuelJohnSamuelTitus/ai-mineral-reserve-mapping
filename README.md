# AI Mineral Reserve Mapping Assistant

> **Scientific Disclaimer:** This platform performs **mineral prospectivity mapping and exploration target ranking** using open geological, geospatial, satellite, and geophysical proxy datasets. **Prospectivity scores do NOT establish proven or probable mineral reserves, mineral resources, or economic viability** (which require compliant drilling, assaying, and technical reporting under standards such as JORC, NI 43-101, or S-K 1300).

---

## Overview

**AI Mineral Reserve Mapping Assistant** is a modular geospatial intelligence and machine learning platform designed to help geologists and exploration teams:

- Ingest and harmonize verified geological maps, mineral occurrences, terrain/DEM models, and multispectral/hyperspectral satellite imagery.
- Compute alteration indices, structural proximity features, and terrain derivatives across metric analysis grids.
- Train spatially cross-validated prospectivity models (`Scikit-learn`, `XGBoost`, `SHAP`, and optional `PyTorch`) with explicit uncertainty and data-coverage tracking.
- Explore 2D/2.5D (`MapLibre GL JS`) and 3D (`CesiumJS`) geospatial evidence interactively.
- Query a grounded AI geological assistant linked to real database evidence and peer-reviewed literature (`OpenAlex`).
- Export reproducible exploration dossiers (`Markdown`, `PDF`, `GeoJSON`) with full dataset provenance and attribution.

---

## Foundation & Scientific Documentation

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Tech stack, implemented backend/frontend architecture, and UI workbench plan |
| [API_CATALOG.md](API_CATALOG.md) | Audit of `public-apis/public-apis` + specialist APIs, auth, pricing, and licenses |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | SQLite Phase 2/3 schema, Alembic migrations (`0001`, `0002`), and PostgreSQL+PostGIS target model |
| [POSTGIS_MIGRATION_PLAN.md](POSTGIS_MIGRATION_PLAN.md) | Migration strategy from native Windows SQLite to PostgreSQL 16 + PostGIS 3.4 |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Milestone-by-milestone status across Phases 1–5 |
| [TESTING_STRATEGY.md](TESTING_STRATEGY.md) | Backend (`pytest`), geospatial, ML spatial-CV, and frontend (`Vitest`, Chrome CDP) QA strategy |
| [SATELLITE_DATA_GUIDE.md](SATELLITE_DATA_GUIDE.md) | STAC discovery, auth gating, windowed COG clipping, and NASA GIBS visualization boundaries |
| [RASTER_PROCESSING_GUIDE.md](RASTER_PROCESSING_GUIDE.md) | UTM `TargetGridSpec` reprojection, nodata conventions, and bounded memory/disk safeguards |
| [FEATURE_ENGINEERING_GUIDE.md](FEATURE_ENGINEERING_GUIDE.md) | Spectral alteration ratios, SCL masking, DEM terrain derivatives, and leakage/non-fabrication policy |
| [GEOLOGICAL_DATA_QUALITY.md](GEOLOGICAL_DATA_QUALITY.md) | Occurrence normalization, commodity synonym mapping, quarantine, and quality reports |
| [ML_DATASET_GUIDE.md](ML_DATASET_GUIDE.md) | PU labeling, deterministic `B_{bx}_{by}` spatial blocking, `GroupKFold`, and readiness gates |
| [PHASE3_COMPLETION_REPORT.md](PHASE3_COMPLETION_REPORT.md) | Delivered Phase 3 scope, commit history, verification gates, and scientific caveats |
| [.env.example](.env.example) | Environment configuration template (never commit `.env` or real keys) |

---

## Implemented Repository Structure (Phase 3 Complete)

```text
.
├── backend/
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py          # FastAPI entrypoint, CORS, startup seed/setup
│   │   ├── api/v1/          # routes.py, geology_routes.py, satellite_routes.py, features_routes.py, ml_routes.py, schemas.py
│   │   ├── core/            # Config, in-memory cache, UTM/CRS math, structured logging
│   │   ├── db/              # SQLAlchemy 2 models, repositories, Alembic migrations (0001, 0002), seed
│   │   ├── geological/      # Multi-format importer, occurrence normalizer & quarantine, quality reports
│   │   ├── geospatial/      # raster_ops, spectral indices, DEM terrain derivatives, proximity, pipeline
│   │   ├── ingestion/       # AOI-scoped ingestion orchestrator
│   │   ├── integrations/    # Macrostrat, USGS MRDS, STAC (MPC/Earth Search/CMR), NASA GIBS, Elevation, India sources, OpenAlex, Nominatim
│   │   ├── ml/              # PU spatial ML dataset builder & gated GroupKFold baseline evaluator
│   │   ├── satellite/       # Safe AOI-clipped COG downloader & storage validation
│   │   └── storage/         # Safe filename sanitization, path traversal guard & free disk checks
│   └── tests/               # unit/, integration/, geospatial/
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   └── src/
│       ├── components/      # layout/, map/ (MapLibre GL JS + polygon validator), panels/ (Control sidebar & Inspector drawer)
│       ├── services/        # Typed FastAPI API client
│       └── types/           # TypeScript domain contracts
├── ml_experiments/          # Experiment workspace
├── data/                    # Gitignored local storage (mineral_dev.db, raw/, interim/, processed/, rasters/)
└── infra/                   # Optional PostgreSQL/PostGIS reference configs (not used in native Windows Phase 2/3)
```

---

## Development Environment & Running Locally (Native Windows)

Phase 2 and Phase 3 run natively on Windows without Docker, WSL, or Linux dependencies:

- **Python:** `3.12.14` (`backend/.venv`) with FastAPI, SQLAlchemy 2, Alembic, SQLite, GeoPandas, Shapely, PyProj, Rasterio, Scikit-learn, Pandas, NumPy.
- **Node.js / npm:** `v24.22.1` / `11.19.1` (`npm.cmd`) with React 19, TypeScript, Vite 6, MapLibre GL JS 5, Vitest 4.
- **Git:** `2.56.0`

### Start Backend & Frontend
```powershell
# Backend API (runs on http://127.0.0.1:8000)
backend\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --reload --port 8000

# Frontend Workbench (runs on http://127.0.0.1:5173)
npm.cmd --prefix frontend run dev
```

