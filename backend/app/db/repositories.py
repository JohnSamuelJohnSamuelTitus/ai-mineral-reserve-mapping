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
    DatasetQualityReport,
    DataSource,
    FeatureManifest,
    GeologicalUnit,
    IngestionJob,
    MineralOccurrence,
    MLDatasetVersion,
    OccurrenceQuarantine,
    ProcessingJob,
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

    def update(
        self,
        aoi: AreaOfInterest,
        *,
        name: str | None = None,
        description: str | None = None,
        commodity_focus: list[str] | None = None,
        deposit_model: str | None = None,
        normalized: NormalizedAOIGeometry | None = None,
    ) -> AreaOfInterest:
        if name is not None:
            aoi.name = name
        if description is not None:
            aoi.description = description
        if commodity_focus is not None:
            aoi.commodity_focus = commodity_focus
        if deposit_model is not None:
            aoi.deposit_model = deposit_model
        if normalized is not None:
            min_lon, min_lat, max_lon, max_lat = normalized.bbox
            aoi.geom_geojson = normalized.geojson_str
            aoi.geom_wkt = normalized.wkt
            aoi.bbox_min_lon = min_lon
            aoi.bbox_min_lat = min_lat
            aoi.bbox_max_lon = max_lon
            aoi.bbox_max_lat = max_lat
            aoi.centroid_lon = normalized.centroid_lon
            aoi.centroid_lat = normalized.centroid_lat
            aoi.processing_epsg = normalized.processing_epsg
            aoi.area_km2 = normalized.area_km2
        self._db.commit()
        self._db.refresh(aoi)
        return aoi


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
                existing.platform = asset.platform or existing.platform
                existing.product_type = asset.product_type or existing.product_type
                existing.requires_auth = asset.requires_auth
                existing.estimated_size_mb = asset.estimated_size_mb or existing.estimated_size_mb
                existing.bands_available = asset.bands_available or existing.bands_available
                merged_meta = dict(existing.band_metadata or {})
                merged_meta.update(asset.band_metadata or {})
                if (existing.band_metadata or {}).get("downloaded_bands") and not (
                    (asset.band_metadata or {}).get("downloaded_bands")
                ):
                    merged_meta["downloaded_bands"] = existing.band_metadata["downloaded_bands"]
                existing.band_metadata = merged_meta
        self._db.commit()
        return written

    def get(self, asset_id: str) -> RasterAsset | None:
        return self._db.get(RasterAsset, asset_id)

    def mark_downloaded(
        self,
        asset: RasterAsset,
        *,
        local_path: str,
        checksum_sha256: str,
        crs_epsg: int | None = None,
        band_metadata: dict | None = None,
        download_status: str = "downloaded",
    ) -> RasterAsset:
        asset.local_path = local_path
        asset.checksum_sha256 = checksum_sha256
        asset.download_status = download_status
        if crs_epsg is not None:
            asset.crs_epsg = crs_epsg
        if band_metadata is not None:
            existing = dict(asset.band_metadata or {})
            if "downloaded_bands" in band_metadata and isinstance(band_metadata["downloaded_bands"], dict):
                merged_bands = dict(existing.get("downloaded_bands") or {})
                merged_bands.update(band_metadata["downloaded_bands"])
                existing.update(band_metadata)
                existing["downloaded_bands"] = merged_bands
            else:
                existing.update(band_metadata)
            asset.band_metadata = existing
        self._db.commit()
        self._db.refresh(asset)
        return asset

    def mark_bands_downloaded(
        self,
        asset: RasterAsset,
        *,
        downloaded_bands: dict[str, dict],
        primary_local_path: str,
        primary_checksum_sha256: str,
        crs_epsg: int | None = None,
        download_status: str = "downloaded",
    ) -> RasterAsset:
        existing = dict(asset.band_metadata or {})
        merged_bands = dict(existing.get("downloaded_bands") or {})
        merged_bands.update(downloaded_bands)
        existing["downloaded_bands"] = merged_bands
        asset.band_metadata = existing
        asset.local_path = primary_local_path
        asset.checksum_sha256 = primary_checksum_sha256
        asset.download_status = download_status
        if crs_epsg is not None:
            asset.crs_epsg = crs_epsg
        self._db.commit()
        self._db.refresh(asset)
        return asset

    def mark_download_failed(self, asset: RasterAsset) -> RasterAsset:
        asset.download_status = "failed"
        self._db.commit()
        self._db.refresh(asset)
        return asset

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


class QuarantineAndQualityRepository:
    """Persists quarantined occurrence rows and dataset quality audit summaries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save_report_and_quarantine(
        self,
        report: DatasetQualityReport,
        quarantined: list[OccurrenceQuarantine],
    ) -> DatasetQualityReport:
        self._db.add(report)
        for item in quarantined:
            self._db.add(item)
        self._db.commit()
        self._db.refresh(report)
        return report

    def list_reports_for_aoi(self, aoi_id: str) -> list[DatasetQualityReport]:
        stmt = (
            select(DatasetQualityReport)
            .where(DatasetQualityReport.aoi_id == aoi_id)
            .order_by(DatasetQualityReport.created_at.desc())
        )
        return list(self._db.scalars(stmt).all())

    def list_quarantined_for_aoi(
        self, aoi_id: str, *, limit: int = 100
    ) -> list[OccurrenceQuarantine]:
        stmt = (
            select(OccurrenceQuarantine)
            .where(OccurrenceQuarantine.aoi_id == aoi_id)
            .order_by(OccurrenceQuarantine.created_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())


class ProcessingJobRepository:
    """Repository for background processing jobs (downloads, features, ML dataset prep)."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self, *, job_type: str, aoi_id: str | None = None, parameters: dict | None = None
    ) -> ProcessingJob:
        job = ProcessingJob(
            job_type=job_type,
            aoi_id=aoi_id,
            status="pending",
            progress_pct=0,
            parameters_json=parameters or {},
            result_summary_json={},
        )
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def get(self, job_id: str) -> ProcessingJob | None:
        return self._db.get(ProcessingJob, job_id)

    def mark_running(self, job: ProcessingJob, progress_pct: int = 10) -> ProcessingJob:
        job.status = "running"
        job.progress_pct = progress_pct
        self._db.commit()
        self._db.refresh(job)
        return job

    def update_progress(
        self,
        job: ProcessingJob,
        *,
        progress_pct: int,
        summary: dict | None = None,
    ) -> ProcessingJob:
        job.progress_pct = max(0, min(100, int(progress_pct)))
        if summary is not None:
            job.result_summary_json = summary
        self._db.commit()
        self._db.refresh(job)
        return job

    def complete(self, job: ProcessingJob, *, summary: dict) -> ProcessingJob:
        job.status = "completed"
        job.progress_pct = 100
        job.result_summary_json = summary
        job.finished_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(job)
        return job

    def fail(self, job: ProcessingJob, *, error_message: str) -> ProcessingJob:
        job.status = "failed"
        job.error_message = error_message[:2000]
        job.finished_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(job)
        return job

    def cancel(self, job: ProcessingJob, *, reason: str = "Cancelled by user") -> ProcessingJob:
        job.status = "cancelled"
        job.error_message = reason[:2000]
        job.finished_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(job)
        return job

    def is_cancelled(self, job_id: str) -> bool:
        self._db.expire_all()
        job = self._db.get(ProcessingJob, job_id)
        return job is not None and job.status == "cancelled"

    def list_for_aoi(self, aoi_id: str | None = None, *, limit: int = 50) -> list[ProcessingJob]:
        stmt = select(ProcessingJob).order_by(ProcessingJob.started_at.desc()).limit(limit)
        if aoi_id is not None:
            stmt = (
                select(ProcessingJob)
                .where(ProcessingJob.aoi_id == aoi_id)
                .order_by(ProcessingJob.started_at.desc())
                .limit(limit)
            )
        return list(self._db.scalars(stmt).all())


class FeatureManifestRepository:
    """Repository for reproducible geospatial feature-engineering manifests."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, manifest: FeatureManifest) -> FeatureManifest:
        self._db.add(manifest)
        self._db.commit()
        self._db.refresh(manifest)
        return manifest

    def get(self, manifest_id: str) -> FeatureManifest | None:
        return self._db.get(FeatureManifest, manifest_id)

    def list_for_aoi(self, aoi_id: str) -> list[FeatureManifest]:
        stmt = (
            select(FeatureManifest)
            .where(FeatureManifest.aoi_id == aoi_id)
            .order_by(FeatureManifest.created_at.desc())
        )
        return list(self._db.scalars(stmt).all())


class MLDatasetVersionRepository:
    """Repository for spatial ML dataset snapshots and readiness reports."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, version: MLDatasetVersion) -> MLDatasetVersion:
        self._db.add(version)
        self._db.commit()
        self._db.refresh(version)
        return version

    def get(self, dataset_id: str) -> MLDatasetVersion | None:
        return self._db.get(MLDatasetVersion, dataset_id)

    def list_for_aoi(self, aoi_id: str) -> list[MLDatasetVersion]:
        stmt = (
            select(MLDatasetVersion)
            .where(MLDatasetVersion.aoi_id == aoi_id)
            .order_by(MLDatasetVersion.created_at.desc())
        )
        return list(self._db.scalars(stmt).all())
