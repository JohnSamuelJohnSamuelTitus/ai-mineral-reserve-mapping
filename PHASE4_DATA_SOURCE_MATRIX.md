# Phase 4 — Data-Source Verification Matrix
## AI Mineral Reserve Mapping Assistant

This matrix documents the verification, authentication, licensing, format, and scientific ML suitability of all prospective geological, elevation, and remote-sensing data sources evaluated for Phase 4 dataset development.

---

## 1. India-Focused Geological Data Sources

| Source / Provider Key | Organization & Base URL | Access / Protocol | Auth Requirements | Available Geographic Coverage | Data Format | License & Usage Terms | ML Training Allowed? | Actual Testing Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`ngdr_geodataindia`** | Geological Survey of India (GSI) / Ministry of Mines<br>`https://geodataindia.gov.in/` | Web Portal / WMS / OGC GeoServices | Web portal requires registration; OGC endpoints accessible via session tokens. | Pan-India (1:50k & 1:2M geological maps, baseline geophysical surveys, mineral baseline data). | GeoJSON, Shapefile, WMS raster tiles, tabular exports. | **GODL-India** (Government Open Data License) / NDSAP. Attribution mandatory. | **Yes** (Non-commercial research & spatial modeling permitted under GODL). | **Tested.** Public portal HTTP 200; official occurrence records ingested from published GSI Miscellaneous Publication 30 & District Resource Maps. |
| **`ibm_india`** | Indian Bureau of Mines (IBM)<br>`https://ibm.gov.in/` | Web Portal / PDF / Tabular Releases | Public web portal; no direct programmatic REST API for National Mineral Inventory. | All mining states in India (detailed district-wise lease boundaries, reserve/resource inventory). | Tabular data (PDF / Excel monographs, Indian Minerals Yearbook). | **GODL-India** / Ministry of Mines Terms. Open for research with proper citation. | **Yes** (Public statistical inventory summaries usable for occurrence grounding). | **Tested.** Occurrence coordinates and production history digitized from IBM National Mineral Inventory (Copper Ore monograph). |
| **`data_gov_in`** | Open Government Data Platform India<br>`https://api.data.gov.in/` | REST API (`/resource/{id}`) | Free API key required (registered on data.gov.in). | National / State level mineral statistics and lease tallies. | JSON, XML, CSV. | **GODL-India**. | **Yes**. | **Tested.** Validated endpoint structure. Provides aggregated statistics rather than high-resolution deposit centroids. |
| **`bhukosh_gsi`** | GSI Bhukosh Spatial Data Gateway<br>`https://bhukosh.gsi.gov.in/` | ArcIMS / GeoServer OGC WMS/WFS | Web interface open; raw WFS endpoints require VPN or dynamic ASP.NET session cookies. | Pan-India mineral occurrence layers, geochronology, aeromagnetic grids. | WMS GetMap / GML. | **GODL-India** / GSI Policy. | **Yes**. | **Investigated.** Web portal operational; automated scraping blocked by CAPTCHA/session tokens. Data ingested via authorized offline exports. |

---

## 2. International Geological & Remote Sensing Providers

| Source / Provider Key | Organization & Base URL | Access / Protocol | Auth Requirements | Available Geographic Coverage | Data Format | License & Usage Terms | ML Training Allowed? | Actual Testing Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`usgs_mrds`** | U.S. Geological Survey (USGS)<br>`https://mrdata.usgs.gov/services/mrds` | WFS 1.0.0 (`GetFeature`), REST, Shapefile/CSV bulk | **None** (Open public domain service). | Global coverage (dense in US/North America; sparse global historic records). | GML2 XML, GeoJSON, CSV. | **U.S. Public Domain**. Free reuse without restriction. | **Yes**. | **Tested & Verified.** WFS GML2 parser tested against Walker Lane, Nevada and Khetri queries; `code_list` parsing and case normalization active. |
| **`macrostrat_v2`** | Macrostrat (UW-Madison)<br>`https://macrostrat.org/api/v2` | Programmatic REST API (`/geologic_units/map`) | **None** (Open scientific API). | Global bedrock lithology, stratigraphy, map polygons (scale-dependent). | JSON / GeoJSON. | **CC BY 4.0** with citation. | **Yes**. | **Tested.** Intersecting lithology and chronostratigraphic units queryable by WGS84 bounding box. |
| **`copernicus_dem`** / **`earth_search_stac`** | European Space Agency (ESA) / Element 84<br>`https://earth-search.aws.element84.com/v1` | STAC API v1.0.0 (`cop-dem-glo-30`) | **None** for search and AWS S3 COG downloads. | Global landmass ($\pm 85^\circ$ latitude) at 30m resolution. | Cloud-Optimized GeoTIFF (COG), 32-bit float elevation (meters). | **Copernicus Open Access / DEM License**. Free & open. | **Yes**. | **Tested & Verified.** Successfully queried and clipped intersecting 1° tiles (e.g. `Copernicus_DSM_COG_10_N28_00_E075_00_DEM`). |
| **`mpc_stac`** | Microsoft Planetary Computer<br>`https://planetarycomputer.microsoft.com/api/stac/v1` | STAC API v1.0.0 | Search is open; COG downloads require signed SAS tokens (`/api/sas/v1/token`). | Global: Sentinel-2 L2A, Landsat C2 L2, ASTER L1T, COP30 DEM. | Cloud-Optimized GeoTIFF (COG), JSON. | Varies by collection (Copernicus / USGS / NASA open). | **Yes**. | **Tested.** SAS query parameter stripping active; multi-band scene discovery verified. |
| **`nasa_cmr_stac`** | NASA LP DAAC (CMR-STAC)<br>`https://cmr.earthdata.nasa.gov/stac/LPCLOUD` | STAC API (`AST_L1T_003`, `EMITL2ARFL_001`) | Search is open; asset download requires **NASA Earthdata Login token (`requires_auth=True`)**. | Global on-demand ASTER collections and EMIT orbital tracks. | NetCDF4 / HDF5 / COG. | NASA Open Data Policy (Public Domain). | **Yes**. | **Tested.** Route inspection blocks unauthorized download attempts with HTTP 403/424 guidance when EDL token is missing. |
| **`nasa_gibs`** | NASA EOSDIS Global Imagery Browse Services<br>`https://gibs.earthdata.nasa.gov/wmts` | WMTS / XYZ REST tiles (`epsg3857/best`) | **None** (Open browse service). | Global daily RGB reflectance and shaded relief. | 256x256 8-bit JPEG/PNG tiles. | NASA Public Domain. | **NO (Visualization ONLY)** (`is_ml_training_allowed=False`). | **Tested & Blocked from ML.** Enforced in `pipeline.py` and GIS workbench; strictly excluded from quantitative feature extraction. |
| **`mindat_v1`** | Hudson Institute of Mineralogy<br>`https://api.mindat.org/v1/` | REST API | API key required. | Global amateur & mineralogical occurrences. | JSON. | **Strictly Proprietary**: Mindat Terms of Use forbid machine learning, AI training, and commercial scraping without written agreement. | **STRICTLY PROHIBITED WITHOUT WRITTEN PERMISSION.** | **Blocked by Architecture.** `is_ml_training_allowed = False` enforced in seed records and `dataset_builder.py`. Excluded from ML training pipelines. |

---

## 3. License & Provenance Summary

- **Real Empirical Datasets:** Derived solely from **GODL-India**, **USGS Public Domain**, **Copernicus Open Access**, and **CC BY 4.0** (Macrostrat).
- **Prohibited Data:** Mindat (`mindat_v1`) is systematically quarantined and prevented from feeding the ML dataset builder.
- **Visualization-Only Data:** NASA GIBS tiles are restricted to UI visual backdrop inspection and never converted into model features.
