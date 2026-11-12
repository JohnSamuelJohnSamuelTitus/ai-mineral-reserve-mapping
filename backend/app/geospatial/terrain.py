"""Projected metric terrain derivative calculations from DEM rasters."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.geospatial.raster_ops import DEFAULT_NODATA


@dataclass(frozen=True)
class TerrainDerivatives:
    elevation_m: np.ndarray
    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    hillshade: np.ndarray
    tri: np.ndarray
    tpi: np.ndarray
    curvature: np.ndarray
    drainage_proxy: np.ndarray


def compute_terrain_derivatives(
    dem_m: np.ndarray,
    *,
    pixel_size_m: float,
    is_projected_metric: bool = True,
    nodata: float = DEFAULT_NODATA,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
) -> TerrainDerivatives:
    """Compute slope, aspect, hillshade, TRI, TPI, curvature, and drainage proxy in metric CRS.

    Raises ValueError if `is_projected_metric` is False to guarantee terrain derivatives
    are never computed directly in latitude/longitude degrees.
    """
    if not is_projected_metric:
        raise ValueError(
            "Terrain derivatives MUST be computed on a projected metric CRS (meters), "
            "not geographic latitude/longitude degrees."
        )
    if pixel_size_m <= 0:
        raise ValueError("pixel_size_m must be strictly positive")
    if dem_m.ndim != 2 or dem_m.shape[0] < 3 or dem_m.shape[1] < 3:
        raise ValueError("DEM array must be 2D with shape >= (3, 3)")

    z = dem_m.astype(np.float64, copy=True)
    valid = np.isfinite(z) & (z != nodata)

    # Fill isolated invalid cells temporarily by nearest valid neighbor for stencil stability,
    # then re-apply exact nodata mask on every output layer.
    fill_val = float(np.median(z[valid])) if np.any(valid) else 0.0
    z_work = np.where(valid, z, fill_val)
    zp = np.pad(z_work, pad_width=1, mode="edge")

    # 3x3 Horn stencil neighborhood
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, e, f = zp[1:-1, :-2], zp[1:-1, 1:-1], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]

    dz_dx = ((c + 2.0 * f + i) - (a + 2.0 * d + g)) / (8.0 * pixel_size_m)
    dz_dy = ((g + 2.0 * h + i) - (a + 2.0 * b + c)) / (8.0 * pixel_size_m)

    slope_rad = np.arctan(np.hypot(dz_dx, dz_dy))
    slope_deg_f64 = np.degrees(slope_rad)

    # Standard GIS compass aspect (degrees clockwise from North, 0..360)
    aspect_math = np.degrees(np.arctan2(dz_dy, -dz_dx))
    aspect_compass = np.where(
        (dz_dx == 0.0) & (dz_dy == 0.0),
        0.0,
        np.where(aspect_math < 0.0, 90.0 - aspect_math, np.where(aspect_math > 90.0, 450.0 - aspect_math, 90.0 - aspect_math)),
    ) % 360.0

    # Hillshade [0, 255]
    zenith_rad = np.radians(90.0 - altitude_deg)
    az_math_rad = np.radians((360.0 - azimuth_deg + 90.0) % 360.0)
    aspect_rad = np.arctan2(dz_dy, -dz_dx)
    hs = 255.0 * (
        np.cos(zenith_rad) * np.cos(slope_rad)
        + np.sin(zenith_rad) * np.sin(slope_rad) * np.cos(az_math_rad - aspect_rad)
    )
    hs = np.clip(hs, 0.0, 255.0)

    # Riley Terrain Ruggedness Index (TRI): RMS of elevation diffs across 8 neighbors
    neighbors = [a, b, c, d, f, g, h, i]
    tri_f64 = np.sqrt(sum((n - e) ** 2 for n in neighbors) / 8.0)

    # Topographic Position Index (TPI): center minus mean of 8 neighbors
    mean_8 = sum(neighbors) / 8.0
    tpi_f64 = e - mean_8

    # Laplacian curvature proxy ((d2z/dx2 + d2z/dy2) * 100)
    d2x = (d - 2.0 * e + f) / (pixel_size_m**2)
    d2y = (b - 2.0 * e + h) / (pixel_size_m**2)
    curv_f64 = -(d2x + d2y) * 100.0

    # Drainage convergence proxy: high when TPI is concave/negative and slope is gentle
    drain_f64 = np.maximum(0.0, -tpi_f64) / (np.tan(slope_rad) + 0.05)

    def _mask_out(arr: np.ndarray) -> np.ndarray:
        res = np.full(arr.shape, nodata, dtype=np.float32)
        res[valid] = arr[valid].astype(np.float32)
        return res

    elev_out = np.full(z.shape, nodata, dtype=np.float32)
    elev_out[valid] = z[valid].astype(np.float32)

    return TerrainDerivatives(
        elevation_m=elev_out,
        slope_deg=_mask_out(slope_deg_f64),
        aspect_deg=_mask_out(aspect_compass),
        hillshade=_mask_out(hs),
        tri=_mask_out(tri_f64),
        tpi=_mask_out(tpi_f64),
        curvature=_mask_out(curv_f64),
        drainage_proxy=_mask_out(drain_f64),
    )

