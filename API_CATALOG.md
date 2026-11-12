# API Discovery & Evaluation Catalog

**Verification Date:** 2026-11-12  
**Primary Discovery Source:** [`public-apis/public-apis`](https://github.com/public-apis/public-apis) (inspected categories: `Environment`, `Geocoding`, `Open Data`, `Science & Math`, `Weather`)  
**Specialist Extension Sources:** USGS MRData / STAC, Microsoft Planetary Computer, Element 84 Earth Search, Copernicus Data Space Ecosystem (CDSE), NASA Earthdata CMR / GIBS, OpenTopography, British Geological Survey (BGS), Geoscience Australia, Mindat, EarthChem / GEOROC.

> **Scientific & Engineering Integrity Note:** Every endpoint, authentication model, license, and HTTP status recorded below was verified directly from official documentation and live HTTP probes during Phase 1. Unavailable, rate-limited, deprecated, or legally restricted services are explicitly flagged.

---

## 1. Master API Evaluation Summary

| API | Provider | Purpose | Authentication | Cost | Status |
|---|---|---|---|---|---|
| **USGS MRDS (WFS & Bulk)** | U.S. Geological Survey | Global mineral occurrences, mines, prospects, commodities | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, WFS 1.0.0 GML2; layers `mrds-high`, `mrds-low`) |
| **Macrostrat v2** | UW-Madison Macrostrat | Geologic map units, lithology, stratigraphy, vector tiles | None | Free (CC BY 4.0) | **Verified Working** (`HTTP 200`, JSON/GeoJSON/TopoJSON) |
| **Microsoft Planetary Computer STAC** | Microsoft | Sentinel-2 L2A, Landsat C2 L2, ASTER, Copernicus DEM COGs | None (search); SAS token via SDK (assets) | Free | **Verified Working** (`HTTP 200`, STAC v1.0 / CQL2) |
| **Element 84 Earth Search STAC** | Element 84 / AWS Open Data | Sentinel-2 L2A/L1C, Sentinel-1, Copernicus DEM 30m/90m COGs | None | Free | **Verified Working** (`HTTP 200`, STAC v1.0.0) |
| **NASA CMR STAC (`LPCLOUD`)** | NASA LP DAAC | EMIT L2B hyperspectral mineralogy, ASTER GDEM/L1T discovery | None (search); Earthdata Login (downloads) | Free (Public Domain) | **Verified Working** (`HTTP 200`, STAC v1.0.0) |
| **NASA GIBS WMTS** | NASA EOSDIS | Global multi-temporal satellite imagery WMTS basemap tiles | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, WMTS 1.0.0 XML) |
| **USGS LandsatLook STAC** | USGS EROS | Landsat Collection 2 Level-1/Level-2 catalog discovery | None (search); ERS / AWS Requester Pays (assets) | Free (data); AWS egress if S3 | **Verified Working** (`HTTP 200`, STAC v1.1.0) |
| **Copernicus Data Space (CDSE)** | ESA / Copernicus | Official Sentinel-1/2/3/5P STAC, OData & Sentinel Hub Process API | OAuth2 (`client_id`/`client_secret`) for downloads/processing | Free tier (10k PU/mo, 12 TB/30d); paid credits above | **Verified Working** (`HTTP 200` on STAC catalog) |
| **OpenTopography API** | NSF OpenTopography | High-res global DEMs (COP30, SRTM, ALOS) & LiDAR catalog | API Key (`apiKey`, free registration) | Free (50–200 calls/day); Plus/Enterprise paid | **Verified Working** (`HTTP 200` on `/otCatalog`) |
| **Open Topo Data** | Open Topo Data (Public / OSS) | Point/transect elevation queries (SRTM30m, ASTER, EU-DEM) | None | Free (public) or self-hosted (MIT) | **Verified Working** (`HTTP 200`, JSON) |
| **Open-Meteo Elevation & Weather** | Open-Meteo | Point elevation (Copernicus GLO-90) & climate/weather data | None (non-commercial); API Key (commercial) | Free (non-commercial CC BY 4.0); \$29+/mo commercial | **Verified Working** (`HTTP 200`, JSON) |
| **Open-Elevation** | Open-Elevation | Point elevation lookup fallback | None | Free (OSS) | **Working (Secondary)** (`HTTP 200`, historically variable uptime) |
| **USGS Earthquake Hazards (FDSN)** | U.S. Geological Survey | Real-time & historical seismic events (fault/tectonic proxy) | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, GeoJSON) |
| **USGS Water Services (NWIS)** | U.S. Geological Survey | Surface water quality & hydrological time series (US) | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, WaterML JSON) |
| **PixelGust Soil API** | PixelGust | SoilGrids 2.0 properties at 6 depths (250m) | None (free tier) | Free tier | **Verified Working** (`HTTP 200`, JSON) |
| **SoilPoint API** | SoilPoint | US soil properties from USDA SSURGO | None | Free | **Docs Reachable** (`HTTP 200` on `/docs`; US-only) |
| **BGS OGC API (BETA)** | British Geological Survey | UK bedrock geology, boreholes, mineral stats, landslides | None | Free (OGL v3.0 attribution required) | **Verified Working** (`HTTP 200`, OGC API Features JSON) |
| **Geoscience Australia EarthResource** | Geoscience Australia | Australian mineral deposits & occurrences (EarthResourceML) | None | Free (CC BY 4.0) | **Verified Working** (`HTTP 200`, WFS 2.0.0) |
| **NASA POWER** | NASA Langley | Global solar & meteorological parameters | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, GeoJSON/JSON) |
| **NASA EONET v3** | NASA EOSDIS | Natural hazard events (volcanic, wildfire, flood) | None | Free (Public Domain) | **Verified Working** (`HTTP 200`, JSON) |
| **OSM Nominatim** | OpenStreetMap | Forward/reverse geocoding for AOI search | Custom `User-Agent` header | Free (ODbL 1.0, max 1 req/s) | **Verified Working** (`HTTP 200`, JSON) |
| **OpenAlex Works API** | OurResearch | Peer-reviewed geological & prospectivity literature search | None (optional free `api_key` for higher quota) | Free (\$0.10/day IP shared; \$1/day w/ free key) | **Verified Working** (`HTTP 200`, JSON, CC0) |
| **Actinia GRASS GIS** | mundialis | Cloud GRASS GIS raster/vector processing | Basic Auth / `apiKey` (demo/account) | OSS / Commercial | **Partial** (`HTTP 200` `/version`; processing gated) |
| **Semantic Scholar Graph API** | Allen Institute (AI2) | Academic paper search & citation graph | Optional `x-api-key` (free application) | Free | **Rate-Limited Unauth** (`HTTP 429` without key) |
| **Mindat API v1** | Hudson Institute of Mineralogy | Mineral species, IMA data & occurrence localities | API Key (manual approval) | Free (non-commercial); Commercial paid | **Restricted / Degraded** (`HTTP 504` on probe; **prohibits ML training** without written permission) |
| **ISRIC SoilGrids v2 REST** | ISRIC World Soil Info | Official SoilGrids 2.0 point/coverage API | None | Free (CC BY 4.0) | **Unavailable / Timeout** (`curl 28` timeout after 12s; use PixelGust or WCS/COG) |
| **GEOROC API v1** | Göttingen Univ. (DIGIS) | Igneous/metamorphic rock geochemistry (GeoJSON) | None | Free (CC BY-SA 4.0) | **Unverified / Doc 404** (`HTTP 404` at `/api/v1/docs/index.html`) |
| **NASA `api.nasa.gov` Earth Imagery** | NASA (`public-apis` listing) | Legacy Landsat 8 Earth imagery/assets endpoint | `apiKey` (`DEMO_KEY`) | Free | **Deprecated / Failing** (`HTTP 503` upstream connect error; officially archived in favor of GIBS/CMR) |

---

## 2. Audit of `public-apis/public-apis` Findings

Inspection of `https://github.com/public-apis/public-apis` across `Environment`, `Geocoding`, `Open Data`, `Science & Math`, and `Weather` revealed:

### Useful Entries Retained from `public-apis`
- **Science & Math:** `Macrostrat`, `USGS Earthquake Hazards Program`, `USGS Water Services`, `OpenAlex`, `Semantic Scholar`, `arXiv`, `DataCite`, `NASA` (only active sub-APIs like EONET/CMR/GIBS—not the deprecated `/planetary/earth/*`).
- **Geocoding:** `Open Topo Data`, `Nominatim`, `Actinia Grass GIS`.
- **Environment & Weather:** `PixelGust Soil`, `SoilPoint`, `Open-Meteo`, `NASA POWER`.

### Gaps in `public-apis` Requiring Specialist Providers
The `public-apis` directory lacks dedicated categories for **mineral resources**, **multispectral/hyperspectral satellite STAC catalogs**, **geological survey WFS services**, and **high-resolution DEMs**. Therefore, specialist providers were researched and verified:
- **Mineral Occurrences:** USGS MRDS (`mrdata.usgs.gov`), Geoscience Australia (`services.ga.gov.au`), BGS (`ogcapi.bgs.ac.uk`), Mindat (`api.mindat.org` — flagged for ML licensing restriction).
- **Satellite & Spectral Data:** Microsoft Planetary Computer STAC, Element 84 Earth Search STAC, Copernicus CDSE STAC, NASA CMR STAC (`LPCLOUD` for **EMIT** hyperspectral mineralogy & **ASTER**), USGS LandsatLook STAC.
- **Terrain & Elevation:** OpenTopography (`/globaldem`), Open-Meteo (`/v1/elevation`).

---

## 3. Detailed Specification of Primary Selected APIs

### 3.1 Mineral Occurrence & Geological Vector/Attribute APIs

#### 1. USGS Mineral Resources Data System (MRDS)
- **Documentation:** `https://mrdata.usgs.gov/mrds/` and `https://mrdata.usgs.gov/catalog/api.php`
- **Verified Endpoints:**
  - WFS 1.0.0: `https://mrdata.usgs.gov/services/mrds?request=GetCapabilities&service=WFS&version=1.0.0`
  - Verified FeatureTypes: `mrds-high`, `mrds-low` (Note: `outputFormat=GML2` supported on WFS 1.0.0; passing `outputformat=geojson` returns `ServiceExceptionReport`).
  - Bulk Ingestion (Recommended for PostGIS seeding): CSV / Shapefile / KML archives on `https://mrdata.usgs.gov/mrds/`.
- **Auth / Cost / License:** No auth; Free; U.S. Government Public Domain.
- **Rate Limits:** Standard USGS fair-use; bulk downloads are preferred over high-frequency WFS bounding-box scraping.
- **Role in Platform:** Primary global baseline dataset of metallic/non-metallic mineral occurrences, deposits, and historical mines (positive labels / known occurrences for prospectivity analysis, with strict spatial bias caveats).

#### 2. Macrostrat API v2
- **Documentation:** `https://macrostrat.org/api`
- **Verified Endpoints:**
  - Base URL: `https://macrostrat.org/api/v2`
  - Geologic map units at coordinate: `GET /geologic_units/map?lat={lat}&lng={lng}`
  - Lithology & stratigraphic definitions: `GET /defs/lithologies`, `GET /defs/intervals`, `GET /columns`, `GET /units`
  - Vector Tiles: `https://tiles.macrostrat.org/carto/{z}/{x}/{y}`
- **Auth / Cost / License:** No auth; Free; **CC BY 4.0** (attribution to Macrostrat and underlying source maps required).
- **Data Formats:** JSON, GeoJSON, TopoJSON, CSV, MVT vector tiles.
- **Role in Platform:** Core lithological, stratigraphic, and bedrock age context for both ML feature engineering and the AI Geological Assistant.

#### 3. Geoscience Australia EarthResource WFS & BGS OGC API
- **Endpoints:**
  - GA WFS 2.0.0: `https://services.ga.gov.au/gis/earthresource/wfs`
  - BGS OGC API Features: `https://ogcapi.bgs.ac.uk/`
- **Auth / Cost / License:** No auth; Free; GA is **CC BY 4.0**, BGS is **OGL v3.0**.
- **Role in Platform:** High-quality regional geological survey testbeds (Australia & UK) for validating models outside North America.

---

### 3.2 Satellite & Hyperspectral / Multispectral Earth Observation APIs

#### 4. Microsoft Planetary Computer STAC API (Primary Multispectral & DEM Raster Source)
- **Documentation:** `https://planetarycomputer.microsoft.com/docs/overview/about`
- **Verified Endpoints:**
  - STAC Root: `https://planetarycomputer.microsoft.com/api/stac/v1`
  - Search: `POST https://planetarycomputer.microsoft.com/api/stac/v1/search`
  - Key Collections: `sentinel-2-l2a` (VNIR/SWIR 10m–20m), `landsat-c2-l2` (VNIR/SWIR/TIR 30m), `aster-l1t` (SWIR/TIR), `cop-dem-glo-30` (30m DEM).
- **Auth / Cost / License:** No auth for STAC search; asset Cloud-Optimized GeoTIFF (COG) URLs require ephemeral SAS signing via `planetary-computer` Python SDK (`/api/sas/v1/token`). Free. Underlying data is open (Copernicus / USGS Public Domain).
- **Rate Limits:** Shared public service; no fixed RPS cap, but aggressive concurrency triggers `503`/`504`. Must use exponential backoff and bounded concurrency.
- **Role in Platform:** Primary backend source for COG window reads (band ratios for iron oxides, clays/hydroxyls, carbonates, NDVI/vegetation masking) via `rasterio`/`rioxarray`.

#### 5. Element 84 Earth Search STAC API (Secondary / Redundant STAC Source)
- **Verified Endpoint:** `https://earth-search.aws.element84.com/v1`
- **Auth / Cost / License:** No auth; Free best-effort public STAC; underlying Sentinel-2 COGs on AWS Open Data (Copernicus open license).
- **Role in Platform:** Failover STAC provider when Planetary Computer experiences `503` throttling.

#### 6. NASA CMR-STAC (`LPCLOUD`) — EMIT Imaging Spectroscopy & ASTER
- **Verified Endpoint:** `https://cmr.earthdata.nasa.gov/stac/LPCLOUD`
- **Key Collections:** `EMITL2ARFL_001` (surface reflectance), `EMITL2BMIN_001` (mineral identification & band depth at 60m!), `AST_L1T_003`.
- **Auth / Cost / License:** Search is unauthenticated; downloading NetCDF/COG assets requires a free **NASA Earthdata Login (EDL)** account (`earthaccess` / bearer token / `_netrc`). Free, Public Domain.
- **Role in Platform:** Unique mineral spectroscopy validation layer (EMIT directly maps surface hematite, goethite, kaolinite, alunite, illite, calcite, dolomite in arid/exposed terrains).

#### 7. Copernicus Data Space Ecosystem (CDSE) & NASA GIBS WMTS
- **CDSE STAC:** `https://catalogue.dataspace.copernicus.eu/stac` (OAuth2 free tier: 10,000 Processing Units/month, 12 TB/30-day download quota).
- **NASA GIBS WMTS:** `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml` (no auth; fast tile overlays for frontend MapLibre/Cesium).

---

### 3.3 Terrain, Elevation, Soil, Tectonics & Literature APIs

#### 8. OpenTopography API & Open Topo Data & Open-Meteo Elevation
- **OpenTopography:** `https://portal.opentopography.org/API/globaldem` (COP30, SRTM, ALOS) — requires free `apiKey`; 50 calls/day (non-academic) or 200 calls/day (academic), area caps per request (`450,000 km²` at 30m).
- **Open Topo Data:** `https://api.opentopodata.org/v1/srtm30m` — no auth; 100 locations/req, 1 req/s, 1,000 calls/day; MIT self-hostable.
- **Open-Meteo Elevation:** `https://api.open-meteo.com/v1/elevation` — no auth for non-commercial (CC BY 4.0, 10,000 calls/day); commercial plans start at ~\$29/mo.

#### 9. USGS Earthquake FDSN & PixelGust Soil
- **USGS Earthquake FDSN:** `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson` — no auth, free, public domain; used for regional tectonic/seismicity density context.
- **PixelGust Soil:** `https://pixelgust.com/v1/soil?lat={lat}&lon={lon}` — verified `HTTP 200`, wraps SoilGrids 2.0 (250m, 6 depths) reliably while ISRIC's direct `rest.isric.org` timed out.

#### 10. OpenAlex Works API & OSM Nominatim
- **OpenAlex:** `https://api.openalex.org/works` — free CC0 scholarly metadata; adding a free `OPENALEX_API_KEY` raises daily budget from shared IP \$0.10/day to \$1.00/day. Grounds the AI Geological Assistant in real peer-reviewed literature.
- **OSM Nominatim:** `https://nominatim.openstreetmap.org/search` — ODbL 1.0, requires custom `User-Agent`, max 1 req/s; geocodes region/deposit names for AOI selection.

---

## 4. Deprecated, Unavailable, or Legally Restricted Services (Do Not Depend On)

1. **`api.nasa.gov/planetary/earth/*` (NASA Earth Imagery/Assets):** Listed in `public-apis`, but officially archived/deprecated and returns `HTTP 503` upstream connect failures. Replaced with Planetary Computer STAC / NASA GIBS / NASA CMR.
2. **Mindat API v1 (`api.mindat.org/v1/`):** Returned `HTTP 504` gateway timeouts on probe, requires manual non-commercial approval, and **terms of service explicitly prohibit using Mindat data to train or fine-tune AI/ML models without prior written permission**. Excluded from ML training pipelines; optionally supported only as a user-supplied, non-ML reference lookup if explicitly licensed.
3. **ISRIC SoilGrids REST (`rest.isric.org`):** Timed out after 12s (`curl exit 28`). Use PixelGust Soil API (cached) or direct SoilGrids WCS/GeoTIFF tiles instead.
4. **Semantic Scholar Unauthenticated API:** Returned `HTTP 429` immediately on shared IP; requires API key application. Use OpenAlex as primary literature API.
5. **GEOROC API Docs (`georoc.eu/api/v1/docs/index.html`):** Returned `HTTP 404` at the documented path; defer geochemical integration until verified or use bulk EarthChem Library datasets with explicit DOI provenance.

