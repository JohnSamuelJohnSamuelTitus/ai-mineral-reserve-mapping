# Raster Processing, CRS Alignment & Memory Safety Guide

Implemented in [`backend/app/geospatial/raster_ops.py`](backend/app/geospatial/raster_ops.py) and [`backend/app/core/crs.py`](backend/app/core/crs.py).

---

## 1. Metric CRS Strategy (No Degree-Based Distance/Slope Math)

Computing slope ($\partial z / \partial x, \partial z / \partial y$), curvature, raster resolution, or spatial proximity buffers directly in geographic `EPSG:4326` degrees produces severe latitudinal distortion (especially away from the equator) and physically invalid units.

- **Canonical Storage CRS:** Vector AOIs, occurrences, geological units, and raster footprints are stored and queried in `EPSG:4326`.
- **Per-AOI Processing CRS:** `suggest_utm_epsg(lon, lat)` dynamically selects the local metric **WGS 84 UTM zone (`EPSG:326xx` North / `EPSG:327xx` South)**. All raster alignment, terrain derivatives, proximity surfaces, and ML spatial blocks run in that metric UTM CRS.

---

## 2. `TargetGridSpec` Alignment

`build_target_grid_spec(aoi_geometry, resolution_m=...)` computes:
1. Target UTM CRS (`target_epsg`).
2. Buffered/reprojected bounds rounded outward to clean `resolution_m` multiples (`west, south, east, north`).
3. Exact `Affine` transform (`from_origin(west, north, res, res)`), `width`, and `height`.
4. Explicit nodata fill (`DEFAULT_NODATA = -9999.0`).

All input rasters (single-band DEMs, Sentinel-2 multispectral bands, or ASTER VNIR/SWIR) are warped onto this identical `TargetGridSpec` via `reproject_to_grid(...)` (`rasterio.warp.reproject`, resampling chosen per product: `Resampling.bilinear` for continuous reflectance/elevation, `Resampling.nearest` for discrete categorical/SCL masks).

---

## 3. Bounded Memory & Grid Size Protection

To keep native Windows memory usage safe and prevent accidental continent-scale allocations:
- `TargetGridSpec` and `raster_ops.py` enforce grid dimensions strictly capped at `<= 4096 x 4096` pixels (raising `ValueError` when an excessive extent / overly fine resolution exceeds safe limits).
- Output stacked GeoTIFFs (`feature_stack.tif`) are stored as `float32`, tiled (`blockxsize`, `blockysize`), and `DEFLATE`-compressed with explicit `nodata = -9999.0`.
- Valid pixel coverage (`valid_coverage_pct`) is computed per band and overall across the stack so downstream ML readiness gates reject low-coverage or empty extractions.

---

## 4. Visualization Overlay Export (`overlay.json` & `overlay.png`)

Implemented in [`backend/app/api/v1/features_routes.py`](backend/app/api/v1/features_routes.py):
- `GET /api/v1/features/manifests/{manifest_id}/overlay.json`: Returns WGS84 corner coordinates (`[[west, north], [east, north], [east, south], [west, south]]`) and layer metadata compatible with MapLibre GL JS `image` sources.
- `GET /api/v1/features/manifests/{manifest_id}/overlay.png`: Renders a single chosen feature band into an RGBA PNG (using pure-stdlib `zlib`/`struct` compression and perceptually distinct mineral-ramp coloring) with `alpha = 0` on `nodata = -9999.0` pixels so MapLibre drapes only valid AOI data without black/opaque borders.
