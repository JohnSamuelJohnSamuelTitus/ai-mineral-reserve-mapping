"""Satellite STAC search, NASA GIBS visualization catalog, and controlled COG downloads."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, sessionmaker

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
from app.integrations.stac import STACSearchAdapter, resolve_scene_download_targets
from app.satellite.downloader import download_cog_window_for_aoi
from app.storage.manager import (
    StorageLimitError,
    UnsafePathError,
    sanitize_url_for_storage,
    scrub_secrets_from_text,
)

router = APIRouter(prefix="/satellite", tags=["satellite"])


def raster_asset_to_response(r: RasterAsset) -> RasterAssetResponse:
    meta = dict(r.band_metadata or {})
    raw_downloaded = meta.get("downloaded_bands")
    downloaded_bands: dict[str, dict] = {}
    if isinstance(raw_downloaded, dict):
        for band_k, band_info in raw_downloaded.items():
            if isinstance(band_info, dict):
                downloaded_bands[band_k] = {
                    k: v
                    for k, v in band_info.items()
                    if not any(secret_key in k.lower() for secret_key in ("url", "token", "sig", "secret"))
                }
    summary = {
        "provider_key": meta.get("provider_key"),
        "downloaded_band_keys": sorted(downloaded_bands.keys()),
        "asset_info_keys": sorted((meta.get("asset_info") or {}).keys())
        if isinstance(meta.get("asset_info"), dict)
        else [],
        "auth_note": meta.get("auth_note"),
    }
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
        storage_uri=sanitize_url_for_storage(r.storage_uri),
        local_path=r.local_path,
        download_status=r.download_status,
        requires_auth=r.requires_auth,
        estimated_size_mb=r.estimated_size_mb,
        bands_available=r.bands_available or [],
        crs_epsg=r.crs_epsg,
        checksum_sha256=r.checksum_sha256,
        source_provider=meta.get("provider_key"),
        downloaded_bands=downloaded_bands,
        band_metadata_summary=summary,
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
                clean_hrefs = {
                    k: sanitize_url_for_storage(v) for k, v in sc.asset_hrefs.items()
                }
                primary_href = (
                    clean_hrefs.get("visual")
                    or clean_hrefs.get("data")
                    or clean_hrefs.get("B04")
                    or clean_hrefs.get("red")
                    or clean_hrefs.get("VNIR")
                    or next(iter(clean_hrefs.values()), f"stac://{sc.collection}/{sc.item_id}")
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
                        storage_uri=sanitize_url_for_storage(primary_href),
                        download_status="discovered",
                        requires_auth=sc.requires_auth,
                        estimated_size_mb=sc.estimated_size_mb,
                        bands_available=sc.bands_available,
                        band_metadata={
                            "provider_key": payload.provider,
                            "assets": sc.bands_available,
                            "asset_hrefs": clean_hrefs,
                            "asset_info": sc.asset_info,
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


def _extract_fallback_nodata(asset_info: dict, source_key: str) -> float | None:
    entry = asset_info.get(source_key)
    if not isinstance(entry, dict):
        return None
    val = entry.get("nodata")
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _background_download_cog_task(
    *,
    job_id: str,
    asset_id: str,
    download_targets: list[tuple[str, str, str, float | None]] | None = None,
    signed_url: str | None = None,
    band_key: str = "auto",
    aoi_id: str,
    aoi_bbox: tuple[float, float, float, float],
    settings: Settings,
    session_factory: sessionmaker[Session] | None = None,
) -> None:
    factory = session_factory or get_session_factory()
    targets: list[tuple[str, str, str, float | None]] = list(download_targets or [])
    if not targets and signed_url:
        targets = [(band_key, band_key, signed_url, None)]

    with factory() as bg_db:
        job_repo = ProcessingJobRepository(bg_db)
        raster_repo = RasterAssetRepository(bg_db)
        job = job_repo.get(job_id)
        asset = raster_repo.get(asset_id)
        if job is None or asset is None:
            return
        if job.status == "cancelled":
            return

        job_repo.mark_running(job, progress_pct=5)
        downloaded_bands: dict[str, dict] = {}
        total = max(len(targets), 1)
        first_dl = None

        try:
            for idx, (canon_key, source_key, target_signed_url, fallback_nodata) in enumerate(
                targets
            ):
                if job_repo.is_cancelled(job_id):
                    if downloaded_bands and first_dl is not None:
                        raster_repo.mark_bands_downloaded(
                            asset,
                            downloaded_bands=downloaded_bands,
                            primary_local_path=str(first_dl.local_path),
                            primary_checksum_sha256=first_dl.checksum_sha256,
                            crs_epsg=first_dl.crs_epsg,
                            download_status="partial",
                        )
                    return

                dl = download_cog_window_for_aoi(
                    asset_url=target_signed_url,
                    aoi_bbox_wgs84=aoi_bbox,
                    output_dir=settings.rasters_dir,
                    aoi_id=aoi_id,
                    filename_stem=f"{asset.stac_item_id}_{canon_key}",
                    max_download_mb=settings.raster_max_download_mb,
                    min_free_disk_gb=settings.min_free_disk_gb,
                    fallback_nodata=fallback_nodata,
                )
                if first_dl is None:
                    first_dl = dl

                downloaded_bands[canon_key] = {
                    "local_path": str(dl.local_path),
                    "checksum_sha256": dl.checksum_sha256,
                    "crs_epsg": dl.crs_epsg,
                    "width": dl.width,
                    "height": dl.height,
                    "band_count": dl.band_count,
                    "size_mb": dl.size_mb,
                    "dtype": dl.dtype,
                    "native_resolution": list(dl.native_resolution)
                    if dl.native_resolution
                    else None,
                    "nodata": dl.nodata,
                    "band_descriptions": list(dl.band_descriptions),
                    "source_asset_key": source_key,
                }
                pct = min(95, int(((idx + 1) / total) * 90) + 5)
                job_repo.update_progress(
                    job,
                    progress_pct=pct,
                    summary={
                        "completed_bands": sorted(downloaded_bands.keys()),
                        "total_bands": len(targets),
                        "last_band": canon_key,
                    },
                )

            if first_dl is None:
                raise ValueError("No downloadable bands were processed")

            raster_repo.mark_bands_downloaded(
                asset,
                downloaded_bands=downloaded_bands,
                primary_local_path=str(first_dl.local_path),
                primary_checksum_sha256=first_dl.checksum_sha256,
                crs_epsg=first_dl.crs_epsg,
                download_status="downloaded",
            )
            job_repo.complete(
                job,
                summary={
                    "local_path": str(first_dl.local_path),
                    "downloaded_bands": sorted(downloaded_bands.keys()),
                    "band_count_downloaded": len(downloaded_bands),
                    "total_size_mb": round(
                        sum(float(b["size_mb"]) for b in downloaded_bands.values()), 4
                    ),
                    "checksum_sha256": first_dl.checksum_sha256,
                    "crs_epsg": first_dl.crs_epsg,
                    "width": first_dl.width,
                    "height": first_dl.height,
                },
            )
        except (StorageLimitError, UnsafePathError, ValueError, OSError, RuntimeError) as exc:
            if downloaded_bands and first_dl is not None:
                raster_repo.mark_bands_downloaded(
                    asset,
                    downloaded_bands=downloaded_bands,
                    primary_local_path=str(first_dl.local_path),
                    primary_checksum_sha256=first_dl.checksum_sha256,
                    crs_epsg=first_dl.crs_epsg,
                    download_status="partial",
                )
            else:
                raster_repo.mark_download_failed(asset)
            job_repo.fail(job, error_message=scrub_secrets_from_text(str(exc)))


@router.post("/scenes/{asset_id}/download-clipped", response_model=ProcessingJobResponse)
async def download_clipped_scene_band(
    asset_id: str,
    background_tasks: BackgroundTasks,
    band_key: str = Query(default="auto", min_length=1, max_length=128),
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

    meta = dict(asset.band_metadata or {})
    asset_hrefs: dict[str, str] = meta.get("asset_hrefs") or {}
    asset_info: dict = meta.get("asset_info") or {}
    targets = resolve_scene_download_targets(
        collection=asset.stac_collection,
        product_type=asset.product_type,
        asset_hrefs=asset_hrefs,
        band_key=band_key,
    )
    if (
        not targets
        and band_key.lower() in {"auto", "default", "primary", "data"}
        and asset.storage_uri
        and not asset.storage_uri.startswith("stac://")
    ):
        fallback_canon = "DEM" if "dem" in (asset.product_type or "").lower() else band_key
        targets = [(fallback_canon, band_key, sanitize_url_for_storage(asset.storage_uri))]

    if not targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Band(s) '{band_key}' unavailable. Available: {asset.bands_available}",
        )

    aoi = AOIRepository(db).get(asset.aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent AOI not found")

    signer: STACSearchAdapter | None = None
    download_targets: list[tuple[str, str, str, float | None]] = []
    signed_cache: dict[str, str] = {}
    for canon_key, source_key, raw_url in targets:
        clean_url = sanitize_url_for_storage(raw_url)
        signed_url = signed_cache.get(clean_url)
        if signed_url is None:
            signed_url = clean_url
            if (
                clean_url.startswith("https://")
                and "blob.core.windows.net" in clean_url
                and asset.stac_collection
            ):
                if signer is None:
                    signer = STACSearchAdapter(
                        provider_key="mpc_stac",
                        base_url=settings.mpc_stac_url,
                        sas_token_url=settings.mpc_sas_token_url,
                        timeout_seconds=settings.http_timeout_seconds,
                    )
                signed_url = await signer.sign_mpc_asset_url(clean_url, asset.stac_collection)
            signed_cache[clean_url] = signed_url
        download_targets.append(
            (canon_key, source_key, signed_url, _extract_fallback_nodata(asset_info, source_key))
        )

    job = ProcessingJobRepository(db).create(
        job_type="cog_window_download",
        aoi_id=aoi.id,
        parameters={
            "asset_id": asset.id,
            "band_key": band_key,
            "target_bands": [t[0] for t in download_targets],
        },
    )
    bg_factory = sessionmaker(
        bind=db.get_bind(), autocommit=False, autoflush=False, expire_on_commit=False
    )
    background_tasks.add_task(
        _background_download_cog_task,
        job_id=job.id,
        asset_id=asset.id,
        download_targets=download_targets,
        aoi_id=aoi.id,
        aoi_bbox=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
        settings=settings,
        session_factory=bg_factory,
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


@router.get("/jobs/{job_id}", response_model=ProcessingJobResponse)
def get_satellite_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> ProcessingJobResponse:
    job = ProcessingJobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
    return ProcessingJobResponse(
        id=job.id,
        aoi_id=job.aoi_id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        parameters_json=job.parameters_json or {},
        result_summary_json=job.result_summary_json or {},
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
