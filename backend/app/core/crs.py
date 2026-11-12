"""Geospatial geometry validation, geodesic area, and UTM CRS utilities."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from pyproj import Geod, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry

_WGS84_GEOD = Geod(ellps="WGS84")


class GeospatialValidationError(ValueError):
    """Raised when input GeoJSON/coordinates violate spatial constraints."""


@dataclass(frozen=True)
class NormalizedAOIGeometry:
    """Validated WGS84 MultiPolygon with derived bounding box, centroid, UTM EPSG, and area."""

    multipolygon: MultiPolygon
    geojson_str: str
    wkt: str
    bbox: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    centroid_lon: float
    centroid_lat: float
    processing_epsg: int
    area_km2: float


def choose_utm_epsg(lon: float, lat: float) -> int:
    """Select the WGS84 UTM EPSG code (326xx north / 327xx south) for a lon/lat coordinate."""
    if not (-180.0 <= lon <= 180.0) or not (-80.0 <= lat <= 84.0):
        raise GeospatialValidationError(
            f"Coordinates ({lon}, {lat}) outside valid UTM latitude/longitude range."
        )
    zone = math.floor((lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 + zone) if lat >= 0.0 else (32700 + zone)


def compute_geodesic_area_km2(geom: BaseGeometry) -> float:
    """Compute exact WGS84 ellipsoidal area in square kilometers."""
    area_m2, _ = _WGS84_GEOD.geometry_area_perimeter(geom)
    return round(abs(area_m2) / 1_000_000.0, 4)


def transform_bbox(
    bbox: tuple[float, float, float, float],
    src_epsg: int,
    dst_epsg: int,
) -> tuple[float, float, float, float]:
    """Reproject a bounding box (min_x, min_y, max_x, max_y) between coordinate systems."""
    if src_epsg == dst_epsg:
        return bbox
    minx, miny, maxx, maxy = bbox
    transformer = Transformer.from_crs(
        f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True
    )
    xs, ys = transformer.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    return (min(xs), min(ys), max(xs), max(ys))


def validate_and_normalize_aoi_geojson(
    geojson_obj: dict[str, Any],
    max_area_km2: float = 250_000.0,
) -> NormalizedAOIGeometry:
    """Validate GeoJSON Polygon/MultiPolygon in WGS84 and compute metric metadata."""
    if not isinstance(geojson_obj, dict) or "type" not in geojson_obj:
        raise GeospatialValidationError("AOI geometry must be a valid GeoJSON object.")

    geom_type = geojson_obj.get("type")
    if geom_type == "Feature":
        inner = geojson_obj.get("geometry")
        if not isinstance(inner, dict):
            raise GeospatialValidationError("GeoJSON Feature must contain a geometry object.")
        geojson_obj = inner
        geom_type = geojson_obj.get("type")

    if geom_type not in ("Polygon", "MultiPolygon"):
        raise GeospatialValidationError(
            f"AOI geometry must be Polygon or MultiPolygon, got '{geom_type}'."
        )

    try:
        geom = shape(geojson_obj)
    except Exception as exc:
        raise GeospatialValidationError(f"Malformed GeoJSON coordinates: {exc}") from exc

    if geom.is_empty:
        raise GeospatialValidationError("AOI geometry cannot be empty.")
    if not geom.is_valid:
        raise GeospatialValidationError("AOI geometry is invalid or self-intersecting.")

    min_lon, min_lat, max_lon, max_lat = geom.bounds
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise GeospatialValidationError("AOI longitudes must lie within [-180, 180].")
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise GeospatialValidationError("AOI latitudes must lie within [-90, 90].")

    multipoly = MultiPolygon([geom]) if isinstance(geom, Polygon) else geom
    if not isinstance(multipoly, MultiPolygon):
        raise GeospatialValidationError("AOI geometry could not be normalized to MultiPolygon.")

    area_km2 = compute_geodesic_area_km2(multipoly)
    if area_km2 <= 0.0:
        raise GeospatialValidationError("AOI area must be greater than 0 km^2.")
    if area_km2 > max_area_km2:
        raise GeospatialValidationError(
            f"AOI area ({area_km2:.2f} km^2) exceeds max allowed ({max_area_km2:.0f} km^2)."
        )

    centroid = multipoly.centroid
    processing_epsg = choose_utm_epsg(centroid.x, centroid.y)
    normalized_mapping = mapping(multipoly)

    return NormalizedAOIGeometry(
        multipolygon=multipoly,
        geojson_str=json.dumps(normalized_mapping),
        wkt=multipoly.wkt,
        bbox=(min_lon, min_lat, max_lon, max_lat),
        centroid_lon=round(centroid.x, 6),
        centroid_lat=round(centroid.y, 6),
        processing_epsg=processing_epsg,
        area_km2=area_km2,
    )


def bbox_to_geojson_polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict[str, Any]:
    """Create a GeoJSON Polygon dictionary from WGS84 bounding coordinates."""
    if min_lon >= max_lon or min_lat >= max_lat:
        raise GeospatialValidationError("Bounding box requires min < max for both lon and lat.")
    return mapping(box(min_lon, min_lat, max_lon, max_lat))
