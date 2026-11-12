"""Geospatial raster inspection, AOI feature extraction, coverage summary, and overlay preview routes."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import rasterio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.schemas import (
    AOICoverageResponse,
    FeatureExtractRequest,
    FeatureManifestResponse,
    FeatureOverlayDescriptorResponse,
    ProcessingJobResponse,
    RasterInspectResponse,
)
from app.core.config import Settings, get_settings
from app.db.models import FeatureManifest
from app.db.repositories import (
    AOIRepository,
    FeatureManifestRepository,
    GeologicalUnitRepository,
    MineralOccurrenceRepository,
    ProcessingJobRepository,
    QuarantineAndQualityRepository,
    RasterAssetRepository,
)
from app.db.session import get_db
from app.geological.quality import SCIENTIFIC_BIAS_WARNING
from app.geospatial.pipeline import extract_aoi_features
from app.geospatial.raster_ops import inspect_raster_metadata

router = APIRouter(prefix="/features", tags=["features"])


def _manifest_to_response(m: FeatureManifest) -> FeatureManifestResponse:
    return FeatureManifestResponse(
        id=m.id,
        aoi_id=m.aoi_id,
        target_crs_epsg=m.target_crs_epsg,
        resolution_m=m.resolution_m,
        grid_rows=m.grid_rows,
        grid_cols=m.grid_cols,
        nodata_value=m.nodata_value,
        status=m.status,
        input_datasets_json=m.input_datasets_json or [],
        input_scene_ids=m.input_scene_ids or [],
        feature_names=m.feature_names or [],
        output_files_json=m.output_files_json or {},
        warnings_json=m.warnings_json or [],
        manifest_json=m.manifest_json or {},
        data_origin=m.data_origin,
        created_at=m.created_at,
    )


def _execute_feature_job_with_session(
    *,
    db: Session,
    job_id: str,
    aoi_id: str,
    resolution_m: float,
    dem_asset_id: str | None,
    include_geology: bool,
    settings: Settings,
) -> None:
    job_repo = ProcessingJobRepository(db)
    job = job_repo.get(job_id)
    if job is None:
        return
    try:
        job_repo.mark_running(job, progress_pct=20)
        aoi = AOIRepository(db).get(aoi_id)
        if aoi is None:
            raise ValueError(f"AOI '{aoi_id}' not found")
        outcome = extract_aoi_features(
            db=db,
            aoi=aoi,
            settings=settings,
            resolution_m=resolution_m,
            dem_asset_id=dem_asset_id,
            include_geology=include_geology,
        )
        job_repo.complete(
            job,
            summary={
                "manifest_id": outcome.manifest.id,
                "feature_names": outcome.manifest.feature_names,
                "grid_rows": outcome.manifest.grid_rows,
                "grid_cols": outcome.manifest.grid_cols,
                "resolution_m": outcome.manifest.resolution_m,
                "warnings_count": len(outcome.manifest.warnings_json or []),
                "feature_stats": outcome.feature_stats,
            },
        )
    except (ValueError, OSError, RuntimeError) as exc:
        job_repo.fail(job, error_message=str(exc))


def _run_feature_extraction_job(
    session_factory: sessionmaker[Session],
    job_id: str,
    aoi_id: str,
    resolution_m: float,
    dem_asset_id: str | None,
    include_geology: bool,
    settings: Settings,
) -> None:
    db = session_factory()
    try:
        _execute_feature_job_with_session(
            db=db,
            job_id=job_id,
            aoi_id=aoi_id,
            resolution_m=resolution_m,
            dem_asset_id=dem_asset_id,
            include_geology=include_geology,
            settings=settings,
        )
    finally:
        db.close()


def _encode_rgba_png(rgba: np.ndarray) -> bytes:
    """Encode an HxWx4 uint8 RGBA numpy array into a compressed PNG without external deps."""
    height, width, channels = rgba.shape
    if channels != 4:
        raise ValueError("Expected RGBA image array")
    raw_rows = b"".join(b"\x00" + rgba[y].tobytes() for y in range(height))
    compressed = zlib.compress(raw_rows, level=6)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


def _apply_colormap(norm: np.ndarray) -> np.ndarray:
    """Map normalized [0, 1] float values to a legible amber-teal-emerald RGB LUT."""
    # Simple 5-stop scientific ramp: slate-blue -> teal -> gold -> orange -> crimson
    stops_x = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    stops_r = np.array([34, 28, 120, 235, 220], dtype=np.float32)
    stops_g = np.array([62, 148, 198, 165, 58], dtype=np.float32)
    stops_b = np.array([128, 168, 125, 48, 45], dtype=np.float32)
    r = np.interp(norm, stops_x, stops_r).astype(np.uint8)
    g = np.interp(norm, stops_x, stops_g).astype(np.uint8)
    b = np.interp(norm, stops_x, stops_b).astype(np.uint8)
    return np.stack([r, g, b], axis=-1)


def _resolve_manifest_stack(
    manifest: FeatureManifest, settings: Settings
) -> Path:
    raw_path = (manifest.output_files_json or {}).get("feature_stack_tif")
    if not raw_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature stack GeoTIFF path missing in manifest",
        )
    stack_path = Path(raw_path).resolve()
    try:
        stack_path.relative_to(settings.features_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid feature path") from exc
    if not stack_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature stack GeoTIFF not found on disk",
        )
    return stack_path


@router.post("/rasters/{asset_id}/inspect", response_model=RasterInspectResponse)
def inspect_downloaded_raster(
    asset_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RasterInspectResponse:
    asset = RasterAssetRepository(db).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raster asset not found")
    if not asset.local_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Raster asset has not been downloaded locally yet",
        )
    local_path = Path(asset.local_path).resolve()
    try:
        local_path.relative_to(settings.rasters_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsafe raster path") from exc
    if not local_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Downloaded raster file missing")

    meta = inspect_raster_metadata(local_path)
    return RasterInspectResponse(
        asset_id=asset.id,
        local_path=str(local_path),
        epsg=meta.get("crs_epsg"),
        is_geographic=bool(meta.get("is_geographic", False)),
        crs_wkt=meta.get("crs"),
        width=int(meta["width"]),
        height=int(meta["height"]),
        count=int(meta["band_count"]),
        dtype=str((meta.get("dtypes") or ["unknown"])[0]),
        nodata=meta.get("nodata"),
        resolution=list(meta.get("pixel_size") or [0.0, 0.0]),
        bounds=list(meta.get("bounds") or []),
        stats=dict(meta.get("band1_stats") or {}),
    )


@router.post("/aois/{aoi_id}/extract", response_model=ProcessingJobResponse)
def trigger_aoi_feature_extraction(
    aoi_id: str,
    payload: FeatureExtractRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProcessingJobResponse:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    job_repo = ProcessingJobRepository(db)
    job = job_repo.create(
        job_type="feature_extraction",
        aoi_id=aoi.id,
        parameters=payload.model_dump(),
    )

    if payload.run_sync:
        _execute_feature_job_with_session(
            db=db,
            job_id=job.id,
            aoi_id=aoi.id,
            resolution_m=payload.resolution_m,
            dem_asset_id=payload.dem_asset_id,
            include_geology=payload.include_geology,
            settings=settings,
        )
        refreshed = job_repo.get(job.id)
        if refreshed is not None and refreshed.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=refreshed.error_message or "Feature extraction failed",
            )
        job = refreshed or job
    else:
        bg_factory = sessionmaker(
            bind=db.get_bind(), autocommit=False, autoflush=False, expire_on_commit=False
        )
        background_tasks.add_task(
            _run_feature_extraction_job,
            bg_factory,
            job.id,
            aoi.id,
            payload.resolution_m,
            payload.dem_asset_id,
            payload.include_geology,
            settings,
        )

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


@router.get("/aois/{aoi_id}/manifests", response_model=list[FeatureManifestResponse])
def list_aoi_feature_manifests(
    aoi_id: str,
    db: Session = Depends(get_db),
) -> list[FeatureManifestResponse]:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")
    manifests = FeatureManifestRepository(db).list_for_aoi(aoi_id)
    return [_manifest_to_response(m) for m in manifests]


@router.get("/manifests/{manifest_id}", response_model=FeatureManifestResponse)
def get_feature_manifest(
    manifest_id: str,
    db: Session = Depends(get_db),
) -> FeatureManifestResponse:
    m = FeatureManifestRepository(db).get(manifest_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature manifest not found")
    return _manifest_to_response(m)


@router.get("/manifests/{manifest_id}/overlay.json", response_model=FeatureOverlayDescriptorResponse)
def get_feature_overlay_descriptor(
    manifest_id: str,
    feature_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FeatureOverlayDescriptorResponse:
    m = FeatureManifestRepository(db).get(manifest_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature manifest not found")
    if feature_name not in (m.feature_names or []):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature '{feature_name}' not present in manifest",
        )
    stack_path = _resolve_manifest_stack(m, settings)
    with rasterio.open(stack_path) as src:
        b = src.bounds
        xs = [b.left, b.right, b.right, b.left]
        ys = [b.top, b.top, b.bottom, b.bottom]
        lons, lats = warp_transform(src.crs, "EPSG:4326", xs, ys)
        corners = [[round(float(lon), 6), round(float(lat), 6)] for lon, lat in zip(lons, lats, strict=True)]

    fstats = ((m.manifest_json or {}).get("feature_stats") or {}).get(feature_name) or {}
    return FeatureOverlayDescriptorResponse(
        manifest_id=m.id,
        feature_name=feature_name,
        min=fstats.get("min"),
        max=fstats.get("max"),
        mean=fstats.get("mean"),
        valid_pct=fstats.get("valid_pct"),
        nodata_value=m.nodata_value,
        wgs84_corners=corners,
        image_url=f"/api/v1/features/manifests/{m.id}/overlay.png?feature_name={feature_name}",
    )


@router.get("/manifests/{manifest_id}/overlay.png")
def render_feature_overlay_png(
    manifest_id: str,
    feature_name: str = Query(..., min_length=1),
    max_dim: int = Query(default=256, ge=32, le=512),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    m = FeatureManifestRepository(db).get(manifest_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature manifest not found")
    names = m.feature_names or []
    if feature_name not in names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature '{feature_name}' not present in manifest",
        )
    band_idx = names.index(feature_name) + 1
    stack_path = _resolve_manifest_stack(m, settings)

    with rasterio.open(stack_path) as src:
        scale = min(1.0, max_dim / max(src.width, src.height))
        out_w = max(1, round(src.width * scale))
        out_h = max(1, round(src.height * scale))
        arr = src.read(
            band_idx,
            out_shape=(out_h, out_w),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

    valid = np.isfinite(arr) & (arr != m.nodata_value)
    rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    if np.any(valid):
        vals = arr[valid]
        lo = float(np.percentile(vals, 2))
        hi = float(np.percentile(vals, 98))
        if hi <= lo:
            norm = np.full(arr.shape, 0.5, dtype=np.float32)
        else:
            norm = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
        rgb = _apply_colormap(norm)
        rgba[..., :3] = rgb
        rgba[valid, 3] = 205

    png_bytes = _encode_rgba_png(rgba)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/aois/{aoi_id}/coverage", response_model=AOICoverageResponse)
def get_aoi_data_coverage(
    aoi_id: str,
    db: Session = Depends(get_db),
) -> AOICoverageResponse:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    occs_all = MineralOccurrenceRepository(db).find_in_aoi(aoi, ml_trainable_only=False)
    occs_ml = MineralOccurrenceRepository(db).find_in_aoi(aoi, ml_trainable_only=True)
    units = GeologicalUnitRepository(db).find_in_aoi(aoi)
    rasters = RasterAssetRepository(db).list_for_aoi(aoi.id)
    downloaded = [r for r in rasters if r.download_status == "downloaded"]
    qa_repo = QuarantineAndQualityRepository(db)
    reports = qa_repo.list_reports_for_aoi(aoi.id)
    quarantined = qa_repo.list_quarantined_for_aoi(aoi.id, limit=500)
    manifests = FeatureManifestRepository(db).list_for_aoi(aoi.id)

    missing_layers: list[str] = []
    warnings: list[str] = [SCIENTIFIC_BIAS_WARNING]

    if not occs_ml:
        missing_layers.append("ML-eligible mineral occurrences (positive labels)")
        warnings.append("No ML-eligible mineral occurrences exist inside this AOI yet.")
    if not units:
        missing_layers.append("Geological bedrock polygons (Macrostrat / GSI)")
    if not downloaded:
        missing_layers.append("Downloaded local raster assets (e.g., Copernicus DEM / Sentinel-2)")
    missing_layers.append("Verified structural fault lines & intrusive contacts (no national open feed ingested)")
    missing_layers.append("Systematic geochemical survey grids & explicit drill-tested barren negatives")

    if manifests:
        latest_warns = manifests[0].warnings_json or []
        for w in latest_warns:
            if w not in warnings:
                warnings.append(w)

    return AOICoverageResponse(
        aoi_id=aoi.id,
        aoi_name=aoi.name,
        processing_epsg=aoi.processing_epsg,
        area_km2=aoi.area_km2,
        occurrence_total=len(occs_all),
        occurrence_ml_trainable=len(occs_ml),
        occurrence_reference_only=max(0, len(occs_all) - len(occs_ml)),
        quarantined_count=len(quarantined),
        quality_reports_count=len(reports),
        geological_units_count=len(units),
        raster_scenes_discovered=len(rasters),
        raster_scenes_downloaded=len(downloaded),
        feature_manifests_count=len(manifests),
        latest_manifest_id=manifests[0].id if manifests else None,
        missing_layers=missing_layers,
        warnings=warnings,
    )
