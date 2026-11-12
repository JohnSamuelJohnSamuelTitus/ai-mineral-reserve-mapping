"""Memory-aware raster inspection, reprojection, resampling, and canonical grid alignment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

DEFAULT_NODATA = -9999.0


@dataclass(frozen=True)
class TargetGridSpec:
    """Canonical projected grid definition for aligning all AOI features."""

    crs_epsg: int
    resolution_m: float
    width: int
    height: int
    transform: Affine
    bounds_metric: tuple[float, float, float, float]
    nodata: float = DEFAULT_NODATA


def build_aoi_target_grid(
    *,
    bbox_wgs84: tuple[float, float, float, float],
    target_epsg: int,
    resolution_m: float = 100.0,
    max_dimension_px: int = 4096,
) -> TargetGridSpec:
    """Construct a metric UTM raster grid enclosing the WGS84 AOI bounding box."""
    if resolution_m <= 0:
        raise ValueError("resolution_m must be strictly positive")
    minx, miny, maxx, maxy = transform_bounds(
        "EPSG:4326", f"EPSG:{target_epsg}", *bbox_wgs84, densify_pts=21
    )
    width = max(1, int(np.ceil((maxx - minx) / resolution_m)))
    height = max(1, int(np.ceil((maxy - miny) / resolution_m)))
    if width > max_dimension_px or height > max_dimension_px:
        raise ValueError(
            f"Requested grid ({width}x{height} px at {resolution_m}m) exceeds RAM safety cap "
            f"of {max_dimension_px}px per axis; increase resolution_m or shrink AOI."
        )
    transform = from_origin(minx, maxy, resolution_m, resolution_m)
    snapped_maxx = minx + width * resolution_m
    snapped_miny = maxy - height * resolution_m
    return TargetGridSpec(
        crs_epsg=target_epsg,
        resolution_m=resolution_m,
        width=width,
        height=height,
        transform=transform,
        bounds_metric=(minx, snapped_miny, snapped_maxx, maxy),
    )


def inspect_raster_metadata(raster_path: Path) -> dict[str, Any]:
    """Read raster CRS, resolution, bounds, band count, and nodata stats without loading all pixels."""
    if not raster_path.exists():
        raise FileNotFoundError(f"Raster not found: {raster_path}")
    with rasterio.open(raster_path) as src:
        epsg = src.crs.to_epsg() if src.crs else None
        is_geographic = bool(src.crs and src.crs.is_geographic)
        res_x, res_y = src.res
        bounds = src.bounds
        stats: dict[str, Any] | None = None

        # Compute summary stats cleanly via native block windows (low RAM)
        total_valid = 0
        running_sum = 0.0
        min_val: float | None = None
        max_val: float | None = None
        nodata = src.nodata
        for _, win in src.block_windows(1):
            block = src.read(1, window=win).astype(np.float64)
            mask = np.isfinite(block)
            if nodata is not None:
                mask &= block != nodata
            if np.any(mask):
                valid = block[mask]
                total_valid += int(valid.size)
                running_sum += float(np.sum(valid))
                b_min = float(np.min(valid))
                b_max = float(np.max(valid))
                min_val = b_min if min_val is None else min(min_val, b_min)
                max_val = b_max if max_val is None else max(max_val, b_max)

        total_px = int(src.width * src.height)
        stats = {
            "valid_pixels": total_valid,
            "valid_pct": round((total_valid / max(total_px, 1)) * 100.0, 2),
            "min": round(min_val, 4) if min_val is not None else None,
            "max": round(max_val, 4) if max_val is not None else None,
            "mean": round(running_sum / total_valid, 4) if total_valid > 0 else None,
        }

        return {
            "path": str(raster_path),
            "driver": src.driver,
            "crs": str(src.crs) if src.crs else None,
            "crs_epsg": int(epsg) if epsg else None,
            "is_geographic": is_geographic,
            "width": int(src.width),
            "height": int(src.height),
            "band_count": int(src.count),
            "dtypes": list(src.dtypes),
            "pixel_size": [float(res_x), float(res_y)],
            "bounds": [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)],
            "nodata": nodata,
            "band1_stats": stats,
        }


def reproject_array_to_grid(
    *,
    source_array: np.ndarray,
    src_transform: Affine,
    src_crs: Any,
    src_nodata: float | None,
    grid: TargetGridSpec,
    resampling: Resampling = Resampling.bilinear,
) -> np.ndarray:
    """Reproject a 2D array into the target float32 AOI grid with standardized nodata."""
    if source_array.ndim != 2:
        raise ValueError("Expected 2D numpy array for grid alignment")

    src_f32 = source_array.astype(np.float32, copy=True)
    effective_src_nodata = DEFAULT_NODATA if src_nodata is None else float(src_nodata)
    if src_nodata is None:
        src_f32[~np.isfinite(src_f32)] = DEFAULT_NODATA

    dst = np.full((grid.height, grid.width), grid.nodata, dtype=np.float32)
    reproject(
        source=src_f32,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=effective_src_nodata,
        dst_transform=grid.transform,
        dst_crs=f"EPSG:{grid.crs_epsg}",
        dst_nodata=grid.nodata,
        resampling=resampling,
    )
    return dst


def align_raster_band_to_grid(
    raster_path: Path,
    *,
    band_index: int = 1,
    grid: TargetGridSpec,
    resampling: Resampling = Resampling.bilinear,
) -> np.ndarray:
    """Open a local GeoTIFF and reproject the chosen band into the canonical AOI grid."""
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            raise ValueError(f"Raster '{raster_path.name}' lacks CRS metadata")
        arr = src.read(band_index)
        return reproject_array_to_grid(
            source_array=arr,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            grid=grid,
            resampling=resampling,
        )


def reproject_raster_to_utm(
    *,
    src_path: Path,
    dst_path: Path,
    dst_epsg: int,
    resolution_m: float | None = None,
    resampling: Resampling = Resampling.bilinear,
) -> Path:
    """Reproject an entire GeoTIFF cleanly into a projected metric CRS."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        if src.crs is None:
            raise ValueError("Source raster lacks CRS")
        dst_crs = f"EPSG:{dst_epsg}"
        transform, width, height = calculate_default_transform(
            src.crs,
            dst_crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=resolution_m,
        )
        profile = src.profile.copy()
        profile.update(
            crs=dst_crs,
            transform=transform,
            width=width,
            height=height,
            compress="deflate",
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            for band_i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band_i),
                    destination=rasterio.band(dst, band_i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=resampling,
                )
    return dst_path

