"""Repository abstraction isolating SQLite spatial filtering from future PostGIS queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol

from shapely.geometry import Point, shape
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.crs import NormalizedAOIGeometry
from app.db.models import (
    AreaOfInterest,
    DataSource,
    GeologicalUnit,
    IngestionJob,
    MineralOccurrence,
    RasterAsset,
)


class LicenseViolationError(PermissionError):
    """Raised when attempting ML training on a restricted data source."""


class SpatialAOIRepositoryProtocol(Protocol):
    """Contract allowing drop-in replacement of SQLite spatial logic with PostGIS."""

    def create(
        self,
        *,
        name: str,
        description: str | None,
        jurisdiction: str,
        commodity_focus: list[str],
        deposit_model: str | None,
        normalized: NormalizedAOIGeometry,
        data_origin: str = "real",
    ) -> AreaOfInterest: ...

    def get(self, aoi_id: str) -> AreaOfInterest | None: ...

    def list_all(self, limit: int = 100, offset: int = 0) -> list[AreaOfInterest]: ...

    def delete(self, aoi_id: str) -> bool: ...


class AOIRepository:
    """SQLAlchemy implementation of AOI persistence (SQLite-compatible)."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        name: str,
        description: str | None,
        jurisdiction: str,
        commodity_focus: list[str],
        deposit_model: str | None,
        normalized: NormalizedAOIGeometry,
        data_origin: str = "real",
    ) -> AreaOfInterest:
        min_lon, min_lat, max_lon, max_lat = normalized.bbox
        aoi = AreaOfInterest(
            name=name,
            description=description,
            jurisdiction=jurisdiction,
            commodity_focus=commodity_focus,
            deposit_model=deposit_model,
            geom_geojson=normalized.geojson_str,
            geom_wkt=normalized.wkt,
            bbox_min_lon=min_lon,
            bbox_min_lat=min_lat,
            bbox_max_lon=max_lon,
            bbox_max_lat=max_lat,
            centroid_lon=normalized.centroid_lon,
            centroid_lat=normalized.centroid_lat,
            processing_epsg=normalized.processing_epsg,
            area_km2=normalized.area_km2,
            data_origin=data_origin,
        )
        self._db.add(aoi)
        self._db.commit()
        self._db.refresh(aoi)
        return aoi

    def get(self, aoi_id: str) -> AreaOfInterest | None:
        return self._db.get(AreaOfInterest, aoi_id)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[AreaOfInterest]:
        stmt = (
            select(AreaOfInterest)
            .order_by(AreaOfInterest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._db.scalars(stmt).all())

    def delete(self, aoi_id: str) -> bool:
        aoi = self.get(aoi_id)
        if aoi is None:
            return False
        self._db.delete(aoi)
        self._db.commit()
        return True


class DataSourceRepository:
    """Manages provider metadata, health status, and ML-training license flags."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_key(self, provider_key: str) -> DataSource | None:
        stmt = select(DataSource).where(DataSource.provider_key == provider_key)
        return self._db.scalar(stmt)

    def list_all(self) -> list[DataSource]:
        stmt = select(DataSource).order_by(DataSource.jurisdiction, DataSource.provider_key)
        return list(self._db.scalars(stmt).all())

    def assert_ml_training_allowed(self, provider_key: str) -> DataSource:
        """Enforce scientific licensing guardrails before any ML pipeline reads records."""
        source = self.get_by_key(provider_key)
        if source is None:
            raise LicenseViolationError(f"Unknown data source '{provider_key}'.")
        if not source.is_ml_training_allowed:
            raise LicenseViolationError(
                f"Provider '{provider_key}' is restricted from ML training "
                f"(license: {source.license}). Explicit written permission is required."
            )
        return source

    def update_health(self, provider_key: str, status: str) -> None:
        source = self.get_by_key(provider_key)
        if source is not None:
            source.last_health_status = status
            source.last_checked_at = datetime.now(UTC)
            self._db.commit()


class MineralOccurrenceRepository:
    """Spatial & provenance-aware repository for mineral occurrences."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_many(self, items: list[MineralOccurrence]) -> int:
        written = 0
        for item in items:
            existing = self._db.scalar(
                select(MineralOccurrence).where(
                    and_(
                        MineralOccurrence.source_id == item.source_id,
                        MineralOccurrence.external_id == item.external_id,
                    )
                )
            )
            if existing is None:
                self._db.add(item)
                written += 1
            else:
                existing.name = item.name
                existing.commodity_primary = item.commodity_primary
                existing.commodities_all = item.commodities_all
                existing.occurrence_type = item.occurrence_type
                existing.deposit_type = item.deposit_type
                existing.raw_attributes = item.raw_attributes
                existing.collected_at = item.collected_at
                existing.aoi_id = item.aoi_id or existing.aoi_id
        self._db.commit()
        return written

    def find_in_aoi(
        self,
        aoi: AreaOfInterest,
        *,
        label_authority: str | None = None,
        data_origin: str | None = None,
        ml_trainable_only: bool = False,
    ) -> list[MineralOccurrence]:
        """Two-stage spatial filter: SQL bbox index -> exact Shapely geometry intersection."""
        stmt = (
            select(MineralOccurrence)
            .join(DataSource, MineralOccurrence.source_id == DataSource.id)
            .where(
                and_(
                    MineralOccurrence.lon >= aoi.bbox_min_lon,
                    MineralOccurrence.lon <= aoi.bbox_max_lon,
                    MineralOccurrence.lat >= aoi.bbox_min_lat,
                    MineralOccurrence.lat <= aoi.bbox_max_lat,
                )
            )
        )
        if label_authority is not None:
            stmt = stmt.where(MineralOccurrence.label_authority == label_authority)
        if data_origin is not None:
            stmt = stmt.where(MineralOccurrence.data_origin == data_origin)
        if ml_trainable_only:
            stmt = stmt.where(DataSource.is_ml_training_allowed.is_(True))

        candidates = list(self._db.scalars(stmt).all())
        aoi_poly = shape(json.loads(aoi.geom_geojson))
        return [occ for occ in candidates if aoi_poly.intersects(Point(occ.lon, occ.lat))]


class GeologicalUnitRepository:
    """Spatial repository for bedrock geological units."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_many(self, units: list[GeologicalUnit]) -> int:
        written = 0
        for unit in units:
            existing = self._db.scalar(
                select(GeologicalUnit).where(
                    and_(
                        GeologicalUnit.source_id == unit.source_id,
                        GeologicalUnit.external_map_id == unit.external_map_id,
                    )
                )
            )
            if existing is None:
                self._db.add(unit)
                written += 1
            else:
                existing.unit_name = unit.unit_name
                existing.lithology_raw = unit.lithology_raw
                existing.lithology_class = unit.lithology_class
                existing.metadata_json = unit.metadata_json
                existing.collected_at = unit.collected_at
        self._db.commit()
        return written

    def find_in_aoi(self, aoi: AreaOfInterest) -> list[GeologicalUnit]:
        stmt = select(GeologicalUnit).where(
            and_(
                GeologicalUnit.bbox_max_lon >= aoi.bbox_min_lon,
                GeologicalUnit.bbox_min_lon <= aoi.bbox_max_lon,
                GeologicalUnit.bbox_max_lat >= aoi.bbox_min_lat,
                GeologicalUnit.bbox_min_lat <= aoi.bbox_max_lat,
            )
        )
        candidates = list(self._db.scalars(stmt).all())
        aoi_poly = shape(json.loads(aoi.geom_geojson))
        return [u for u in candidates if aoi_poly.intersects(shape(json.loads(u.geom_geojson)))]


class RasterAssetRepository:
    """Repository for STAC satellite items and raster metadata."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_many(self, assets: list[RasterAsset]) -> int:
        written = 0
        for asset in assets:
            existing = self._db.scalar(
                select(RasterAsset).where(
                    and_(
                        RasterAsset.source_id == asset.source_id,
                        RasterAsset.stac_item_id == asset.stac_item_id,
                        RasterAsset.asset_type == asset.asset_type,
                    )
                )
            )
            if existing is None:
                self._db.add(asset)
                written += 1
            else:
                existing.cloud_cover_pct = asset.cloud_cover_pct
                existing.storage_uri = asset.storage_uri
                existing.band_metadata = asset.band_metadata
        self._db.commit()
        return written

    def list_for_aoi(self, aoi_id: str) -> list[RasterAsset]:
        stmt = (
            select(RasterAsset)
            .where(RasterAsset.aoi_id == aoi_id)
            .order_by(RasterAsset.acquired_at.desc())
        )
        return list(self._db.scalars(stmt).all())


class IngestionJobRepository:
    """Tracks ingestion jobs and failures."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, provider_key: str, aoi_id: str | None = None) -> IngestionJob:
        job = IngestionJob(provider_key=provider_key, aoi_id=aoi_id, status="running")
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def complete(
        self, job: IngestionJob, *, records_written: int, details: dict | None = None
    ) -> IngestionJob:
        job.status = "completed"
        job.records_written = records_written
        job.details_json = details or {}
        job.finished_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(job)
        return job

    def fail(self, job: IngestionJob, *, error_message: str) -> IngestionJob:
        job.status = "failed"
        job.error_message = error_message[:2000]
        job.finished_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(job)
        return job

    def list_recent(self, limit: int = 50) -> list[IngestionJob]:
        stmt = select(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit)
        return list(self._db.scalars(stmt).all())
