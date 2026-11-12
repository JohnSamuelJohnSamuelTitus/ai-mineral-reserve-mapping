"""Memory- and disk-aware AOI-windowed COG downloader using Rasterio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

from app.core.logging import get_logger
from app.storage.manager import (
    StorageLimitError,
    check_free_disk_space,
    resolve_safe_path,
    sanitize_filename,
    sha256_file,
    validate_file_size,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class ClippedDownloadResult:
    local_path: Path
    checksum_sha256: str
    crs_epsg: int | None
    width: int
    height: int
    count: int
    size_mb: float
    nodata: float | None


def download_cog_window_for_aoi(
    *,
    asset_url: str,
    aoi_bbox_wgs84: tuple[float, float, float, float],
    output_dir: Path,
    aoi_id: str,
    filename_stem: str,
    max_download_mb: float = 150.0,
    min_free_disk_gb: float = 2.0,
) -> ClippedDownloadResult:
    """Read ONLY the AOI-intersecting pixel window from a COG URL/path and write a GeoTIFF."""
    check_free_disk_space(output_dir, min_free_gb=min_free_disk_gb, required_mb=20.0)
    safe_aoi = sanitize_filename(aoi_id, fallback="aoi")
    safe_name = sanitize_filename(filename_stem, fallback="scene") + ".tif"
    target_path = resolve_safe_path(output_dir, safe_aoi, safe_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tif.tmp")

    vsi_env: dict[str, Any] = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.TIF,.TIFF",
        "VSI_CACHE": "TRUE",
        "GDAL_HTTP_TIMEOUT": "20",
        "GDAL_HTTP_MAX_RETRY": "2",
    }

    try:
        with rasterio.Env(**vsi_env), rasterio.open(asset_url) as src:
            if src.crs is None:
                raise ValueError("Source raster has no CRS; refusing unreferenced download")

            src_bounds = transform_bounds("EPSG:4326", src.crs, *aoi_bbox_wgs84, densify_pts=21)
            win = from_bounds(*src_bounds, transform=src.transform)
            win = win.round_offsets().round_lengths()

            # Clamp window strictly to raster extent
            col_off = max(0, int(win.col_off))
            row_off = max(0, int(win.row_off))
            max_w = int(src.width) - col_off
            max_h = int(src.height) - row_off
            width = min(max_w, int(win.width))
            height = min(max_h, int(win.height))
            if width <= 0 or height <= 0:
                raise ValueError("AOI bbox does not intersect the remote raster extent")

            clamped_win = Window(col_off=col_off, row_off=row_off, width=width, height=height)
            dtype_bytes = np.dtype(src.dtypes[0]).itemsize
            est_bytes = width * height * src.count * dtype_bytes
            validate_file_size(est_bytes, max_mb=max_download_mb)

            data = src.read(window=clamped_win)
            out_transform = src.window_transform(clamped_win)
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                height=height,
                width=width,
                transform=out_transform,
                compress="deflate",
                tiled=True,
                blockxsize=min(256, max(16, (width // 16) * 16)),
                blockysize=min(256, max(16, (height // 16) * 16)),
            )
            with rasterio.open(tmp_path, "w", **profile) as dst:
                dst.write(data)

        actual_bytes = tmp_path.stat().st_size
        validate_file_size(actual_bytes, max_mb=max_download_mb)
        tmp_path.replace(target_path)
        checksum = sha256_file(target_path)
        epsg = src.crs.to_epsg() if src.crs else None
        logger.info("Downloaded windowed COG %s (%.2f MB)", target_path.name, actual_bytes / (1024**2))
        return ClippedDownloadResult(
            local_path=target_path,
            checksum_sha256=checksum,
            crs_epsg=int(epsg) if epsg else None,
            width=width,
            height=height,
            count=data.shape[0],
            size_mb=round(actual_bytes / (1024**2), 4),
            nodata=src.nodata,
        )
    except (StorageLimitError, Exception):
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
