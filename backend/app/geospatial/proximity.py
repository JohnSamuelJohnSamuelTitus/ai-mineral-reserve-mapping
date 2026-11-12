"""Geological distance & lithology rasterization features with strict anti-fabrication rules."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point, shape
from shapely.ops import transform as shapely_transform

from app.db.models import GeologicalUnit, MineralOccurrence
from app.geospatial.raster_ops import DEFAULT_NODATA, TargetGridSpec


def _metric_distance_to_geometries(
    geoms_metric: list[Any],
    *,
    grid: TargetGridSpec,
) -> np.ndarray | None:
    """Compute exact Euclidean distance (meters) across the grid from non-empty metric geometries."""
    if not geoms_metric:
        return None
    presence = rasterize(
        [(g, 1) for g in geoms_metric],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    if not np.any(presence == 1):
        # Geometry lies outside grid bounds; fall back to exact center-to-geometry distance array
        xs = grid.transform.c + (np.arange(grid.width) + 0.5) * grid.transform.a
        ys = grid.transform.f + (np.arange(grid.height) + 0.5) * grid.transform.e
        xx, yy = np.meshgrid(xs, ys)
        out = np.full((grid.height, grid.width), np.inf, dtype=np.float64)
        for g in geoms_metric:
            if g.geom_type == "Point":
                dist = np.hypot(xx - g.x, yy - g.y)
                out = np.minimum(out, dist)
        return np.where(np.isfinite(out), out, DEFAULT_NODATA).astype(np.float32)

    dist_px = distance_transform_edt(presence == 0)
    return (dist_px * grid.resolution_m).astype(np.float32)


def compute_geological_features(
    *,
    grid: TargetGridSpec,
    occurrences: list[MineralOccurrence],
    geological_units: list[GeologicalUnit],
    verified_fault_geometries_wgs84: list[dict[str, Any]] | None = None,
    verified_intrusive_geometries_wgs84: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]], list[str]]:
    """Compute metric distance features and lithology encodings without fabricating missing layers."""
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{grid.crs_epsg}", always_xy=True)

    def _to_metric(geom_wgs84: Any) -> Any:
        return shapely_transform(transformer.transform, geom_wgs84)

    features: dict[str, np.ndarray] = {}
    docs: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1. Distance to known ML-eligible mineral occurrences
    occ_points_m = [_to_metric(Point(o.lon, o.lat)) for o in occurrences]
    dist_occ = _metric_distance_to_geometries(occ_points_m, grid=grid)
    if dist_occ is not None:
        features["dist_to_occurrence_m"] = dist_occ
        docs.append(
            {
                "name": "dist_to_occurrence_m",
                "formula": f"Euclidean metric distance in EPSG:{grid.crs_epsg}",
                "native_resolution_m": grid.resolution_m,
                "source_count": len(occ_points_m),
            }
        )
    else:
        warnings.append("No mineral occurrences available in AOI; skipped dist_to_occurrence_m.")

    # 2. Geological unit category & contact boundaries ONLY when distinct polygons exist
    if geological_units:
        unit_shapes_m = []
        lith_classes: list[str] = []
        for idx, unit in enumerate(geological_units, start=1):
            poly = shape(json.loads(unit.geom_geojson))
            poly_m = _to_metric(poly)
            unit_shapes_m.append((poly_m, idx))
            if unit.lithology_class:
                lith_classes.extend(unit.lithology_class)

        unit_id_raster = rasterize(
            unit_shapes_m,
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            fill=0,
            dtype=np.int32,
        )
        features["geology_unit_index"] = unit_id_raster.astype(np.float32)
        docs.append(
            {
                "name": "geology_unit_index",
                "formula": "Categorical index rasterized from verified Macrostrat/GSI unit geometries",
                "native_resolution_m": grid.resolution_m,
                "distinct_units": len(geological_units),
                "lithologies_observed": sorted(set(lith_classes)),
            }
        )

        # Contact distance only scientifically meaningful when >=2 adjacent unit polygons exist
        if len(geological_units) >= 2:
            boundaries = [geom.boundary for geom, _ in unit_shapes_m]
            dist_contact = _metric_distance_to_geometries(boundaries, grid=grid)
            if dist_contact is not None:
                features["dist_to_contact_m"] = dist_contact
                docs.append(
                    {
                        "name": "dist_to_contact_m",
                        "formula": "Metric distance to polygon unit contacts",
                        "native_resolution_m": grid.resolution_m,
                    }
                )
        else:
            warnings.append(
                "Only <=1 geological unit polygon covers this AOI; lithological contact geometry unavailable (not fabricated)."
            )
    else:
        warnings.append("No geological units ingested for AOI; skipped geology features.")

    # 3. Verified fault / intrusive layers ONLY when explicitly supplied
    if verified_fault_geometries_wgs84:
        fault_m = [_to_metric(shape(g)) for g in verified_fault_geometries_wgs84]
        dist_fault = _metric_distance_to_geometries(fault_m, grid=grid)
        if dist_fault is not None:
            features["dist_to_fault_m"] = dist_fault
            docs.append(
                {
                    "name": "dist_to_fault_m",
                    "formula": "Euclidean distance to verified structural fault traces",
                    "native_resolution_m": grid.resolution_m,
                }
            )
    else:
        warnings.append("Missing layer: verified geological fault dataset unavailable (never fabricated).")

    if verified_intrusive_geometries_wgs84:
        intr_m = [_to_metric(shape(g)) for g in verified_intrusive_geometries_wgs84]
        dist_intr = _metric_distance_to_geometries(intr_m, grid=grid)
        if dist_intr is not None:
            features["dist_to_intrusive_m"] = dist_intr
            docs.append(
                {
                    "name": "dist_to_intrusive_m",
                    "formula": "Euclidean distance to verified intrusive bodies",
                    "native_resolution_m": grid.resolution_m,
                }
            )
    else:
        warnings.append("Missing layer: verified intrusive body polygons unavailable (never fabricated).")

    return features, docs, warnings

