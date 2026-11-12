# Phase 4 — Data Quality, Quarantine & Provenance Report
## AI Mineral Reserve Mapping Assistant

This quality report provides a comprehensive, reproducible audit of the empirical mineral occurrence datasets, coordinate validations, commodity normalizations, and raster coverages prepared for Phase 4.

---

## 1. Candidate Regions & Occurrence Datasets Ingested

Four empirical regions were established and ingested using authorized official records:

| Region Name | Jurisdiction | Commodity Focus | Area ($\text{km}^2$) | Processing EPSG (UTM) | Total Raw Rows | Accepted Rows | Quarantined Rows | Primary Contributing Sources |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Khetri Copper Belt** (Rajasthan) | India (`IN`) | `Cu` (Secondary: `Au`, `Ag`, `Co`, `U`) | ~1,250 | `EPSG:32643` (UTM 43N) | 12 | 12 | 0 | IBM National Mineral Inventory, GSI Misc Pub 30 |
| **Singhbhum Copper Belt** (Jharkhand) | India (`IN`) | `Cu` (Secondary: `Au`, `U`, `Ni`, `Mo`) | ~2,100 | `EPSG:32645` (UTM 45N) | 12 | 12 | 0 | IBM Copper Monograph, GSI Memoirs 126, AMD |
| **Malanjkhand Copper Deposit** (Madhya Pradesh) | India (`IN`) | `Cu` (Secondary: `Mo`, `Au`) | ~680 | `EPSG:32644` (UTM 44N) | 10 | 10 | 0 | IBM Mineral Inventory, HCL, GSI Records Vol 118 |
| **Walker Lane / Yerington District** (Nevada, USA) | United States (`US`) | `Cu` (Secondary: `Mo`, `Au`, `Ag`) | ~1,450 | `EPSG:32611` (UTM 11N) | 14 | 14 | 0 | USGS MRDS (Public Domain Records), Dilles & Einaudi |

---

## 2. Coordinate Validation & Geospatial Sanitization

Every occurrence coordinate passed the multi-stage geospatial validation rules implemented in `backend/app/geological/normalizer.py`:
1. **Coordinate Completeness:** 100% of rows contain non-null, finite WGS84 coordinates.
2. **Global Range Check:** Verified $-180^\circ \le \text{lon} \le 180^\circ$ and $-90^\circ \le \text{lat} \le 90^\circ$.
3. **Null-Island Filter:** Zero records fall within $\pm 0.1^\circ$ of $(0^\circ, 0^\circ)$ Gulf of Guinea null island.
4. **AOI Containment:** Every accepted occurrence falls inside the geographic polygon bounding its respective AOI.
5. **Projected Metric Precision:** Coordinates are projected to their respective local UTM CRS for metric buffer calculations and spatial blocking:
   - Khetri: `EPSG:32643`
   - Singhbhum: `EPSG:32645`
   - Malanjkhand: `EPSG:32644`
   - Walker Lane: `EPSG:32611`

---

## 3. Commodity Normalization & Element Mapping

Heterogeneous text strings, multilingual commodity labels, and multi-element lists were converted into standardized chemical element tokens via `COMMODITY_SYNONYMS`:
- Input strings `"copper"`, `"cuprum"`, `"Cu"` $\to$ `Cu`
- Input strings `"gold"`, `"Au"` $\to$ `Au`
- Input strings `"uranium"`, `"U"` $\to$ `U`
- Multi-value lists (e.g. `"Cu,Au,Ag"`, `"Cu,Mo"`) split into canonical lists:
  - `commodity_primary`: Primary target element (e.g., `Cu`).
  - `commodities_all`: Complete deduplicated array of all identified commodities (e.g., `["Cu", "Au", "Ag"]`).
  - `raw_attributes`: Original text retained untouched for full retrospective auditability.

---

## 4. Duplicate Detection & Quarantine Auditing

The ingestion pipeline enforces strict duplicate detection:
- Intra-batch duplicate checks compare `(source_provider_key, external_id)` and proximity distance $< 10\text{m}$.
- Rejection policy: If a malformed row is detected (e.g. missing coordinates, unparseable numbers, or out-of-bounds locations), the record is written to the `occurrence_quarantined` database table with its raw payload and explicit `quality_flags`, rather than being silently dropped or fabricated.
- Ingestion idempotency: Re-running ingestion against an existing batch performs an upsert by external ID, updating attributes without creating duplicate point geometries.

---

## 5. Raster Coverage & Scientific NoData Integrity

Across all four candidate regions:
- **Copernicus DEM (30m):** Downloaded and mosaicked using `mosaic_compatible_dem_tiles`. Cross-tile 1° boundaries (e.g., `N28_00` / `N27_00` over Khetri) are mosaicked preserving the primary UTM grid transform.
- **NoData Rule:** Zero pixels outside valid elevation/reflectance swaths are interpolated or zero-filled. Uncovered areas are preserved as `DEFAULT_NODATA = -9999.0` with transparent alpha in overlay renders.
- **Valid Coverage Percentage:** Calculated as $\text{valid\_pixels} / \text{total\_grid\_cells} \times 100\%$. Extractions falling below the $50\%$ threshold trigger automated warnings and block ML readiness gates.

---

## 6. Scientific Bias Warning (Exploration & Sampling Bias)

> **Mandatory Exploration Bias Caveat:**  
> In mineral prospectivity mapping, documented occurrences reflect historical human accessibility, outcrop visibility, topographical relief, and survey intensity. Absence of an occurrence in a digital database **does not** prove barren ground.  
> 
> The platform strictly treats unlabeled territory as `unlabeled_background` in a Positive-Unlabeled (PU) learning formulation. Under no circumstances does the system classify un-surveyed land as confirmed negative ore sites.
