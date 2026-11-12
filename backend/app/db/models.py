"""SQLAlchemy ORM models aligned with DATABASE_DESIGN.md and India-first provenance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid_str() -> str:
    return str(uuid.uuid4())


class AreaOfInterest(Base):
    """User-defined exploration polygon stored in WGS84 GeoJSON/WKT with UTM metadata."""

    __tablename__ = "areas_of_interest"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False, default="IN")
    commodity_focus: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    deposit_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Migration-friendly spatial representation for SQLite -> PostGIS GEOMETRY(MultiPolygon, 4326)
    geom_geojson: Mapped[str] = mapped_column(Text, nullable=False)
    geom_wkt: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)

    processing_epsg: Mapped[int] = mapped_column(Integer, nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    data_origin: Mapped[str] = mapped_column(String(24), nullable=False, default="real")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    occurrences: Mapped[list[MineralOccurrence]] = relationship(back_populates="aoi")
    geological_units: Mapped[list[GeologicalUnit]] = relationship(back_populates="aoi")
    raster_assets: Mapped[list[RasterAsset]] = relationship(back_populates="aoi")


class DataSource(Base):
    """External or national data provider registry with licensing and ML training guardrails."""

    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    provider_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False, default="INTL")
    label_authority: Mapped[str] = mapped_column(
        String(48), nullable=False, default="international_supplement"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    license: Mapped[str] = mapped_column(String(128), nullable=False)
    attribution_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_ml_training_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    license_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MineralOccurrence(Base):
    """Mineral deposit, prospect, or mine record with explicit authority & origin lineage."""

    __tablename__ = "mineral_occurrences"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_occurrence_source_ext"),
        Index("ix_occ_lon_lat", "lon", "lat"),
        Index("ix_occ_authority_origin", "label_authority", "data_origin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("areas_of_interest.id"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    commodity_primary: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commodities_all: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    occurrence_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deposit_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geologic_age: Mapped[str | None] = mapped_column(String(128), nullable=True)
    host_rock: Mapped[str | None] = mapped_column(String(256), nullable=True)

    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False, default="INTL")
    # Distinguishes verified Indian GSI/IBM labels from international MRDS supplements
    label_authority: Mapped[str] = mapped_column(
        String(48), nullable=False, default="international_supplement"
    )
    data_origin: Mapped[str] = mapped_column(String(24), nullable=False, default="real")

    lon: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    geom_geojson: Mapped[str] = mapped_column(Text, nullable=False)
    raw_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    source: Mapped[DataSource] = relationship()
    aoi: Mapped[AreaOfInterest | None] = relationship(back_populates="occurrences")


class GeologicalUnit(Base):
    """Bedrock lithology and stratigraphic map unit associated with an AOI or location."""

    __tablename__ = "geological_units"
    __table_args__ = (
        UniqueConstraint("source_id", "external_map_id", name="uq_geounit_source_ext"),
        Index("ix_geounit_bbox", "bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("areas_of_interest.id"), nullable=True)
    external_map_id: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_name: Mapped[str] = mapped_column(String(256), nullable=False)
    strat_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    lithology_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    lithology_class: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    age_min_ma: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_max_ma: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    data_origin: Mapped[str] = mapped_column(String(24), nullable=False, default="real")

    geom_geojson: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    source: Mapped[DataSource] = relationship()
    aoi: Mapped[AreaOfInterest | None] = relationship(back_populates="geological_units")


class RasterAsset(Base):
    """Metadata index for STAC satellite scenes, DEMs, and Cloud-Optimized GeoTIFFs."""

    __tablename__ = "raster_assets"
    __table_args__ = (
        UniqueConstraint("source_id", "stac_item_id", "asset_type", name="uq_raster_item_asset"),
        Index("ix_raster_bbox", "bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    aoi_id: Mapped[str] = mapped_column(ForeignKey("areas_of_interest.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    stac_collection: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stac_item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    crs_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)

    footprint_geojson: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lat: Mapped[float] = mapped_column(Float, nullable=False)

    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    band_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    data_origin: Mapped[str] = mapped_column(String(24), nullable=False, default="real")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    source: Mapped[DataSource] = relationship()
    aoi: Mapped[AreaOfInterest] = relationship(back_populates="raster_assets")


class IngestionJob(Base):
    """Audit log of external API ingestion runs, record counts, and errors."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("areas_of_interest.id"), nullable=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
