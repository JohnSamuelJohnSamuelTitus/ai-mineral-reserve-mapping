# Database & Spatial Storage Design Proposal

## 1. Storage Philosophy

The **AI Mineral Reserve Mapping Assistant** handles two distinct workloads:
1. **Vector, Tabular, Metadata & Provenance Workloads:** Area of Interest (AOI) polygons, mineral occurrences, geological units, target grid cells, model runs, feature vectors, target rankings, audit trails, and literature citations — stored in **PostgreSQL 16 + PostGIS 3.4**.
2. **Large Multi-Band Raster & Cube Workloads:** Cloud-Optimized GeoTIFFs (COGs) from Sentinel-2/Landsat/ASTER/DEMs, spectral index rasters, and continuous prospectivity probability GeoTIFF surfaces — stored in **object/filesystem storage** (local `./data/` in dev; S3/MinIO-compatible object store in production) and **indexed by spatial bounding box, CRS, band metadata, and SHA-256 checksum inside PostGIS**.

> Storing multi-gigabyte multi-band satellite rasters directly as `postgis_raster` BLOBs inside PostgreSQL creates backup bloat and I/O bottlenecks; keeping COGs on disk/object storage with PostGIS metadata indexing is standard cloud-native GIS best practice.

---

## 2. Coordinate Reference Systems (CRS)

- **Canonical Storage CRS (Vector):** `EPSG:4326` (`GEOGRAPHY` or `GEOMETRY(..., 4326)`) for global catalog interoperability, with spatial GIST indexes.
- **Processing & Grid Analysis CRS (Per-AOI):** Dynamically projected to the local **UTM zone (`EPSG:326xx` / `327xx`)** or equal-area projection (`EPSG:6933` / Albers) during raster alignment, terrain derivative computation, distance-to-fault calculation, and regular grid tessellation (so cell areas in $\text{km}^2$ and distances in meters are metric and distortion-free).

---

## 3. Core Schema Design (PostgreSQL + PostGIS)

### 3.1 Provenance & Data Lineage
Every external record, raster scene, and ML prediction carries explicit `data_origin` classification (`real`, `synthetic`, or `demonstration`), source URL/DOI, license tag, and ingestion timestamp.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE data_origin_enum AS ENUM ('real', 'synthetic', 'demonstration');
CREATE TYPE job_status_enum AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');
```

### 3.2 Spatial & Geological Tables

1. **`areas_of_interest` (`aois`)**
   - `id` (`UUID PK`), `name` (`TEXT`), `description` (`TEXT`)
   - `commodity_focus` (`TEXT[]`, e.g., `{'Cu', 'Au', 'Li'}`)
   - `deposit_model` (`TEXT`, e.g., `'porphyry_cu'`, `'orogenic_au'`, `'li_brine'`, `'li_pegmatite'`)
   - `geom` (`GEOMETRY(MultiPolygon, 4326) NOT NULL`) — `GIST` indexed
   - `processing_epsg` (`INTEGER NOT NULL`) — e.g., UTM zone
   - `area_km2` (`DOUBLE PRECISION NOT NULL`)
   - `created_at`, `updated_at` (`TIMESTAMPTZ`)

2. **`data_sources`**
   - `id` (`UUID PK`), `provider_key` (`TEXT UNIQUE`, e.g., `'usgs_mrds'`, `'macrostrat_v2'`, `'mpc_sentinel2'`)
   - `display_name` (`TEXT`), `base_url` (`TEXT`), `license` (`TEXT`), `attribution_text` (`TEXT`)
   - `is_ml_training_allowed` (`BOOLEAN NOT NULL DEFAULT TRUE`) — enforces Mindat-style license guardrails programmatically!
   - `last_health_status` (`TEXT`), `last_checked_at` (`TIMESTAMPTZ`)

3. **`mineral_occurrences`**
   - `id` (`UUID PK`), `source_id` (`UUID FK -> data_sources`), `external_id` (`TEXT`)
   - `name` (`TEXT`), `commodity_primary` (`TEXT`), `commodities_all` (`TEXT[]`)
   - `occurrence_type` (`TEXT`, e.g., `'mine'`, `'deposit'`, `'prospect'`, `'occurrence'`)
   - `deposit_type` (`TEXT`), `geologic_age` (`TEXT`), `host_rock` (`TEXT`)
   - `data_origin` (`data_origin_enum NOT NULL DEFAULT 'real'`)
   - `geom` (`GEOMETRY(Point, 4326) NOT NULL`) — `GIST` indexed
   - `raw_attributes` (`JSONB`), `ingested_at` (`TIMESTAMPTZ`)
   - `UNIQUE (source_id, external_id)`

4. **`geological_units`**
   - `id` (`UUID PK`), `source_id` (`UUID FK -> data_sources`), `external_map_id` (`TEXT`)
   - `unit_name` (`TEXT`), `strat_name` (`TEXT`), `lithology_raw` (`TEXT`), `lithology_class` (`TEXT[]`)
   - `age_min_ma` (`DOUBLE PRECISION`), `age_max_ma` (`DOUBLE PRECISION`), `period_name` (`TEXT`)
   - `data_origin` (`data_origin_enum NOT NULL DEFAULT 'real'`)
   - `geom` (`GEOMETRY(MultiPolygon, 4326) NOT NULL`) — `GIST` indexed
   - `metadata_json` (`JSONB`)

5. **`geological_structures`** *(faults, lineaments, contacts — user-uploaded or derived)*
   - `id` (`UUID PK`), `aoi_id` (`UUID FK -> aois NULLABLE`), `source_id` (`UUID FK -> data_sources`)
   - `structure_type` (`TEXT`, e.g., `'fault'`, `'shear_zone'`, `'fold_axis'`, `'dem_lineament'`)
   - `is_inferred` (`BOOLEAN NOT NULL DEFAULT FALSE`)
   - `geom` (`GEOMETRY(MultiLineString, 4326) NOT NULL`) — `GIST` indexed

### 3.3 Satellite & Raster Asset Index

6. **`raster_assets`**
   - `id` (`UUID PK`), `aoi_id` (`UUID FK -> aois`), `source_id` (`UUID FK -> data_sources`)
   - `stac_collection` (`TEXT`), `stac_item_id` (`TEXT`)
   - `asset_type` (`TEXT`, e.g., `'sentinel2_l2a_cog'`, `'landsat_c2_l2'`, `'cop30_dem'`, `'emit_l2b_min'`, `'spectral_index_iron_oxide'`, `'prospectivity_surface'`)
   - `acquired_at` (`TIMESTAMPTZ`), `cloud_cover_pct` (`DOUBLE PRECISION`)
   - `resolution_m` (`DOUBLE PRECISION`), `crs_epsg` (`INTEGER`)
   - `footprint` (`GEOMETRY(Polygon, 4326) NOT NULL`) — `GIST` indexed
   - `storage_uri` (`TEXT NOT NULL`), `checksum_sha256` (`TEXT`)
   - `band_metadata` (`JSONB`), `data_origin` (`data_origin_enum NOT NULL DEFAULT 'real'`)
   - `created_at` (`TIMESTAMPTZ`)

### 3.4 Prospectivity Grid, ML Runs & Target Ranking

7. **`analysis_grids`** *(Defines a tessellated study grid over an AOI)*
   - `id` (`UUID PK`), `aoi_id` (`UUID FK -> aois`), `cell_size_m` (`INTEGER NOT NULL`)
   - `processing_epsg` (`INTEGER NOT NULL`), `cell_count` (`INTEGER NOT NULL`)
   - `created_at` (`TIMESTAMPTZ`)

8. **`grid_cells`** *(Partitioned or indexed cells containing extracted geospatial/spectral features)*
   - `id` (`BIGSERIAL PK`), `grid_id` (`UUID FK -> analysis_grids`), `cell_index` (`INTEGER`)
   - `geom` (`GEOMETRY(Polygon, 4326) NOT NULL`) — `GIST` indexed
   - `centroid` (`GEOMETRY(Point, 4326) NOT NULL`) — `GIST` indexed
   - `features` (`JSONB NOT NULL`) — e.g. `{"iron_oxide_ratio": 1.42, "clay_hydroxyl_idx": 1.18, "dist_to_fault_m": 420.5, "slope_deg": 14.2, "ndvi_median": 0.12, "lithology_code": "granitoid"}`
   - `data_coverage_pct` (`DOUBLE PRECISION NOT NULL`) — flags cloud/no-data gaps!
   - `has_known_occurrence` (`BOOLEAN NOT NULL DEFAULT FALSE`)

9. **`model_runs`**
   - `id` (`UUID PK`), `grid_id` (`UUID FK -> analysis_grids`)
   - `target_commodity` (`TEXT NOT NULL`), `deposit_model` (`TEXT`)
   - `algorithm` (`TEXT NOT NULL`, e.g., `'xgboost_pu'`, `'random_forest'`, `'logistic_baseline'`, `'cnn_patch'`)
   - `hyperparameters` (`JSONB`), `feature_columns` (`TEXT[]`)
   - `cv_strategy` (`TEXT NOT NULL`, e.g., `'spatial_block_5fold'`)
   - `metrics` (`JSONB NOT NULL`) — e.g. `{"roc_auc_mean": ..., "pr_auc_mean": ..., "capture_efficiency_top10pct": ...}`
   - `training_data_origin` (`data_origin_enum NOT NULL`)
   - `artifact_uri` (`TEXT`), `status` (`job_status_enum`), `created_at` (`TIMESTAMPTZ`)

10. **`prospectivity_predictions`**
    - `id` (`BIGSERIAL PK`), `model_run_id` (`UUID FK -> model_runs`), `cell_id` (`BIGINT FK -> grid_cells`)
    - `prospectivity_score` (`DOUBLE PRECISION NOT NULL`) — calibrated `[0.0, 1.0]` relative score (explicitly NOT ore grade or reserve tonnage)
    - `uncertainty_std` (`DOUBLE PRECISION`) — ensemble/bootstrap spread
    - `confidence_tier` (`TEXT`, `'high' | 'medium' | 'low'`) — combines model uncertainty & feature coverage
    - `shap_top_drivers` (`JSONB`) — top contributing positive/negative geospatial features per cell

11. **`exploration_targets`** *(Clustered high-prospectivity zones ranked for field verification)*
    - `id` (`UUID PK`), `model_run_id` (`UUID FK -> model_runs`), `rank` (`INTEGER NOT NULL`)
    - `target_name` (`TEXT`), `geom` (`GEOMETRY(MultiPolygon, 4326) NOT NULL`) — `GIST` indexed
    - `area_km2` (`DOUBLE PRECISION`), `mean_score` (`DOUBLE PRECISION`), `max_score` (`DOUBLE PRECISION`)
    - `uncertainty_score` (`DOUBLE PRECISION`), `evidence_summary` (`JSONB`)
    - `recommended_next_steps` (`TEXT[]`), `reviewer_status` (`TEXT DEFAULT 'unreviewed'`)

### 3.5 AI Assistant, Reports & Pipeline Audit

12. **`assistant_sessions` & `assistant_messages`**
    - Stores multi-turn conversation history, bound `aoi_id` / `model_run_id`, tool calls executed, and explicit `citations` (`JSONB`: OpenAlex DOIs, Macrostrat `map_id`s, MRDS IDs, model run IDs).

13. **`generated_reports`**
    - `id` (`UUID PK`), `aoi_id` (`UUID FK -> aois`), `model_run_id` (`UUID FK -> model_runs NULLABLE`)
    - `report_type` (`TEXT`), `format` (`TEXT`: `'markdown' | 'pdf' | 'geojson'`)
    - `storage_uri` (`TEXT`), `disclaimer_version` (`TEXT NOT NULL`), `created_at` (`TIMESTAMPTZ`)

14. **`ingestion_jobs`**
    - Tracks async API fetches, STAC scene downloads, spectral processing, and errors (`status`, `provider_key`, `started_at`, `finished_at`, `error_message`, `records_written`).

---

## 4. Indexing & Performance Strategy

- **Spatial Indexes:** `CREATE INDEX idx_<table>_geom ON <table> USING GIST (geom);` on all geometry columns.
- **Composite Indexes:** `(model_run_id, prospectivity_score DESC)` on `prospectivity_predictions` for instant top-$k$ target queries and GeoJSON/MVT streaming.
- **Vector Tiles:** PostGIS `ST_AsMVT` / `ST_AsMVTGeom` serves large `grid_cells` and `mineral_occurrences` layers directly as Mapbox Vector Tiles (`/api/v1/tiles/{layer}/{z}/{x}/{y}.pbf`) so MapLibre GL JS renders 100k+ cells smoothly without crashing the browser with giant GeoJSON payloads.
- **Migrations:** Managed strictly via **Alembic** + SQLAlchemy 2.0 + GeoAlchemy2.

