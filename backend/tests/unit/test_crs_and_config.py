"""Unit tests for CRS transformations, geometry validation, caching, config, and logging."""

from __future__ import annotations

import logging

import pytest
from shapely.geometry import box

from app.core.cache import InMemoryTTLCache
from app.core.config import Settings
from app.core.crs import (
    GeospatialValidationError,
    choose_utm_epsg,
    compute_geodesic_area_km2,
    transform_bbox,
    validate_and_normalize_aoi_geojson,
)
from app.core.logging import SecretRedactingFilter


def test_choose_utm_epsg_india_and_southern_hemisphere() -> None:
    # Khetri Copper Belt, Rajasthan (~75.8E, 28.0N) -> UTM Zone 43N -> 32643
    assert choose_utm_epsg(75.8, 28.0) == 32643
    # Singhbhum Copper Belt, Jharkhand (~86.4E, 22.6N) -> UTM Zone 45N -> 32645
    assert choose_utm_epsg(86.4, 22.6) == 32645
    # Pilbara, Australia (~118.6E, -22.3S) -> UTM Zone 50S -> 32750
    assert choose_utm_epsg(118.6, -22.3) == 32750


def test_transform_bbox_roundtrip_wgs84_utm() -> None:
    wgs84_bbox = (75.7, 27.9, 75.9, 28.1)
    utm_bbox = transform_bbox(wgs84_bbox, 4326, 32643)
    assert utm_bbox[2] > utm_bbox[0] > 100_000.0
    assert utm_bbox[3] > utm_bbox[1] > 3_000_000.0
    # Axis-aligned UTM bounding box expands slightly under UTM convergence, so back-projected
    # WGS84 bounds enclose the original box within ~0.002 degrees.
    back = transform_bbox(utm_bbox, 32643, 4326)
    assert back[0] <= wgs84_bbox[0] and pytest.approx(back[0], abs=2e-3) == wgs84_bbox[0]
    assert back[1] <= wgs84_bbox[1] and pytest.approx(back[1], abs=2e-3) == wgs84_bbox[1]
    assert back[2] >= wgs84_bbox[2] and pytest.approx(back[2], abs=2e-3) == wgs84_bbox[2]
    assert back[3] >= wgs84_bbox[3] and pytest.approx(back[3], abs=2e-3) == wgs84_bbox[3]

    # Single-point degenerate bbox roundtrips accurately to sub-millimeter precision
    pt_utm = transform_bbox((75.8, 28.0, 75.8, 28.0), 4326, 32643)
    pt_back = transform_bbox(pt_utm, 32643, 4326)
    assert pytest.approx(pt_back[0], abs=1e-7) == 75.8
    assert pytest.approx(pt_back[1], abs=1e-7) == 28.0


def test_geodesic_area_km2_realistic() -> None:
    # 0.1 deg x 0.1 deg near 28N ~ 9.8km x 11.1km ~ 109 km^2
    poly = box(75.7, 27.9, 75.8, 28.0)
    area = compute_geodesic_area_km2(poly)
    assert 100.0 < area < 120.0


def test_validate_aoi_rejects_malformed_geometries() -> None:
    # 1. Self-intersecting bowtie polygon
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]],
    }
    with pytest.raises(GeospatialValidationError, match="invalid or self-intersecting"):
        validate_and_normalize_aoi_geojson(bowtie)

    # 2. Non-polygon geometry
    with pytest.raises(GeospatialValidationError, match="Polygon or MultiPolygon"):
        validate_and_normalize_aoi_geojson({"type": "Point", "coordinates": [75.8, 28.0]})

    # 3. Out-of-bounds latitude
    with pytest.raises(GeospatialValidationError, match="latitudes"):
        validate_and_normalize_aoi_geojson(
            {"type": "Polygon", "coordinates": [[[75, 95], [76, 95], [76, 96], [75, 96], [75, 95]]]}
        )

    # 4. Exceeds max area
    huge = {
        "type": "Polygon",
        "coordinates": [[[70, 10], [85, 10], [85, 30], [70, 30], [70, 10]]],
    }
    with pytest.raises(GeospatialValidationError, match="exceeds max allowed"):
        validate_and_normalize_aoi_geojson(huge, max_area_km2=10_000.0)


def test_in_memory_cache_ttl_and_lru_eviction() -> None:
    cache = InMemoryTTLCache(default_ttl_seconds=60, max_entries=2)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    assert cache.get("k1") == "v1"  # promotes k1
    cache.set("k3", "v3")  # evicts k2 (LRU)
    assert cache.get("k2") is None
    assert cache.get("k1") == "v1"
    assert cache.get("k3") == "v3"
    assert cache.stats()["hits"] >= 3


def test_settings_validation_and_secret_redaction() -> None:
    with pytest.raises(ValueError, match="Unsupported database_url"):
        Settings(database_url="mysql://user:pass@localhost/db")

    filt = SecretRedactingFilter()
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET https://api.example.org?api_key=SUPER_SECRET_12345&q=copper",
        args=(),
        exc_info=None,
    )
    filt.filter(rec)
    assert "SUPER_SECRET_12345" not in rec.msg
    assert "api_key=***REDACTED***" in rec.msg

