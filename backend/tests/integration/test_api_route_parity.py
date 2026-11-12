"""Automated OpenAPI contract parity tests between frontend/src/services/api.ts and FastAPI."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AreaOfInterest, RasterAsset
from app.db.repositories import (
    DataSourceRepository,
    ProcessingJobRepository,
    RasterAssetRepository,
)
from app.geospatial.pipeline import extract_aoi_features
from app.main import create_app
from app.storage.manager import sanitize_url_for_storage

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_API_TS = REPO_ROOT / "frontend" / "src" / "services" / "api.ts"


def _normalize_frontend_path(raw_path: str) -> str:
    without_query = raw_path.split("?", 1)[0]
    return re.sub(r"\$\{[^}]+\}", "{param}", without_query)


def _normalize_openapi_path(raw_path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", raw_path)


def _extract_frontend_endpoints(ts_source: str) -> list[tuple[str, str]]:
    """Parse all /api/v1/... endpoint calls and their HTTP methods from api.ts deterministically."""
    endpoints: list[tuple[str, str]] = []
    search_start = ts_source.find("export const apiClient")
    body = ts_source[search_start:] if search_start != -1 else ts_source
    for match in re.finditer(r"([`'\"])(/api/v1/[^`'\"]+)\1", body):
        raw_url = match.group(2)
        lookahead = body[match.end() : match.end() + 250]
        next_call = lookahead.find("apiJson")
        if next_call != -1:
            lookahead = lookahead[:next_call]
        method_match = re.search(r"method:\s*['\"]([A-Z]+)['\"]", lookahead)
        method = method_match.group(1).upper() if method_match else "GET"
        endpoints.append((method, _normalize_frontend_path(raw_url)))
    return endpoints


def test_frontend_api_routes_match_fastapi_openapi() -> None:
    """Every route called by frontend/src/services/api.ts MUST exist in FastAPI OpenAPI schema."""
    assert FRONTEND_API_TS.exists(), f"Missing frontend api client at {FRONTEND_API_TS}"
    ts_source = FRONTEND_API_TS.read_text(encoding="utf-8")

    # Explicitly guard against historical Phase 3 audit 404 mismatches in frontend source
    assert "/ingest`" not in ts_source, "api.ts still calls outdated /api/v1/aois/{id}/ingest"
    assert "/satellite/assets/" not in ts_source, "api.ts still calls outdated /api/v1/satellite/assets/{id}/download"

    frontend_endpoints = _extract_frontend_endpoints(ts_source)
    assert len(frontend_endpoints) >= 15, f"Expected >= 15 endpoints, extracted {len(frontend_endpoints)}"

    app = create_app()
    openapi_paths: dict[str, dict] = app.openapi()["paths"]

    registered: set[tuple[str, str]] = set()
    for oa_path, ops in openapi_paths.items():
        norm_path = _normalize_openapi_path(oa_path)
        for http_method in ops:
            registered.add((http_method.upper(), norm_path))

    missing = [ep for ep in frontend_endpoints if ep not in registered]
    assert not missing, f"Frontend api.ts references non-existent FastAPI routes: {missing}"


def test_legacy_mismatched_routes_unmounted() -> None:
    """Old incorrect URLs from Phase 3C remain unmounted (no silent aliasing hiding bugs)."""
    app = create_app()
    openapi_paths: dict[str, dict] = app.openapi()["paths"]
    normalized_registered = {_normalize_openapi_path(p) for p in openapi_paths}

    assert "/api/v1/aois/{param}/ingest" not in normalized_registered
    assert "/api/v1/satellite/assets/{param}/download" not in normalized_registered
    assert "/api/v1/satellite/assets/{param}" not in normalized_registered


def test_job_lifecycle_poll_cancel_and_feature_extract_service_roundtrip(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Full service-level integration for job lifecycle, secret scrubbing, and feature extraction."""
    # 1. Create AOI
    aoi = AreaOfInterest(
        name="Parity Test Khetri",
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
    db_session.add(aoi)
    db_session.commit()
    db_session.refresh(aoi)

    # 2. Seed synthetic local DEM COG + RasterAsset
    dem_src_path = tmp_path / "source_dem.tif"
    dem_data = np.linspace(320.0, 480.0, 32 * 32, dtype=np.float32).reshape(32, 32)
    with rasterio.open(
        dem_src_path,
        "w",
        driver="GTiff",
        height=32,
        width=32,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(75.76, 27.97, 75.83, 28.04, 32, 32),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem_data, 1)

    src = DataSourceRepository(db_session).get_by_key("mpc_stac")
    assert src is not None
    raw_sas_url = "https://example.blob.core.windows.net/dem/tile.tif?se=2099-01-01&sig=SECRET"
    asset = RasterAsset(
        aoi_id=aoi.id,
        source_id=src.id,
        stac_collection="cop-dem-glo-30",
        stac_item_id="Copernicus_DSM_COG_10_N28_00_E075_00_DEM",
        asset_type="dem_glo30",
        platform="copernicus-dem",
        product_type="dem_glo30",
        resolution_m=30.0,
        bbox_min_lon=75.76,
        bbox_min_lat=27.97,
        bbox_max_lon=75.83,
        bbox_max_lat=28.04,
        footprint_geojson='{"type":"Polygon","coordinates":[[[75.76,27.97],[75.83,27.97],[75.83,28.04],[75.76,28.04],[75.76,27.97]]]}',
        storage_uri=sanitize_url_for_storage(raw_sas_url),
        download_status="discovered",
        requires_auth=False,
        bands_available=["data"],
        band_metadata={
            "provider_key": "mpc_stac",
            "asset_hrefs": {"data": sanitize_url_for_storage(raw_sas_url)},
        },
        data_origin="real",
    )
    RasterAssetRepository(db_session).upsert_many([asset])
    db_session.refresh(asset)

    # Verify secret is never stored in DB
    assert "sig=SECRET" not in asset.storage_uri
    assert "sig=SECRET" not in str(asset.band_metadata)

    # 3. Test job repository lifecycle: create -> running -> update_progress -> complete
    job_repo = ProcessingJobRepository(db_session)
    job = job_repo.create(
        job_type="cog_window_download",
        aoi_id=aoi.id,
        parameters={"asset_id": asset.id, "band_key": "auto"},
    )
    assert job.status == "pending"
    assert job.progress_pct == 0

    job_repo.mark_running(job, progress_pct=25)
    assert job.status == "running"
    assert job.progress_pct == 25

    job_repo.update_progress(job, progress_pct=75, summary={"last_band": "DEM"})
    assert job.progress_pct == 75

    job_repo.complete(job, summary={"band_count_downloaded": 1})
    assert job.status == "completed"
    assert job.progress_pct == 100

    # 4. Test cancel lifecycle on a pending job
    cancel_job = job_repo.create(
        job_type="cog_window_download",
        aoi_id=aoi.id,
        parameters={"asset_id": asset.id},
    )
    job_repo.cancel(cancel_job, reason="User cancelled test")
    assert cancel_job.status == "cancelled"
    assert job_repo.is_cancelled(cancel_job.id) is True

    # 5. Extract features using local DEM path and verify manifest
    settings = Settings(features_dir=str(tmp_path / "features"))
    outcome = extract_aoi_features(
        db=db_session,
        aoi=aoi,
        settings=settings,
        resolution_m=150.0,
        dem_local_paths=[dem_src_path],
        include_geology=False,
        include_sentinel2=False,
        include_aster=False,
    )
    assert outcome.manifest.status == "completed"
    assert "slope_deg" in outcome.manifest.feature_names
    assert outcome.stack_path.exists()
