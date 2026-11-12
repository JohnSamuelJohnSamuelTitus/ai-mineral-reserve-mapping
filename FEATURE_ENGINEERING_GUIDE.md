# Geospatial Feature Engineering & Scientific Rigor Guide

Implemented across [`backend/app/geospatial/`](backend/app/geospatial/):
- `spectral.py` — Multispectral alteration indices & SCL cloud masking
- `terrain.py` — Metric DEM geomorphometric derivatives
- `proximity.py` — Geological unit & structural proximity features (non-fabricating)
- `pipeline.py` — Unified multi-band feature stack extraction + `FeatureManifest` provenance

---

## 1. Spectral Alteration Indices & Cloud Masking (`spectral.py`)

Features are computed **only for bands actually present** in the source raster (`bands_available`). Divide-by-zero, negative reflectance, non-finite values, and `nodata` pixels are safely masked to `DEFAULT_NODATA = -9999.0`.

### Sentinel-2 L2A Cloud Masking
When Sentinel-2 Scene Classification (`SCL`) is provided, `build_sentinel2_valid_mask` excludes classes in `SENTINEL2_MASKED_SCL_CLASSES`:
- `0` No Data, `1` Saturated/Defective, `3` Cloud Shadows, `8` Cloud Medium Probability, `9` Cloud High Probability, `10` Thin Cirrus, `11` Snow/Ice.

### Sentinel-2 Features (`SENTINEL2_FEATURE_REGISTRY`)
- `ndvi`: $(\text{B08} - \text{B04}) / (\text{B08} + \text{B04})$ — Vegetation vigor proxy (useful for vegetation-cover masking / bare-earth validity).
- `ndwi`: $(\text{B03} - \text{B08}) / (\text{B03} + \text{B08})$ — Water / moisture mask.
- `ndbi`: $(\text{B11} - \text{B08}) / (\text{B11} + \text{B08})$ — Built-up / bare surface index.
- `s2_iron_oxide_ratio`: $\text{B04} / \text{B02}$ — Ferric iron oxide / gossan proxy.
- `s2_ferrous_iron_ratio`: $\text{B12} / \text{B8A}$ (falling back to `B08` if `B8A` absent) — Ferrous iron alteration proxy.
- `s2_clay_hydroxyl_ratio`: $\text{B11} / \text{B12}$ — Al-OH / clay / hydroxyl alteration zone proxy (Note: SWIR-wide approximation compared to narrower ASTER SWIR bands).

### ASTER Features (`compute_aster_features`)
Computed strictly when the required VNIR/SWIR bands exist (skipped on TIR-only nighttime scenes):
- Ferric / Gossan / OH-bearing alteration proxies when matching ASTER bands (`Band1`–`Band9`) are supplied.

---

## 2. DEM Terrain Derivatives (`terrain.py`)

Requires a **metric CRS (`EPSG:326xx` / `327xx`)** grid with explicit `pixel_size_x_m` and `pixel_size_y_m`:
- `elevation_m`: Raw DEM elevation in meters (`nodata` masked).
- `slope_deg`: Horn 3x3 finite-difference slope in degrees.
- `aspect_deg`: Compass azimuth in degrees ($[0^\circ, 360^\circ)$, flat masked cleanly).
- `hillshade`: Synthetic illumination surface (useful for visual structural interpretation).
- `tri`: Terrain Ruggedness Index (mean absolute elevation difference across 3x3 neighborhood).
- `tpi`: Topographic Position Index (center elevation minus mean 3x3 neighborhood elevation — highlights ridges vs. valleys/basins).
- `curvature`: Laplacian second-derivative surface curvature proxy.
- `drainage_proxy`: Local convergent-flow / depression accumulation proxy.

---

## 3. Geological Context & Proximity (`proximity.py`)

### Strict Non-Fabrication Policy
> **Critical Rule:** If an AOI has **zero ingested faults/lineaments** or **zero intrusive geological unit geometries**, features such as `dist_to_fault_m` or `dist_to_intrusive_m` are **NOT synthesized or zero-filled**. Instead, `pipeline.py` omits unavailable layers or fills `nodata = -9999.0` with an explicit audit warning in `FeatureManifest.warnings_json`.

When real geometries are present:
- Metric Euclidean distance transforms (in meters) computed on the UTM grid (`dist_to_fault_m`, `dist_to_contact_m`, `dist_to_intrusive_m`, `lithology_code` rasterization).
- **`dist_to_occurrence_m` Leakage Warning:** Although proximity to known occurrences can be inspected for spatial exploratory analysis, `pipeline.py` emits a leakage caution and the ML dataset builder (`dataset_builder.py`) excludes `dist_to_occurrence_m` by default so models do not trivially cheat on target proximity.

---

## 4. `FeatureManifest` & API Usage

`POST /api/v1/features/aois/{aoi_id}/extract` produces:
- Aligned stacked multi-band GeoTIFF (`data/rasters/.../feature_stack.tif`)
- `manifest.json` + database `feature_manifests` record linking `input_scene_ids`, `feature_names`, `grid_rows`, `grid_cols`, `resolution_m`, `target_crs_epsg`, `data_origin`, and `warnings_json`.
- Live verification on Khetri (`EPSG:32643`, 30m COP-30 DEM): generated `45 x 40` grid with all 8 terrain derivatives (`elev min=378.73m, max=546.78m`).
