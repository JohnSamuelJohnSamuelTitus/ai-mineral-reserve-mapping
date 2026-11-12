"""Phase 3E scientific data pipeline remediation regression tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AreaOfInterest
from app.geospatial.aster import (
    ASTER_BAND_SPECS,
    resolve_aster_grouped_bands,
)
from app.geospatial.pipeline import extract_aoi_features
from app.geospatial.raster_ops import mosaic_compatible_dem_tiles
from app.integrations.usgs_mrds import USGSMRDSAdapter
from app.storage.manager import sanitize_url_for_storage, scrub_secrets_from_text


def _create_khetri_test_aoi(db: Session) -> AreaOfInterest:
    aoi = AreaOfInterest(
        name="Khetri Boundary Test",
        jurisdiction="IN",
        commodity_focus=["Cu"],
        geom_geojson='{"type":"Polygon","coordinates":[[[75.77,27.98],[75.82,27.98],[75.82,28.03],[75.77,28.03],[75.77,27.98]]]}',
        geom_wkt="POLYGON ((75.77 27.98, 75.82 27.98, 75.82 28.03, 75.77 28.03, 75.77 27.98))",
        bbox_min_lon=75.77,
        bbox_min_lat=27.98,
        bbox_max_lon=75.82,
        bbox_max_lat=28.03,
        centroid_lon=75.795,
        centroid_lat=28.005,
        area_km2=27.2,
        processing_epsg=32643,
    )
    db.add(aoi)
    db.commit()
    db.refresh(aoi)
    return aoi


def _write_geotiff(
    path: Path,
    arrays: list[np.ndarray],
    *,
    bounds: tuple[float, float, float, float],
    crs: str = "EPSG:4326",
    nodata: float | None = -9999.0,
    descriptions: tuple[str, ...] | None = None,
) -> Path:
    h, w = arrays[0].shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=len(arrays),
        dtype=str(arrays[0].dtype),
        crs=crs,
        transform=from_bounds(*bounds, w, h),
        nodata=nodata,
    ) as dst:
        for i, arr in enumerate(arrays, start=1):
            dst.write(arr, i)
        if descriptions:
            dst.descriptions = descriptions
    return path


def test_usgs_mrds_code_list_parsing_single_multi_empty_and_unknown() -> None:
    """Remediation E: Live MRDS GML uses space-delimited <ms:code_list> cleanly without guessing."""
    gml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"
                           xmlns:gml="http://www.opengis.net/gml"
                           xmlns:ms="http://mapserver.gis.umn.edu/mapserver">
      <gml:featureMember>
        <ms:mrds-low gml:id="mrds.1">
          <ms:dep_id>100001</ms:dep_id>
          <ms:site_name>Khetri Copper Mine</ms:site_name>
          <ms:code_list>CU</ms:code_list>
          <ms:dev_stat>Producer</ms:dev_stat>
          <ms:msGeometry><gml:Point><gml:coordinates>75.79,28.00</gml:coordinates></gml:Point></ms:msGeometry>
        </ms:mrds-low>
      </gml:featureMember>
      <gml:featureMember>
        <ms:mrds-low gml:id="mrds.2">
          <ms:dep_id>100002</ms:dep_id>
          <ms:site_name>Polymetallic Prospect</ms:site_name>
          <ms:code_list>NI CO PB ZN CU AU AG XYZUNKN</ms:code_list>
          <ms:msGeometry><gml:Point><gml:coordinates>75.80,28.01</gml:coordinates></gml:Point></ms:msGeometry>
        </ms:mrds-low>
      </gml:featureMember>
      <gml:featureMember>
        <ms:mrds-low gml:id="mrds.3">
          <ms:dep_id>100003</ms:dep_id>
          <ms:site_name>Phosphorite Occurrence</ms:site_name>
          <ms:code_list>P, BA; U</ms:code_list>
          <ms:msGeometry><gml:Point><gml:coordinates>75.81,28.02</gml:coordinates></gml:Point></ms:msGeometry>
        </ms:mrds-low>
      </gml:featureMember>
      <gml:featureMember>
        <ms:mrds-low gml:id="mrds.4">
          <ms:dep_id>100004</ms:dep_id>
          <ms:site_name>No Commodity Tag</ms:site_name>
          <ms:code_list></ms:code_list>
          <ms:msGeometry><gml:Point><gml:coordinates>75.78,27.99</gml:coordinates></gml:Point></ms:msGeometry>
        </ms:mrds-low>
      </gml:featureMember>
    </wfs:FeatureCollection>"""

    records = USGSMRDSAdapter.parse_gml2(gml)
    assert len(records) == 4

    assert records[0].raw_commodities == ["CU"]
    assert records[0].unknown_commodity_codes == []
    assert records[0].commodities_all == ["Cu"]

    assert records[1].raw_commodities == ["NI", "CO", "PB", "ZN", "CU", "AU", "AG", "XYZUNKN"]
    assert records[1].unknown_commodity_codes == ["XYZUNKN"]
    assert records[1].commodities_all == ["Ni", "Co", "Pb", "Zn", "Cu", "Au", "Ag", "XYZUNKN"]

    assert records[2].raw_commodities == ["P", "BA", "U"]
    assert records[2].commodities_all == ["P", "Ba", "U"]

    assert records[3].commodities_all == []
    assert records[3].raw_commodities == []


def test_two_tile_dem_mosaic_preserves_nodata_and_computes_8_derivatives(
    db_session: Session, tmp_path: Path
) -> None:
    """Remediation D: Adjacent tiles split at 28.00N mosaic cleanly and uncovered corners stay NoData."""
    aoi = _create_khetri_test_aoi(db_session)
    # South tile covers 27.97..28.00 (south half of AOI)
    south = _write_geotiff(
        tmp_path / "N27_00.tif",
        [np.linspace(300.0, 380.0, 40 * 40, dtype=np.float32).reshape(40, 40)],
        bounds=(75.76, 27.97, 75.83, 28.00),
    )
    # North tile covers 28.00..28.04 ONLY west of 75.81 (leaving NE corner intentionally uncovered)
    north = _write_geotiff(
        tmp_path / "N28_00.tif",
        [np.linspace(380.0, 460.0, 40 * 40, dtype=np.float32).reshape(40, 40)],
        bounds=(75.76, 28.00, 75.81, 28.04),
    )

    mosaic_path = tmp_path / "mosaic.tif"
    m = mosaic_compatible_dem_tiles(
        tile_paths=[south, north],
        aoi_bbox_wgs84=(75.77, 27.98, 75.82, 28.03),
        output_path=mosaic_path,
    )
    assert m.tile_count == 2
    assert m.mosaic_path.exists()

    settings = Settings(features_dir=str(tmp_path / "features"))
    outcome = extract_aoi_features(
        db=db_session,
        aoi=aoi,
        settings=settings,
        resolution_m=150.0,
        dem_local_paths=[south, north],
        include_geology=False,
        include_sentinel2=False,
        include_aster=False,
    )
    manifest = outcome.manifest
    for feat in (
        "elevation_m",
        "slope_deg",
        "aspect_deg",
        "tpi",
        "tri",
        "curvature",
        "drainage_proxy",
        "hillshade",
    ):
        assert feat in manifest.feature_names

    # Valid pct should be < 100 because NE corner is uncovered
    assert 50.0 < outcome.feature_stats["elevation_m"]["valid_pct"] < 99.0
    assert (manifest.manifest_json or {})["dem_coverage_pct"] is not None


def test_sentinel2_multiband_extraction_no_silent_b8a_substitution(
    db_session: Session, tmp_path: Path
) -> None:
    """Remediation C: Multi-band S2 computes spectral indices & refuses silent B8A->B08 substitution."""
    aoi = _create_khetri_test_aoi(db_session)
    bounds = (75.76, 27.97, 75.83, 28.04)
    shape = (32, 32)
    band_paths = {
        "B02": _write_geotiff(tmp_path / "B02.tif", [np.full(shape, 900.0, dtype=np.float32)], bounds=bounds),
        "B03": _write_geotiff(tmp_path / "B03.tif", [np.full(shape, 1100.0, dtype=np.float32)], bounds=bounds),
        "B04": _write_geotiff(tmp_path / "B04.tif", [np.full(shape, 1400.0, dtype=np.float32)], bounds=bounds),
        "B08": _write_geotiff(tmp_path / "B08.tif", [np.full(shape, 2100.0, dtype=np.float32)], bounds=bounds),
        "B11": _write_geotiff(tmp_path / "B11.tif", [np.full(shape, 2500.0, dtype=np.float32)], bounds=bounds),
        "B12": _write_geotiff(tmp_path / "B12.tif", [np.full(shape, 1800.0, dtype=np.float32)], bounds=bounds),
        "SCL": _write_geotiff(tmp_path / "SCL.tif", [np.full(shape, 4.0, dtype=np.uint8)], bounds=bounds, nodata=0),
    }

    settings = Settings(features_dir=str(tmp_path / "features"))
    outcome = extract_aoi_features(
        db=db_session,
        aoi=aoi,
        settings=settings,
        resolution_m=200.0,
        sentinel_band_paths=band_paths,
        include_geology=False,
        include_aster=False,
    )
    fnames = outcome.manifest.feature_names
    for expected in (
        "ndvi",
        "ndwi",
        "ndbi",
        "s2_iron_oxide_ratio",
        "s2_clay_hydroxyl_ratio",
        "s2_bare_earth_mask",
    ):
        assert expected in fnames

    # Crucially: B8A was NOT provided, so s2_ferrous_iron_ratio must NOT be silently computed using B08
    assert "s2_ferrous_iron_ratio" not in fnames
    assert any("B8A" in w for w in (outcome.manifest.warnings_json or []))

    # Verify rasterio reads the persisted output GeoTIFF cleanly
    stack_path = outcome.stack_path
    assert stack_path.exists()
    with rasterio.open(stack_path) as src:
        assert src.count == len(fnames)


def test_aster_grouped_cog_mapping_verified_and_ambiguous_rejected(
    db_session: Session, tmp_path: Path
) -> None:
    """Remediation F: Verified ASTER grouped VNIR/SWIR/TIR band extraction & rejection on ambiguity."""
    bounds = (75.76, 27.97, 75.83, 28.04)
    shape = (24, 24)
    vnir = _write_geotiff(
        tmp_path / "VNIR.tif",
        [np.full(shape, 40.0 + i * 10.0, dtype=np.float32) for i in range(3)],
        bounds=bounds,
        nodata=0.0,
        descriptions=("ImageData1 VNIR_Swath", "ImageData2 VNIR_Swath", "ImageData3N VNIR_Swath"),
    )
    swir = _write_geotiff(
        tmp_path / "SWIR.tif",
        [np.full(shape, 100.0 + i * 15.0, dtype=np.float32) for i in range(6)],
        bounds=bounds,
        nodata=0.0,
        descriptions=tuple(f"ImageData{i} SWIR_Swath" for i in range(4, 10)),
    )
    tir = _write_geotiff(
        tmp_path / "TIR.tif",
        [np.full(shape, 1500.0 + i * 25.0, dtype=np.float32) for i in range(5)],
        bounds=bounds,
        nodata=0.0,
        descriptions=tuple(f"ImageData{i} TIR_Swath" for i in range(10, 15)),
    )

    resolved_list, _resolve_warnings = resolve_aster_grouped_bands(
        {"VNIR": vnir, "SWIR": swir, "TIR": tir}
    )
    by_band = {r.scientific_band: r for r in resolved_list}
    assert len(by_band) == len(ASTER_BAND_SPECS)
    assert by_band["B04"].band_index == 1 and by_band["B04"].group == "SWIR"
    assert by_band["B05"].band_index == 2 and by_band["B05"].group == "SWIR"
    assert by_band["B12"].band_index == 3 and by_band["B12"].group == "TIR"

    aoi = _create_khetri_test_aoi(db_session)
    settings = Settings(features_dir=str(tmp_path / "features"))
    outcome = extract_aoi_features(
        db=db_session,
        aoi=aoi,
        settings=settings,
        resolution_m=200.0,
        aster_band_paths={"VNIR": vnir, "SWIR": swir, "TIR": tir},
        include_geology=False,
        include_sentinel2=False,
    )
    for expected in ("aster_ferric_iron", "aster_aloh_clay", "aster_silica_tir_proxy"):
        assert expected in outcome.manifest.feature_names
    mapping = (outcome.manifest.manifest_json or {}).get("aster_band_mapping", [])
    mapped_bands = {
        m["scientific_band"] for m in mapping if isinstance(m, dict) and "scientific_band" in m
    }
    assert "B05" in mapped_bands and "B12" in mapped_bands

    # Contradictory / unlabelled grouped file MUST fail explicitly rather than guess
    unlabelled = _write_geotiff(
        tmp_path / "SWIR_bad.tif",
        [np.full(shape, 100.0, dtype=np.float32) for _ in range(6)],
        bounds=bounds,
        nodata=0.0,
        descriptions=None,
    )
    with pytest.raises(ValueError):
        resolve_aster_grouped_bands({"SWIR": unlabelled})


def test_secret_sanitization_strips_sas_and_bearer_tokens() -> None:
    """Remediation B: Never persist SAS query strings or tokens in URLs or logs."""
    raw = "https://naipeuwest.blob.core.windows.net/aster/VNIR.tif?st=2026-01-01&se=2026-01-02&sp=rl&sv=2024-05-04&sig=TOPSECRET=="
    cleaned = sanitize_url_for_storage(raw)
    assert cleaned == "https://naipeuwest.blob.core.windows.net/aster/VNIR.tif"
    assert "sig=" not in cleaned and "TOPSECRET" not in cleaned

    err_text = f"HTTP error opening {raw} with Bearer edl_secret_token_123"
    scrubbed = scrub_secrets_from_text(err_text)
    assert "TOPSECRET" not in scrubbed
    assert "edl_secret_token_123" not in scrubbed
