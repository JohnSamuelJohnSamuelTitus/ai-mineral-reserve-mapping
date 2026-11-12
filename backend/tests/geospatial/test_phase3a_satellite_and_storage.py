"""Phase 3A tests for path safety, windowed COG clipping, STAC discovery, and geology import API."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.api.v1 import satellite_routes
from app.integrations.stac import STACSceneMetadata, estimate_clipped_raster_mb
from app.satellite.downloader import download_cog_window_for_aoi
from app.storage.manager import (
    StorageLimitError,
    UnsafePathError,
    resolve_safe_path,
    validate_file_size,
)


def test_storage_path_traversal_and_size_limits(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "..", "secret.txt")
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "C:/Windows/System32")
    with pytest.raises(UnsafePathError):
        resolve_safe_path(tmp_path, "valid\x00evil")

    safe = resolve_safe_path(tmp_path, "aoi-1", "band_b04.tif")
    assert safe.parent == tmp_path.resolve() / "aoi-1"

    with pytest.raises(StorageLimitError):
        validate_file_size(0, max_mb=10.0)
    with pytest.raises(StorageLimitError):
        validate_file_size(25 * 1024 * 1024, max_mb=10.0)


def test_windowed_cog_clip_on_synthetic_raster(tmp_path: Path) -> None:
    # Synthetic EPSG:32643 raster covering a larger tile (~4km x 4km around Khetri UTM center)
    src_path = tmp_path / "synthetic_large.tif"
    height, width = 200, 200
    pixel_size = 20.0
    transform = from_origin(576000.0, 3100000.0, pixel_size, pixel_size)
    arr = np.arange(height * width, dtype=np.uint16).reshape((1, height, width))
    with rasterio.open(
        src_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint16",
        crs="EPSG:32643",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(arr)

    # Small inner AOI bbox in WGS84 (~1km x 1km inside the 4km x 4km tile)
    clipped = download_cog_window_for_aoi(
        asset_url=str(src_path),
        aoi_bbox_wgs84=(75.78, 27.99, 75.79, 28.00),
        output_dir=tmp_path / "out",
        aoi_id="aoi-test",
        filename_stem="clipped_band",
        max_download_mb=50.0,
        min_free_disk_gb=0.05,
    )
    assert clipped.local_path.exists()
    assert clipped.crs_epsg == 32643
    assert clipped.width < width
    assert clipped.height < height
    assert len(clipped.checksum_sha256) == 64

    # Estimate function sanity
    assert 0.5 < estimate_clipped_raster_mb(100.0, resolution_m=10.0, band_count=1) < 3.0


def test_satellite_search_auth_gating_and_geology_import_api(
    client: TestClient, monkeypatch
) -> None:
    aoi_resp = client.post(
        "/api/v1/aois",
        json={
            "name": "Khetri Phase 3A AOI",
            "jurisdiction": "IN",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[75.7, 27.9], [75.9, 27.9], [75.9, 28.1], [75.7, 28.1], [75.7, 27.9]]],
            },
            "data_origin": "synthetic",
        },
    )
    assert aoi_resp.status_code == 201
    aoi_id = aoi_resp.json()["id"]

    # GIBS layers endpoint explicitly marks visualization_only
    gibs = client.get("/api/v1/satellite/gibs-layers")
    assert gibs.status_code == 200
    assert len(gibs.json()) >= 1
    assert all(layer["is_quantitative_science_product"] is False for layer in gibs.json())

    # Fake STAC adapter search returning EMIT item (requires_auth=True)
    async def _fake_search(self, **_kwargs):
        return [
            STACSceneMetadata(
                provider_key=self.provider_key,
                collection="EMITL2BMIN_001",
                item_id="EMIT_L2B_MIN_TEST_001",
                platform="emit-iss",
                product_type="hyperspectral_mineralogy",
                resolution_m=60.0,
                requires_auth=True,
                auth_note="Earthdata token required",
                estimated_size_mb=4.2,
                bands_available=["EMIT_L2B_MIN", "browse"],
                bbox=[75.7, 27.9, 75.9, 28.1],
                geometry={"type": "Polygon", "coordinates": [[[75.7, 27.9], [75.9, 27.9], [75.9, 28.1], [75.7, 28.1], [75.7, 27.9]]]},
                asset_hrefs={"EMIT_L2B_MIN": "https://data.lpdaac.earthdatacloud.nasa.gov/fake.nc"},
            )
        ]

    monkeypatch.setattr(satellite_routes.STACSearchAdapter, "search", _fake_search)

    search_resp = client.post(
        "/api/v1/satellite/search",
        json={
            "aoi_id": aoi_id,
            "provider": "nasa_cmr_stac",
            "collections": ["EMITL2BMIN_001"],
            "limit": 2,
        },
    )
    assert search_resp.status_code == 200
    assert search_resp.json()["saved_count"] == 1

    rasters_resp = client.get(f"/api/v1/aois/{aoi_id}/rasters")
    assert rasters_resp.status_code == 200
    scene_id = rasters_resp.json()[0]["id"]
    assert rasters_resp.json()[0]["requires_auth"] is True

    # Download blocked cleanly without NASA Earthdata token (HTTP 403)
    blocked = client.post(f"/api/v1/satellite/scenes/{scene_id}/download-clipped?band_key=EMIT_L2B_MIN")
    assert blocked.status_code == 403

    # Upload Indian CSV with 1 valid inside AOI and 1 invalid coordinate -> quarantine + report
    csv_bytes = (
        b"external_id,name,commodity,lon,lat,state\n"
        b"NGDR-1,Khetri Test Prospect,Copper,75.8,28.0,Rajasthan\n"
        b"NGDR-BAD,Invalid Point,Cu,999.0,28.0,Rajasthan\n"
    )
    imp = client.post(
        f"/api/v1/geology/aois/{aoi_id}/import",
        data={"source_provider_key": "ngdr_geodataindia", "data_origin": "synthetic"},
        files={"file": ("khetri_test.csv", csv_bytes, "text/csv")},
    )
    assert imp.status_code == 200
    rep = imp.json()
    assert rep["accepted_rows"] == 1
    assert rep["rejected_rows"] == 1

    q_list = client.get(f"/api/v1/geology/aois/{aoi_id}/quarantine")
    assert q_list.status_code == 200
    assert len(q_list.json()) == 1
    assert q_list.json()[0]["rejection_reason"] == "invalid_wgs84_coordinates"

    reports = client.get(f"/api/v1/geology/aois/{aoi_id}/quality-reports")
    assert reports.status_code == 200
    assert len(reports.json()) == 1
    assert len(reports.json()[0]["commodity_distribution"]) == 1
