"""Satellite STAC search, NASA GIBS visualization catalog, and controlled COG downloads."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    ProcessingJobResponse,
    RasterAssetResponse,
    SatelliteSearchRequest,
    SatelliteSearchResponse,
)
from app.core.config import Settings, get_settings
from app.db.models import RasterAsset
from app.db.repositories import (
    AOIRepository,
    DataSourceRepository,
    ProcessingJobRepository,
    RasterAssetRepository,
)
from app.db.session import get_db, get_session_factory
from app.integrations.base import ProviderError
from app.integrations.nasa_gibs import get_nasa_gibs_overlay_layers
from app.integrations.stac import STACSearchAdapter
from app.satellite.downloader import download_cog_window_for_aoi
from app.storage.manager import StorageLimitError, UnsafePathError

router = APIRouter(prefix="/satellite", tags=["satellite"])


def raster_asset_to_response(r: RasterAsset) -> RasterAssetResponse:
    return RasterAssetResponse(
        id=r.id,
        stac_collection=r.stac_collection,
        stac_item_id=r.stac_item_id,
        asset_type=r.asset_type,
        platform=r.platform,
        product_type=r.product_type,
        acquired_at=r.acquired_at,
        cloud_cover_pct=r.cloud_cover_pct,
        resolution_m=r.resolution_m,
        bbox=[r.bbox_min_lon, r.bbox_min_lat, r.bbox_max_lon, r.bbox_max_lat],
        storage_uri=r.storage_uri,
        local_path=r.local_path,
        download_status=r.download_status,
        requires_auth=r.requires_auth,
        estimated_size_mb=r.estimated_size_mb,
        bands_available=r.bands_available or [],
        data_origin=r.data_origin,
        collected_at=r.collected_at,
    )


def _provider_url(provider: str, settings: Settings) -> str:
    if provider == "mpc_stac":
        return settings.mpc_stac_url
    if provider == "earth_search_stac":
        return settings.earth_search_stac_url
    if provider == "nasa_cmr_stac":
        return settings.nasa_cmr_stac_url
    raise ValueError(f"Unsupported STAC provider: {provider}")


@router.get("/gibs-layers")
def list_gibs_layers(settings: Settings = Depends(get_settings)) -> list[dict]:
    """Return NASA GIBS WMTS/XYZ visualization tile layers (not raw quantitative rasters)."""
    return get_nasa_gibs_overlay_layers(settings.nasa_gibs_wmts_url)


@router.post("/search", response_model=SatelliteSearchResponse)
async def search_satellite_scenes(
    payload: SatelliteSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SatelliteSearchResponse:
    aoi = AOIRepository(db).get(payload.aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    adapter = STACSearchAdapter(
        provider_key=payload.provider,
        base_url=_provider_url(payload.provider, settings),
        sas_token_url=settings.mpc_sas_token_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
    )
    try:
        scenes = await adapter.search(
            bbox=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
            collections=payload.collections,
            datetime_range=payload.datetime_range,
            max_cloud_cover=payload.max_cloud_cover,
            aoi_area_km2=aoi.area_km2,
            limit=payload.limit,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    saved_count = 0
    if payload.save_metadata and scenes:
        src_repo = DataSourceRepository(db)
        src = src_repo.get_by_key(payload.provider)
        if src is not None:
            now = datetime.now(UTC)
            to_save: list[RasterAsset] = []
            for sc in scenes:
                primary_href = (
                    sc.asset_hrefs.get("visual")
                    or sc.asset_hrefs.get("data")
                    or sc.asset_hrefs.get("B04")
                    or sc.asset_hrefs.get("red")
                    or next(iter(sc.asset_hrefs.values()), f"stac://{sc.collection}/{sc.item_id}")
                )
                to_save.append(
                    RasterAsset(
                        aoi_id=aoi.id,
                        source_id=src.id,
                        stac_collection=sc.collection,
                        stac_item_id=sc.item_id,
                        asset_type=sc.product_type or f"{sc.collection}_stac_item",
                        platform=sc.platform,
                        product_type=sc.product_type,
                        acquired_at=sc.acquired_at,
                        cloud_cover_pct=sc.cloud_cover_pct,
                        resolution_m=sc.resolution_m,
                        footprint_geojson=json.dumps(sc.geometry),
                        bbox_min_lon=sc.bbox[0],
                        bbox_min_lat=sc.bbox[1],
                        bbox_max_lon=sc.bbox[2],
                        bbox_max_lat=sc.bbox[3],
                        storage_uri=primary_href,
                        download_status="discovered",
                        requires_auth=sc.requires_auth,
                        estimated_size_mb=sc.estimated_size_mb,
                        bands_available=sc.bands_available,
                        band_metadata={
                            "assets": sc.bands_available,
                            "asset_hrefs": sc.asset_hrefs,
                            "auth_note": sc.auth_note,
                        },
                        data_origin="real",
                        collected_at=now,
                    )
                )
            saved_count = RasterAssetRepository(db).upsert_many(to_save)

    return SatelliteSearchResponse(
        aoi_id=aoi.id,
        provider=payload.provider,
        collections_queried=payload.collections,
        scene_count=len(scenes),
        saved_count=saved_count,
        scenes=[sc.model_dump() for sc in scenes],
    )


@router.get("/scenes/{asset_id}", response_model=RasterAssetResponse)
def get_scene_details(asset_id: str, db: Session = Depends(get_db)) -> RasterAssetResponse:
    asset = RasterAssetRepository(db).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raster asset not found")
    return raster_asset_to_response(asset)


def _background_download_cog_task(
    *,
    job_id: str,
    asset_id: str,
    signed_url: str,
    band_key: str,
    aoi_id: str,
    aoi_bbox: tuple[float, float, float, float],
    settings: Settings,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as bg_db:
        job_repo = ProcessingJobRepository(bg_db)
        raster_repo = RasterAssetRepository(bg_db)
        job = job_repo.get(job_id)
        asset = raster_repo.get(asset_id)
        if job is None or asset is None:
            return
        job_repo.mark_running(job, progress_pct=25)
        try:
            dl = download_cog_window_for_aoi(
                asset_url=signed_url,
                aoi_bbox_wgs84=aoi_bbox,
                output_dir=settings.rasters_dir,
                aoi_id=aoi_id,
                filename_stem=f"{asset.stac_item_id}_{band_key}",
                max_download_mb=settings.raster_max_download_mb,
                min_free_disk_gb=settings.min_free_disk_gb,
            )
            raster_repo.mark_downloaded(
                asset,
                local_path=str(dl.local_path),
                checksum_sha256=dl.checksum_sha256,
                crs_epsg=dl.crs_epsg,
            )
            job_repo.complete(
                job,
                summary={
                    "local_path": str(dl.local_path),
                    "size_mb": dl.size_mb,
                    "checksum_sha256": dl.checksum_sha256,
                    "crs_epsg": dl.crs_epsg,
                    "width": dl.width,
                    "height": dl.height,
                },
            )
        except (StorageLimitError, UnsafePathError, ValueError, OSError, RuntimeError) as exc:
            raster_repo.mark_download_failed(asset)
            job_repo.fail(job, error_message=str(exc))


@router.post("/scenes/{asset_id}/download-clipped", response_model=ProcessingJobResponse)
async def download_clipped_scene_band(
    asset_id: str,
    background_tasks: BackgroundTasks,
    band_key: str = Query(default="data", min_length=1, max_length=64),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProcessingJobResponse:
    asset = RasterAssetRepository(db).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raster asset not found")

    if asset.requires_auth and not settings.nasa_earthdata_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="NASA Earthdata Login token is required before downloading this product.",
        )

    asset_hrefs: dict[str, str] = asset.band_metadata.get("asset_hrefs") or {}
    raw_url = asset_hrefs.get(band_key) or (asset.storage_uri if band_key in ("default", "primary") else None)
    if not raw_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Band '{band_key}' unavailable. Available: {asset.bands_available}",
        )

    aoi = AOIRepository(db).get(asset.aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent AOI not found")

    signed_url = raw_url
    if raw_url.startswith("https://") and "blob.core.windows.net" in raw_url and asset.stac_collection:
        signer = STACSearchAdapter(
            provider_key="mpc_stac",
            base_url=settings.mpc_stac_url,
            sas_token_url=settings.mpc_sas_token_url,
            timeout_seconds=settings.http_timeout_seconds,
        )
        signed_url = await signer.sign_mpc_asset_url(raw_url, asset.stac_collection)

    job = ProcessingJobRepository(db).create(
        job_type="cog_window_download",
        aoi_id=aoi.id,
        parameters={"asset_id": asset.id, "band_key": band_key},
    )
    background_tasks.add_task(
        _background_download_cog_task,
        job_id=job.id,
        asset_id=asset.id,
        signed_url=signed_url,
        band_key=band_key,
        aoi_id=aoi.id,
        aoi_bbox=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
        settings=settings,
    )
    return ProcessingJobResponse(
        id=job.id,
        aoi_id=job.aoi_id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        parameters_json=job.parameters_json,
        result_summary_json=job.result_summary_json,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/jobs", response_model=list[ProcessingJobResponse])
def list_processing_jobs(
    aoi_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ProcessingJobResponse]:
    jobs = ProcessingJobRepository(db).list_for_aoi(aoi_id, limit=limit)
    return [
        ProcessingJobResponse(
            id=j.id,
            aoi_id=j.aoi_id,
            job_type=j.job_type,
            status=j.status,
            progress_pct=j.progress_pct,
            parameters_json=j.parameters_json,
            result_summary_json=j.result_summary_json,
            error_message=j.error_message,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]
