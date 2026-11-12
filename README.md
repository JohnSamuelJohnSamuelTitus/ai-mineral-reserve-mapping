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

## Phase 1 Foundation Documents

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Tech stack finalization, 9-module architecture, inter-module communication, and 9-page UI/UX plan |
| [API_CATALOG.md](API_CATALOG.md) | Audit of `public-apis/public-apis` + specialist APIs, live HTTP probe results, auth, pricing, and licenses |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | PostgreSQL + PostGIS schema, CRS strategy, COG storage model, and `ST_AsMVT` vector tiles |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Milestone-by-milestone implementation plan from Phase 1 to production hardening |
| [TESTING_STRATEGY.md](TESTING_STRATEGY.md) | Unit, geospatial/CRS, spatial-CV anti-leakage, API contract, and E2E testing strategy |
| [.env.example](.env.example) | Environment configuration template (never commit `.env` or real keys) |

---

## Planned Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routers & Pydantic schemas
│   │   ├── core/            # Config, structured logging, security
│   │   ├── db/              # SQLAlchemy/GeoAlchemy2 models & Alembic migrations
│   │   ├── integrations/    # External API adapters (STAC, Macrostrat, USGS, OpenAlex, DEM)
│   │   ├── ingestion/       # AOI-scoped ingestion orchestrators
│   │   ├── geospatial/      # GDAL/Rasterio spectral indices, DEM derivatives, grid builder
│   │   ├── ml/              # Spatial CV, Scikit-learn/XGBoost/PyTorch, SHAP, target clustering
│   │   ├── assistant/       # Grounded tool-calling AI geological assistant
│   │   └── reporting/       # Markdown, PDF & GeoJSON exploration dossier generator
│   └── tests/               # unit/, integration/, geospatial/
├── frontend/
│   ├── public/
│   └── src/
│       ├── components/      # layout/, map/ (MapLibre), globe/ (CesiumJS), charts/, common/
│       ├── pages/           # 9 workspace views
│       ├── services/        # Typed FastAPI clients
│       ├── store/           # Application & viewport state
│       └── types/           # TypeScript domain contracts
├── ml_experiments/          # Spatial CV benchmarks & experiment configs
├── data/                    # Gitignored local cache (raw/, interim/, processed/)
└── infra/                   # Docker Compose (PostGIS, Redis) & DB initialization
```

---

## Development Environment Status (Verified Phase 1)

- **Python:** `3.12.14` managed via `uv 0.12.17`
- **Node.js / npm:** `v24.22.1` / `11.19.1` (`npm.cmd`)
- **Git:** `2.56.0`
- **Database / Containers:** Local `psql` and `docker` are not yet installed on this workstation (to be provisioned in Phase 2 via Docker Desktop or local PostgreSQL 16 + PostGIS 3.4).

---

## Getting Started (Phase 2+)

*Application source code implementation begins after Phase 1 architecture approval.*

