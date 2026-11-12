# Satellite Data Discovery, Authorization & Windowed Download Guide

> **Scientific Integrity Guardrail:** All satellite and elevation assets ingested in Phase 3 are **AOI-clipped real external data or documented local fixtures**. The platform never fabricates spectral or elevation pixels, and keeps quantitative COG/NetCDF processing strictly separated from pre-rendered visualization tile services.

---

## 1. Supported STAC & Earth Observation Providers

Implemented in [`backend/app/integrations/stac.py`](backend/app/integrations/stac.py) (`STACSearchAdapter`):

| Provider Key | STAC Endpoint | Key Collections | Auth Requirements | Notes |
|---|---|---|---|---|
| `planetary_computer` | `https://planetarycomputer.microsoft.com/api/stac/v1` | `sentinel-2-l2a`, `landsat-c2-l2`, `aster-l1t`, `cop-dem-glo-30` | Search: None; Assets: ephemeral SAS token (`/api/sas/v1/token`) | Automated SAS URL signing supported in adapter when `planetary_computer` is configured. |
| `earth_search` | `https://earth-search.aws.element84.com/v1` | `sentinel-2-l2a`, `sentinel-2-c1-l2a`, `cop-dem-glo-30`, `cop-dem-glo-90` | **None** for search and COG downloads | Open AWS COG access; `cop-dem-glo-30` verified live over Khetri Copper Belt (`Copernicus_DSM_COG_10_N28_00_E075_00_DEM`). |
| `nasa_cmr_stac` | `https://cmr.earthdata.nasa.gov/stac/LPCLOUD` | `EMITL2ARFL_001`, `EMITL2BMIN_001`, `AST_L1T_003` | Search: None; Asset downloads: **NASA Earthdata Login (`requires_auth=True`)** | Download routes inspect `requires_auth` and return `HTTP 424` / actionable guidance when credentials are absent rather than hanging on login HTML pages. |

---

## 2. Canonical Band Alias Mapping (`BAND_ALIASES`)

Because Planetary Computer, Earth Search, Landsat, and ASTER name identical physical bands differently, [`backend/app/integrations/stac.py`](backend/app/integrations/stac.py) normalizes band asset keys via `BAND_ALIASES`:

- `blue`: `["B02", "blue"]`
- `green`: `["B03", "green"]`
- `red`: `["B04", "red"]`
- `nir`: `["B08", "B8A", "nir", "nir08"]`
- `swir1`: `["B11", "swir16"]`
- `swir2`: `["B12", "swir22"]`
- `scl`: `["SCL", "scl"]` (Sentinel-2 Scene Classification Layer)
- `qa_pixel`: `["qa_pixel"]`
- `dem`: `["data", "dem"]`
- `aster_vnir`, `aster_swir`, `aster_tir`, `thermal`

### Nighttime ASTER Caveat
When discovering ASTER L1T scenes (`_infer_collection_defaults`), nighttime scenes contain only `TIR` (`VNIR` and `SWIR` absent) and are explicitly tagged `product_type = "aster_tir_only"` (`resolution_m = 90.0`). Spectral alteration ratios requiring VNIR/SWIR (`>1000nm` daytime reflectance) are **not** computed from TIR-only scenes.

---

## 3. Windowed Clipping, Size Estimation & Storage Guardrails

Downloading full Sentinel-2 tiles (~700 MB–1.2 GB) or global DEM tiles causes bandwidth waste and local disk exhaustion on native Windows workstations.

1. **Pre-download Size Estimate (`estimate_clipped_raster_mb`):** Estimates compressed clipped transfer size from AOI area ($\text{km}^2$), resolution ($\text{m}$), band count, and bytes/pixel (with a `1.25x` header/overview factor) before starting a job.
2. **Windowed HTTP Range Reads (`backend/app/satellite/downloader.py`):**
   - Uses `rasterio.open(...)` + `from_bounds(...)` in dataset CRS (clipped to dataset bounds) so **only tiles intersecting the AOI polygon + buffer** are transferred.
   - Enforces free disk checks (`check_free_disk_space`), max dimension bounds, and post-write byte validation (`validate_file_size` against `max_download_mb`).
   - Writes atomically via temporary files inside managed directories and computes SHA-256 checksums (`checksum_sha256`).
   - Output is written as tiled, `DEFLATE`-compressed GeoTIFF under `data/rasters/`.

---

## 4. Visualization-Only Policy: NASA GIBS

[`backend/app/integrations/nasa_gibs.py`](backend/app/integrations/nasa_gibs.py) serves fast XYZ/WMTS browse tile templates (`VIIRS_SNPP_CorrectedReflectance_TrueColor`, `ASTER_GDEM_Color_Shaded_Relief`) at `/api/v1/satellite/gibs-layers`. Every GIBS layer sets:

```json
"is_quantitative_science_product": false
```

In the interactive GIS workbench (`GISMapCanvas.tsx` and `WorkbenchHeader.tsx`), enabling NASA GIBS renders an explicit **Visualization Only — Not Quantitative Spectral/DEM Data** pill/banner. GIBS RGB/shaded-relief JPEG tiles are **never** accepted as feature-extraction inputs.

---

## 5. Related Endpoints

- `GET /api/v1/satellite/gibs-layers`
- `POST /api/v1/satellite/search`
- `POST /api/v1/satellite/assets/{asset_id}/download`
- `GET /api/v1/satellite/jobs/{job_id}`
- `POST /api/v1/features/rasters/{asset_id}/inspect`
