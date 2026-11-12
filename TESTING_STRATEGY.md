# Testing & Quality Assurance Strategy

## 1. Testing Principles

- **Deterministic Core, Mocked Externals:** Unit and standard CI integration tests MUST NOT depend on live external APIs (STAC, Macrostrat, USGS, OpenAlex); external adapters are tested against recorded real-response fixtures (`respx` / `pytest-httpx`) plus optional `@pytest.mark.live_api` contract smoke tests.
- **No Fabricated Scientific Assertions:** ML tests verify mathematical invariants (calibration bounds, spatial-block isolation, non-leakage, reproducibility under fixed seeds) using documented synthetic benchmarks or real public test fixtures clearly tagged with `data_origin`.
- **Geospatial Correctness:** CRS transformations, raster alignment, spectral band ratios, and metric area/distance calculations are explicitly asserted against known analytical values.

---

## 2. Backend & Geospatial Test Layers (`pytest`)

| Layer | Scope | Tools | Key Assertions |
|---|---|---|---|
| **Unit Tests (`backend/tests/unit/`)** | Config, Pydantic schemas, spectral band math, rate limiters, retry/backoff, license guardrails | `pytest`, `numpy.testing` | Band ratios (e.g., Iron Oxide $\text{B4}/\text{B2}$, Clay $\text{B11}/\text{B12}$) handle divide-by-zero/NaN/nodata masks; `is_ml_training_allowed=False` sources are rejected by ML training pipeline; AOI size guardrails reject oversized polygons. |
| **External Adapter Contract Tests** | Macrostrat, USGS MRDS GML2 parser, STAC search, Elevation, OpenAlex | `pytest`, `respx` / `httpx.MockTransport` | HTTP `429`/`503`/`504` trigger bounded exponential backoff and failover; malformed XML/JSON raises typed adapter errors instead of silent corrupt records. |
| **Geospatial & PostGIS Tests (`backend/tests/geospatial/`)** | UTM zone selection, raster clipping/reprojection, zonal stats, `ST_AsMVT` vector tile generation | `pytest`, `rasterio`, `geopandas`, PostGIS test DB | Area in $\text{km}^2$ matches analytical expectation; raster-to-grid alignment preserves CRS & nodata coverage %; `ST_AsMVT` returns valid non-empty protobuf bytes for populated tiles. |
| **ML & Spatial CV Tests** | Spatial block splitting, PU weighting, XGBoost/Sklearn training, SHAP, target clustering | `pytest`, `scikit-learn`, `xgboost`, `shap` | **Zero spatial overlap** between train and validation folds (buffered spatial blocks); `prospectivity_score` bounded in `[0, 1]`; deterministic outputs with fixed random seed; Shapley values sum to model margin within tolerance. |
| **API Integration Tests (`backend/tests/integration/`)** | FastAPI endpoints (`/aois`, `/ingestion`, `/ml`, `/targets`, `/reports`, `/assistant`) | `pytest`, `FastAPI TestClient` / `httpx.AsyncClient` | Status codes, OpenAPI schema conformance, `data_origin` propagation, non-reserve disclaimer present in all generated reports. |

---

## 3. Frontend Test Layers

- **Type Checking & Linting:** `tsc --noEmit`, `eslint`, `prettier --check`.
- **Component & Store Tests (`Vitest` + `React Testing Library`):**
  - Data-origin badge rendering (`REAL`, `SYNTHETIC`, `DEMO`).
  - Layer visibility/opacity state synchronization.
  - Target ranking table sorting/filtering and error-banner rendering when backend returns degraded API status.
- **End-to-End Smoke Tests (`Playwright`):**
  - Load Overview Dashboard $\rightarrow$ open Exploration Map $\rightarrow$ select/create AOI $\rightarrow$ inspect geological unit & target ranking drawer $\rightarrow$ export report.

---

## 4. Static Analysis, Security & CI Gates

- **Python:** `ruff` (lint + format), `mypy` (strict typing on `app/`), `pip-audit` / `uv` lockfile checks.
- **Secrets Prevention:** Pre-commit / CI scan ensuring `.env`, private keys, and real API credentials are never committed.
- **CI Pipeline (GitHub Actions):** Runs `ruff`, `mypy`, `pytest` (unit + integration with PostGIS service container), `tsc`, `vitest`, and `vite build` on every pull request.

