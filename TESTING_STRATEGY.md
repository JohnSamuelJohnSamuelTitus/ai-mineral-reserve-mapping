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

- **Type Checking & Build Verification:** `vite build` / TypeScript bundling (`npm.cmd --prefix frontend run build`).
- **Component & Geometry Tests (`Vitest` + `React Testing Library`):**
  - Located in `frontend/src/test/workbench.test.tsx`.
  - Covers self-intersection polygon geometry validation (`polygonGeometry.ts`), workbench rendering with mocked API payloads, basemap & NASA GIBS quantitative-warning pill, layer toggle state, Inspector / AOI Health / Features & ML tabs.
- **Live Browser Verification (Headless Chrome DevTools Protocol / CDP):**
  - Verifies live `uvicorn` + `vite` integration with zero console errors or uncaught JS exceptions, real tile/overlay rendering, API roundtrips, and visual screenshot review.

---

## 4. Phase 3 Backend Test Organization (`pytest`)

- `backend/tests/unit/`: Config, CRS utilities, Phase 2 core schemas.
- `backend/tests/integration/`: FastAPI SQLite endpoint tests (`/aois`, `/ingestion`, `/sources`, `/literature`, `/geocode`).
- `backend/tests/geospatial/`:
  - `test_phase3a_ingestion_and_stac.py`: Occurrence normalization, commodity mapping, quarantine, quality reports, STAC auth gating, size limits.
  - `test_phase3b_features.py`: UTM grid spec alignment, Sentinel-2/ASTER spectral ratios, SCL masking, DEM derivatives, proximity non-fabrication, feature stack extraction & PNG overlay rendering.
  - `test_phase3d_ml_dataset.py`: PU labeling, deterministic spatial block reproducibility, Mindat exclusion, `dist_to_occurrence_m` leakage detection, readiness blocking (`HTTP 422`), and `GroupKFold` baseline evaluation.
- Static lint check via `backend\.venv\Scripts\ruff.exe check backend/app backend/tests`.

