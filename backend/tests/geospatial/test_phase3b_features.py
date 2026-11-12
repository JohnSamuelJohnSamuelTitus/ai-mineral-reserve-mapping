"""Unit, scientific correctness, and API integration tests for Phase 3B feature engineering."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import DataSource, RasterAsset
from app.db.repositories import AOIRepository, DataSourceRepository
from app.geospatial.pipeline import extract_aoi_features
from app.geospatial.raster_ops import DEFAULT_NODATA
from app.geospatial.spectral import compute_aster_features, compute_sentinel2_features
from app.geospatial.terrain import compute_terrain_derivatives


def _create_khetri_aoi_via_api(client: TestClient) -> dict:
    resp = client.post(
        "/api/v1/aois",
        json={
            "name": "Khetri Phase3B Test AOI",
            "description": "Feature engineering integration test AOI",
            "jurisdiction": "IN",
            "commodity_focus": ["Cu"],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [75.77, 27.98],
                        [75.81, 27.98],
                        [75.81, 28.02],
                        [75.77, 28.02],
                        [75.77, 27.98],
                    ]
                ],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_terrain_derivatives_rejects_geographic_degrees() -> None:
    dem = np.full((5, 5), 400.0, dtype=np.float32)
    with pytest.raises(ValueError, match="projected metric CRS"):
        compute_terrain_derivatives(dem, pixel_size_m=0.0003, is_projected_metric=False)


def test_terrain_derivatives_exact_planar_slopes_and_cardinal_aspects() -> None:
    pixel_m = 30.0
    xs = np.arange(5, dtype=np.float64) * pixel_m
    ys = np.arange(5, dtype=np.float64) * pixel_m
    xx, yy = np.meshgrid(xs, ys)

    # Planar slope rising East (+0.1 rise per meter -> slopes down toward West = 270 deg)
    dem_east_up = (100.0 + 0.1 * xx).astype(np.float32)
    deriv_w = compute_terrain_derivatives(dem_east_up, pixel_size_m=pixel_m, is_projected_metric=True)
    expected_slope_deg = math.degrees(math.atan(0.1))
    assert deriv_w.slope_deg[2, 2] == pytest.approx(expected_slope_deg, abs=1e-3)
    assert deriv_w.aspect_deg[2, 2] == pytest.approx(270.0, abs=1e-3)
    assert deriv_w.curvature[2, 2] == pytest.approx(0.0, abs=1e-5)

    # Planar slope rising North (row 0 highest, row 4 lowest -> slopes down toward South = 180 deg)
    dem_north_up = (500.0 - 0.2 * yy).astype(np.float32)
    deriv_s = compute_terrain_derivatives(dem_north_up, pixel_size_m=pixel_m, is_projected_metric=True)
    assert deriv_s.slope_deg[2, 2] == pytest.approx(math.degrees(math.atan(0.2)), abs=1e-3)
    assert deriv_s.aspect_deg[2, 2] == pytest.approx(180.0, abs=1e-3)

    # Peak in center -> positive TPI; Pit in center -> negative TPI and higher drainage proxy
    dem_peak = np.full((5, 5), 100.0, dtype=np.float32)
    dem_peak[2, 2] = 150.0
    deriv_peak = compute_terrain_derivatives(dem_peak, pixel_size_m=pixel_m, is_projected_metric=True)
    assert deriv_peak.tpi[2, 2] > 40.0
    assert deriv_peak.tri[2, 2] > 0.0

    dem_pit = np.full((5, 5), 100.0, dtype=np.float32)
    dem_pit[2, 2] = 60.0
    deriv_pit = compute_terrain_derivatives(dem_pit, pixel_size_m=pixel_m, is_projected_metric=True)
    assert deriv_pit.tpi[2, 2] < -30.0
    assert deriv_pit.drainage_proxy[2, 2] > 100.0


def test_sentinel2_and_aster_indices_cloud_mask_and_zero_division() -> None:
    shape = (3, 3)
    b02 = np.full(shape, 1000.0, dtype=np.float32)
    b03 = np.full(shape, 1200.0, dtype=np.float32)
    b04 = np.full(shape, 2000.0, dtype=np.float32)
    b08 = np.full(shape, 1500.0, dtype=np.float32)
    b8a = np.full(shape, 1600.0, dtype=np.float32)
    b11 = np.full(shape, 2400.0, dtype=np.float32)
    b12 = np.full(shape, 1200.0, dtype=np.float32)
    scl = np.full(shape, 5, dtype=np.int16)  # 5 = bare soils/non-vegetated

    # Pixel (0,0): cloud (SCL=9) -> must become nodata
    scl[0, 0] = 9
    # Pixel (0,1): zero blue + zero nir/red -> safe zero-div guard
    b02[0, 1] = 0.0
    b04[0, 1] = 0.0
    b08[0, 1] = 0.0
    # Pixel (1,1): dense green vegetation -> NDVI > 0.25 -> bare_earth_mask == 0
    b08[1, 1] = 6000.0
    b04[1, 1] = 1000.0

    feats, docs = compute_sentinel2_features(
        {"B02": b02, "B03": b03, "B04": b04, "B08": b08, "B8A": b8a, "B11": b11, "B12": b12},
        scl=scl,
        nodata=DEFAULT_NODATA,
    )
    assert len(docs) == 7
    assert feats["ndvi"][0, 0] == DEFAULT_NODATA
    assert feats["s2_iron_oxide_ratio"][0, 0] == DEFAULT_NODATA
    assert feats["ndvi"][0, 1] == DEFAULT_NODATA
    assert feats["s2_iron_oxide_ratio"][0, 1] == DEFAULT_NODATA
    assert feats["s2_bare_earth_mask"][0, 0] == DEFAULT_NODATA

    # Bare soil pixel (2,2): NDVI = (1500-2000)/(1500+2000) = -1/7, iron ratio = 2000/1000 = 2.0
    assert feats["ndvi"][2, 2] == pytest.approx(-500.0 / 3500.0, abs=1e-4)
    assert feats["s2_iron_oxide_ratio"][2, 2] == pytest.approx(2.0, abs=1e-4)
    assert feats["s2_clay_hydroxyl_ratio"][2, 2] == pytest.approx(2400.0 / 1200.0, abs=1e-4)
    assert feats["s2_bare_earth_mask"][2, 2] == 1.0
    assert feats["s2_bare_earth_mask"][1, 1] == 0.0

    # ASTER nighttime TIR-only scene must skip SWIR/VNIR cleanly with explicit warnings
    tir_b10 = np.full((3, 3), 290.0, dtype=np.float32)
    tir_b13 = np.full((3, 3), 305.0, dtype=np.float32)
    aster_feats, _, aster_warns = compute_aster_features({"B10": tir_b10, "B13": tir_b13})
    assert "aster_silica_tir_proxy" in aster_feats
    assert "aster_aloh_clay" not in aster_feats
    assert any("SWIR" in w for w in aster_warns)


def test_phase3b_pipeline_and_api_end_to_end(
    client: TestClient, db_session: Session
) -> None:
    settings: Settings = client.app.dependency_overrides[get_settings]()  # type: ignore[union-attr]

    aoi_resp = _create_khetri_aoi_via_api(client)
    aoi_id = aoi_resp["id"]
    aoi = AOIRepository(db_session).get(aoi_id)
    assert aoi is not None

    # Create a real local EPSG:4326 synthetic elevation GeoTIFF inside settings.rasters_dir
    rasters_aoi_dir = settings.rasters_dir / aoi_id
    rasters_aoi_dir.mkdir(parents=True, exist_ok=True)
    dem_path = rasters_aoi_dir / "test_dem_4326.tif"
    rows, cols = 40, 40
    xs = np.linspace(75.76, 75.82, cols, dtype=np.float32)
    ys = np.linspace(28.03, 27.97, rows, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    dem_vals = (400.0 + (xx - 75.76) * 2000.0 + (28.03 - yy) * 1000.0).astype(np.float32)
    px_w = (75.82 - 75.76) / cols
    px_h = (28.03 - 27.97) / rows
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(75.76, 28.03, px_w, px_h),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem_vals, 1)

    # Register RasterAsset pointing to that local DEM
    cop_source = DataSourceRepository(db_session).get_by_key("copernicus_dem")
    if cop_source is None:
        cop_source = DataSource(
            provider_key="copernicus_dem",
            display_name="Copernicus DEM Test",
            jurisdiction="INTL",
            label_authority="reference_only",
            base_url="https://example.invalid",
            license="Copernicus",
            attribution_text="Copernicus",
            is_ml_training_allowed=True,
            is_enabled=True,
        )
        db_session.add(cop_source)
        db_session.commit()
        db_session.refresh(cop_source)

    asset = RasterAsset(
        aoi_id=aoi.id,
        source_id=cop_source.id,
        stac_collection="cop-dem-glo-30",
        stac_item_id="Copernicus_DSM_Test_Khetri",
        asset_type="dem",
        platform="Copernicus-DEM",
        product_type="GLO-30",
        acquired_at=datetime.now(UTC),
        resolution_m=30.0,
        footprint_geojson=json.dumps(
            {
                "type": "Polygon",
                "coordinates": [[[75.76, 27.97], [75.82, 27.97], [75.82, 28.03], [75.76, 28.03], [75.76, 27.97]]],
            }
        ),
        bbox_min_lon=75.76,
        bbox_min_lat=27.97,
        bbox_max_lon=75.82,
        bbox_max_lat=28.03,
        storage_uri="https://example.invalid/dem.tif",
        local_path=str(dem_path),
        download_status="downloaded",
        crs_epsg=4326,
        data_origin="real",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    # Ingest 1 real ML-trainable CSV occurrence inside the AOI
    csv_bytes = (
        b"name,latitude,longitude,commodity,deposit_type\n"
        b"Khetri Copper Mine,28.00,75.79,Copper,VMS\n"
    )
    imp_resp = client.post(
        f"/api/v1/geology/aois/{aoi_id}/import",
        files={"file": ("khetri_occ.csv", csv_bytes, "text/csv")},
        data={"source_provider_key": "ngdr_geodataindia", "data_origin": "real"},
    )
    assert imp_resp.status_code == 200, imp_resp.text

    # 1. Inspect downloaded raster
    insp_resp = client.post(f"/api/v1/features/rasters/{asset.id}/inspect")
    assert insp_resp.status_code == 200, insp_resp.text
    insp = insp_resp.json()
    assert insp["epsg"] == 4326
    assert insp["is_geographic"] is True
    assert insp["stats"]["valid_pct"] == 100.0

    # 2. Extract AOI features synchronously at 250m UTM grid
    ext_resp = client.post(
        f"/api/v1/features/aois/{aoi_id}/extract",
        json={"resolution_m": 250.0, "dem_asset_id": asset.id, "include_geology": True, "run_sync": True},
    )
    assert ext_resp.status_code == 200, ext_resp.text
    job = ext_resp.json()
    assert job["status"] == "completed"
    manifest_id = job["result_summary_json"]["manifest_id"]

    # 3. Verify manifest & scientific non-fabrication warnings
    man_resp = client.get(f"/api/v1/features/manifests/{manifest_id}")
    assert man_resp.status_code == 200, man_resp.text
    manifest = man_resp.json()
    assert manifest["target_crs_epsg"] == aoi.processing_epsg
    assert manifest["target_crs_epsg"] != 4326
    assert "elevation_m" in manifest["feature_names"]
    assert "slope_deg" in manifest["feature_names"]
    assert "dist_to_occurrence_m" in manifest["feature_names"]
    # Missing fault/intrusive layers must NOT be fabricated
    assert "dist_to_fault_m" not in manifest["feature_names"]
    assert "dist_to_intrusive_m" not in manifest["feature_names"]
    assert any("fault" in w.lower() for w in manifest["warnings_json"])

    # 4. Overlay descriptor + rendered PNG preview
    ov_json = client.get(
        f"/api/v1/features/manifests/{manifest_id}/overlay.json",
        params={"feature_name": "slope_deg"},
    )
    assert ov_json.status_code == 200, ov_json.text
    ov = ov_json.json()
    assert len(ov["wgs84_corners"]) == 4

    ov_png = client.get(
        f"/api/v1/features/manifests/{manifest_id}/overlay.png",
        params={"feature_name": "slope_deg"},
    )
    assert ov_png.status_code == 200
    assert ov_png.headers["content-type"] == "image/png"
    assert ov_png.content.startswith(b"\x89PNG\r\n\x1a\n")

    # 5. AOI Coverage endpoint
    cov_resp = client.get(f"/api/v1/features/aois/{aoi_id}/coverage")
    assert cov_resp.status_code == 200, cov_resp.text
    cov = cov_resp.json()
    assert cov["occurrence_ml_trainable"] == 1
    assert cov["raster_scenes_downloaded"] == 1
    assert cov["latest_manifest_id"] == manifest_id
    assert any("fault" in m.lower() for m in cov["missing_layers"])

    # Verify Sentinel-2 band path ingestion directly via pipeline function
    s2_b04 = rasters_aoi_dir / "s2_b04.tif"
    s2_b08 = rasters_aoi_dir / "s2_b08.tif"
    for p, val in [(s2_b04, 1000.0), (s2_b08, 3000.0)]:
        with rasterio.open(
            p,
            "w",
            driver="GTiff",
            height=rows,
            width=cols,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(75.76, 28.03, px_w, px_h),
        ) as dst:
            dst.write(np.full((rows, cols), val, dtype=np.float32), 1)

    outcome = extract_aoi_features(
        db=db_session,
        aoi=aoi,
        settings=settings,
        resolution_m=500.0,
        dem_local_path=dem_path,
        sentinel_band_paths={"red": s2_b04, "nir": s2_b08},
        include_geology=True,
    )
    assert "ndvi" in outcome.manifest.feature_names
    assert outcome.feature_stats["ndvi"]["mean"] == pytest.approx(0.5, abs=1e-2)
    assert Path(outcome.stack_path).exists()
    get_settings.cache_clear()
