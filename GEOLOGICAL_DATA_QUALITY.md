# Geological Data Normalization, Quarantine & Quality Reporting Guide

Implemented in [`backend/app/geological/`](backend/app/geological/) (`normalizer.py`, `importers.py`, `quality.py`) and [`backend/app/api/v1/geology_routes.py`](backend/app/api/v1/geology_routes.py).

---

## 1. Authorized Multi-Format Geological Ingestion

Supported file formats (`importers.SUPPORTED_EXTENSIONS`):
- `.csv` (lat/lon + attribute columns)
- `.geojson` / `.json` (GeoJSON `FeatureCollection`)
- `.gpkg` (GeoPackage via GeoPandas)
- `.zip` / `.shp` (Zipped Shapefiles — extracted safely inside managed temporary directories with zip-slip / path traversal checks and auto-reprojected from `input_epsg` to `EPSG:4326`)

Target Indian & global regional sources supported by provider metadata (`DataSource` seed records):
- `ngdr_geodataindia` (GSI / NGDR portal exports)
- `ibm_india` (Indian Bureau of Mines public mineral inventory summaries)
- `bhukosh_gsi` (Geological Survey of India Bhukosh exports)
- `usgs_mrds` (USGS Mineral Resources Data System)
- `macrostrat_v2` (Geologic map units & lithology)
- `mindat_v1` (**Explicitly marked `is_ml_training_allowed = False`**)

---

## 2. Canonical Normalization & Commodity Standardization (`normalizer.py`)

External mineral databases mix spellings, mineral species, and chemical symbols (e.g., `"copper"`, `"cuprum"`, `"Cu"` -> `"Cu"`; `"iron ore"`, `"hematite"`, `"magnetite"` -> `"Fe"`; `"spodumene"`, `"lithium"` -> `"Li"`).

- `COMMODITY_SYNONYMS` maps heterogeneous strings to canonical element/commodity symbols (`Cu`, `Au`, `Ag`, `Fe`, `Zn`, `Pb`, `Ni`, `Co`, `Li`, `U`, `Mn`, `Cr`, `Sn`, `W`, `Mo`, `Al`, `C`, `REE`, `Ti`, `Limestone`, `Diamond`, `P`).
- Multi-value strings delimited by `,`, `;`, or `|` are split cleanly via `parse_commodity_list` into `commodities_all` and `commodity_primary`.

---

## 3. Quarantine & Validation Rules (`occurrence_quarantined`)

Malformed or unusable records are **never** silently fixed with guessed coordinates or inserted as valid training occurrences. Instead, `normalize_occurrence_records` validates every row:
1. Finite coordinates (`lon` in $[-180, 180]$, `lat` in $[-90, 90]$) — non-zero/non-`(0, 0)` ocean-null-island rejection unless explicitly valid, missing coordinate quarantine (`missing_coordinates`, `invalid_coordinates`).
2. Optional non-`EPSG:4326` input reprojection via PyProj (`input_epsg`).
3. AOI spatial containment clipping (`clip_to_aoi=True`) flagging out-of-bounds records cleanly.
4. Intra-batch duplicate detection by `(source_provider_key, external_id)` and near-identical coordinate+name hash.

Rejected rows are written to the **`occurrence_quarantined`** database table preserving `rejection_reason`, `quality_flags`, and the exact `raw_record` JSON for auditability.

---

## 4. Dataset Quality Reports & Exploration Bias Caveat

Every import generates a persisted **`dataset_quality_reports`** entry (`GET /api/v1/geology/aois/{aoi_id}/quality-reports`) containing:
- `total_rows`, `accepted_rows`, `rejected_rows`, `duplicate_rows`
- `missing_coords_count`, `invalid_coords_count`, `missing_commodity_count`
- `completeness_pct` & `commodity_distribution`
- Mandatory scientific warnings (`warnings_json`), including the **exploration/sampling bias caveat**: reported mineral occurrences reflect historical accessibility, outcrop exposure, and survey intensity—absence of a mapped occurrence in an area does **not** prove barren ground.
