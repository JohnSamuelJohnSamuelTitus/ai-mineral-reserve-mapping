# SQLite Architecture & PostgreSQL 16 + PostGIS 3.4 Migration Plan

## 1. Why SQLite Is Used in Phase 2 (Windows Native Dev)

To maintain rapid, deterministic development on Windows without Docker Desktop or WSL 2, Phase 2 stores relational, provenance, and bounding-box-indexed geospatial records in **SQLite** (`data/mineral_dev.db`).

### What SQLite + Shapely + PyProj Handles Cleanly Today
- Transactional storage for `areas_of_interest`, `data_sources`, `mineral_occurrences`, `geological_units`, `raster_assets`, and `ingestion_jobs`.
- Full Alembic schema versioning (`upgrade` / `downgrade`).
- Fast SQL pre-filtering via indexed bounding-box columns (`bbox_min_lon`, `bbox_min_lat`, `bbox_max_lon`, `bbox_max_lat`, `lon`, `lat`) followed by exact `Shapely` geometry predicates (`intersects`, `contains`) inside `backend/app/db/repositories.py`.
- Exact WGS84 ellipsoidal area ($\text{km}^2$) and metric UTM EPSG selection via `PyProj`.

### Features That Explicitly Require PostgreSQL + PostGIS (Not Pretended in SQLite)
1. **`GIST` R-Tree Spatial Indexes** over complex multi-polygon geometries (`GEOMETRY(MultiPolygon, 4326)`).
2. **Server-Side Spatial SQL Operations** (`ST_Intersects`, `ST_Distance` on `GEOGRAPHY`, `ST_Transform`, `ST_Buffer`, `ST_Union`).
3. **Direct Mapbox Vector Tile Generation (`ST_AsMVT` / `ST_AsMVTGeom`)** for serving 100k+ prospectivity grid cells and occurrence points directly to MapLibre GL JS without sending giant GeoJSON payloads.
4. **Concurrent Multi-Worker Writes** (Celery/ARQ workers writing grid features and predictions concurrently without SQLite file-lock contention).

---

## 2. How the Codebase Isolates Spatial Logic

- API routes and domain services **never** write raw spatial SQL directly.
- All spatial persistence and containment queries go through repository interfaces in `backend/app/db/repositories.py` (`AOIRepository`, `MineralOccurrenceRepository`, `GeologicalUnitRepository`, `RasterAssetRepository`).
- Geometries are persisted in standard `EPSG:4326` **GeoJSON (`geom_geojson`) and WKT (`geom_wkt`)**, which map 1-to-1 to PostGIS `ST_GeomFromGeoJSON` / `ST_GeomFromText(..., 4326)`.

---

## 3. Step-by-Step Migration Plan to PostgreSQL 16 + PostGIS 3.4

1. **Provision PostGIS:** Start `postgis/postgis:16-3.4` (using [infra/docker-compose.yml](infra/docker-compose.yml) or native PostgreSQL 16 + PostGIS 3.4) and update `.env` with `DATABASE_URL=postgresql+psycopg://...`.
2. **Add Python Drivers:** Add `psycopg[binary]>=3.2` and `geoalchemy2>=0.15` to `backend/pyproject.toml`.
3. **Run Alembic Migration:**
   - Run `alembic upgrade head` against PostgreSQL to create the baseline tables.
   - Add an Alembic migration (`0002_enable_postgis_geometry`) that executes:
     - `CREATE EXTENSION IF NOT EXISTS postgis;`
     - `ALTER TABLE areas_of_interest ADD COLUMN geom geometry(MultiPolygon, 4326);`
     - `UPDATE areas_of_interest SET geom = ST_Multi(ST_SetSRID(ST_GeomFromText(geom_wkt), 4326));`
     - `CREATE INDEX idx_aois_geom ON areas_of_interest USING GIST (geom);`
     - Equivalent `GEOMETRY` + `GIST` upgrades for `mineral_occurrences`, `geological_units`, and `raster_assets`.
4. **Swap Repository Queries:** Implement `PostGISOccurrenceRepository` / `PostGISUnitRepository` using `func.ST_Intersects(...)` behind the same repository protocol, leaving FastAPI routers, external adapters, and tests unchanged.
5. **Migrate Existing SQLite Records:** Export SQLite rows via Python script (preserving UUIDs, `data_origin`, `label_authority`, and `collected_at`) and upsert into PostgreSQL before retiring `mineral_dev.db`.
