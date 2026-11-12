"""Memory-aware raster inspection, reprojection, resampling, and canonical grid alignment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.merge import merge as rasterio_merge
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from app.storage.manager import managed_temp_dir

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
    nodata_override: float | None = None,
) -> np.ndarray:
    """Open a local GeoTIFF and reproject the chosen band into the canonical AOI grid."""
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            raise ValueError(f"Raster '{raster_path.name}' lacks CRS metadata")
        arr = src.read(band_index)
        effective_nodata = src.nodata if src.nodata is not None else nodata_override
        return reproject_array_to_grid(
            source_array=arr,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=effective_nodata,
            grid=grid,
            resampling=resampling,
        )


@dataclass(frozen=True)
class MosaicResult:
    """Result metadata from bounded DEM cross-tile mosaicking."""

    mosaic_path: Path
    source_crs_epsg: int | None
    native_resolution: tuple[float, float]
    tile_count: int
    reprojected_tile_count: int
    width: int
    height: int
    nodata: float
    warnings: list[str]


def mosaic_compatible_dem_tiles(
    *,
    tile_paths: list[Path],
    output_path: Path,
    aoi_bbox_wgs84: tuple[float, float, float, float] | None = None,
    nodata: float = DEFAULT_NODATA,
    max_resolution_ratio: float = 2.5,
) -> MosaicResult:
    """Validate, optionally align CRS, mosaic compatible DEM tiles, and clip to AOI bounds.

    Never fabricates or interpolates elevations into areas not covered by valid tile pixels.
    """
    if not tile_paths:
        raise ValueError("At least one DEM tile path is required for mosaicking.")

    metas: list[dict[str, Any]] = []
    for p in tile_paths:
        if not p.exists():
            raise FileNotFoundError(f"DEM tile missing on disk: {p}")
        with rasterio.open(p) as src:
            if src.crs is None:
                raise ValueError(f"DEM tile '{p.name}' lacks CRS metadata.")
            metas.append(
                {
                    "path": p,
                    "crs": src.crs,
                    "epsg": src.crs.to_epsg(),
                    "res_x": abs(float(src.res[0])),
                    "res_y": abs(float(src.res[1])),
                    "bounds": src.bounds,
                    "nodata": src.nodata,
                }
            )

    primary_crs = metas[0]["crs"]
    primary_epsg = metas[0]["epsg"]
    warnings: list[str] = []
    reprojected_count = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_mosaic_path = output_path.with_suffix(".tif.tmp")
    if tmp_mosaic_path.exists():
        tmp_mosaic_path.unlink(missing_ok=True)

    with managed_temp_dir("dem_mosaic_") as tmpdir:
        merge_sources: list[Path] = []
        norm_res_list: list[tuple[float, float]] = []

        for idx, meta in enumerate(metas):
            tile_path: Path = meta["path"]
            if meta["crs"] != primary_crs:
                if primary_epsg is None:
                    raise ValueError(
                        f"Cannot harmonize mixed CRSs across DEM tiles without primary EPSG ({meta['crs']})."
                    )
                reproj_path = tmpdir / f"reproj_{idx}_{tile_path.name}"
                reproject_raster_to_utm(
                    src_path=tile_path,
                    dst_path=reproj_path,
                    dst_epsg=int(primary_epsg),
                    resampling=Resampling.bilinear,
                )
                with rasterio.open(reproj_path) as rds:
                    norm_res_list.append((abs(float(rds.res[0])), abs(float(rds.res[1]))))
                merge_sources.append(reproj_path)
                reprojected_count += 1
            else:
                norm_res_list.append((meta["res_x"], meta["res_y"]))
                merge_sources.append(tile_path)

        if reprojected_count > 0:
            warnings.append(
                f"Reprojected {reprojected_count} DEM tile(s) to match primary CRS ({primary_crs}) before mosaicking."
            )

        # Validate spatial resolution compatibility across tiles
        xs = [r[0] for r in norm_res_list if r[0] > 0]
        ys = [r[1] for r in norm_res_list if r[1] > 0]
        if not xs or not ys:
            raise ValueError("Invalid zero pixel resolution detected in DEM tile(s).")
        if (max(xs) / min(xs) > max_resolution_ratio) or (max(ys) / min(ys) > max_resolution_ratio):
            raise ValueError(
                f"Incompatible DEM pixel resolutions across tiles ({norm_res_list}); refusing mosaic."
            )

        # Normalize per-tile nodata into tmp float32 inputs so None nodata / NaNs never turn into zeros
        clean_inputs: list[Path] = []
        for idx, src_p in enumerate(merge_sources):
            with rasterio.open(src_p) as src:
                arr = src.read(1).astype(np.float32)
                if src.nodata is not None:
                    arr = np.where(arr == src.nodata, nodata, arr)
                arr = np.where(np.isfinite(arr), arr, nodata).astype(np.float32)
                clean_p = tmpdir / f"clean_{idx}.tif"
                prof = src.profile.copy()
                prof.update(
                    driver="GTiff",
                    count=1,
                    dtype="float32",
                    nodata=nodata,
                    compress="deflate",
                )
                with rasterio.open(clean_p, "w", **prof) as dst:
                    dst.write(arr, 1)
                clean_inputs.append(clean_p)

        clip_bounds: tuple[float, float, float, float] | None = None
        if aoi_bbox_wgs84 is not None:
            minx, miny, maxx, maxy = transform_bounds(
                "EPSG:4326", primary_crs, *aoi_bbox_wgs84, densify_pts=21
            )
            pad_x = max(xs) * 2.0
            pad_y = max(ys) * 2.0
            clip_bounds = (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)

        opened = [rasterio.open(p) for p in clean_inputs]
        try:
            mosaic_arr, mosaic_transform = rasterio_merge(
                opened,
                bounds=clip_bounds,
                nodata=nodata,
                resampling=Resampling.bilinear,
            )
            out_profile = opened[0].profile.copy()
        finally:
            for ds in opened:
                ds.close()

        out_h, out_w = mosaic_arr.shape[1], mosaic_arr.shape[2]
        out_profile.update(
            driver="GTiff",
            height=out_h,
            width=out_w,
            count=1,
            dtype="float32",
            transform=mosaic_transform,
            crs=primary_crs,
            nodata=nodata,
            compress="deflate",
        )
        with rasterio.open(tmp_mosaic_path, "w", **out_profile) as dst:
            dst.write(mosaic_arr[0].astype(np.float32), 1)
        tmp_mosaic_path.replace(output_path)

    return MosaicResult(
        mosaic_path=output_path,
        source_crs_epsg=int(primary_epsg) if primary_epsg else None,
        native_resolution=(float(min(xs)), float(min(ys))),
        tile_count=len(tile_paths),
        reprojected_tile_count=reprojected_count,
        width=int(out_w),
        height=int(out_h),
        nodata=float(nodata),
        warnings=warnings,
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

