"""Pydantic v2 request and response schemas for Phase 2 API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app_name: str
    database_backend: str
    postgis_enabled: bool
    cache_stats: dict[str, int]
    scientific_disclaimer: str


class AOICreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    jurisdiction: str = Field(default="IN", min_length=2, max_length=32)
    commodity_focus: list[str] = Field(default_factory=list)
    deposit_model: str | None = Field(default=None, max_length=100)
    geometry: dict[str, Any]
    data_origin: Literal["real", "synthetic", "demonstration"] = "real"


class AOIResponse(BaseModel):
    id: str
    name: str
    description: str | None
    jurisdiction: str
    commodity_focus: list[str]
    deposit_model: str | None
    geometry: dict[str, Any]
    bbox: list[float]
    centroid: list[float]
    processing_epsg: int
    area_km2: float
    data_origin: str
    created_at: datetime


class DataSourceResponse(BaseModel):
    id: str
    provider_key: str
    display_name: str
    jurisdiction: str
    label_authority: str
    base_url: str
    license: str
    attribution_text: str
    is_ml_training_allowed: bool
    is_enabled: bool
    last_health_status: str | None
    last_checked_at: datetime | None
    notes: str | None


class IngestionRunRequest(BaseModel):
    providers: list[Literal["usgs_mrds", "macrostrat_v2", "sentinel2_stac"]] = Field(
        default_factory=lambda: ["macrostrat_v2", "usgs_mrds", "sentinel2_stac"]
    )
    max_cloud_cover: float = Field(default=30.0, ge=0.0, le=100.0)
    stac_limit: int = Field(default=5, ge=1, le=25)
    mrds_max_features: int = Field(default=100, ge=1, le=500)


class IngestionProviderResult(BaseModel):
    provider_key: str
    status: str
    records_written: int
    fetched_count: int = 0
    error: str | None = None


class IngestionRunResponse(BaseModel):
    aoi_id: str
    results: list[IngestionProviderResult]


class MineralOccurrenceResponse(BaseModel):
    id: str
    source_id: str
    external_id: str
    name: str
    commodity_primary: str | None
    commodities_all: list[str]
    occurrence_type: str | None
    deposit_type: str | None
    jurisdiction: str
    label_authority: str
    data_origin: str
    lon: float
    lat: float
    collected_at: datetime


class GeologicalUnitResponse(BaseModel):
    id: str
    external_map_id: str
    unit_name: str
    strat_name: str | None
    lithology_raw: str | None
    lithology_class: list[str]
    age_min_ma: float | None
    age_max_ma: float | None
    period_name: str | None
    data_origin: str
    collected_at: datetime


class RasterAssetResponse(BaseModel):
    id: str
    stac_collection: str | None
    stac_item_id: str
    asset_type: str
    platform: str | None = None
    product_type: str | None = None
    acquired_at: datetime | None
    cloud_cover_pct: float | None
    resolution_m: float | None
    bbox: list[float]
    storage_uri: str
    local_path: str | None = None
    download_status: str = "discovered"
    requires_auth: bool = False
    estimated_size_mb: float | None = None
    bands_available: list[str] = Field(default_factory=list)
    data_origin: str
    collected_at: datetime


class IngestionJobResponse(BaseModel):
    id: str
    aoi_id: str | None
    provider_key: str
    status: str
    records_written: int
    error_message: str | None
    details_json: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None


class SatelliteSearchRequest(BaseModel):
    aoi_id: str
    provider: Literal["mpc_stac", "earth_search_stac", "nasa_cmr_stac"] = "mpc_stac"
    collections: list[str] = Field(default_factory=lambda: ["sentinel-2-l2a", "cop-dem-glo-30"])
    datetime_range: str | None = None
    max_cloud_cover: float | None = Field(default=30.0, ge=0.0, le=100.0)
    limit: int = Field(default=8, ge=1, le=25)
    save_metadata: bool = True


class SatelliteSearchResponse(BaseModel):
    aoi_id: str
    provider: str
    collections_queried: list[str]
    scene_count: int
    saved_count: int
    scenes: list[dict[str, Any]]


class DatasetQualityReportResponse(BaseModel):
    id: str
    aoi_id: str | None
    source_provider_key: str
    dataset_name: str
    data_origin: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    missing_coords_count: int
    invalid_coords_count: int
    missing_commodity_count: int
    completeness_pct: float
    commodity_distribution: dict[str, int]
    warnings: list[str]
    created_at: datetime


class QuarantinedRecordResponse(BaseModel):
    id: str
    aoi_id: str | None
    source_provider_key: str
    external_id: str | None
    rejection_reason: str
    quality_flags: list[str]
    raw_record: dict[str, Any]
    created_at: datetime


class ProcessingJobResponse(BaseModel):
    id: str
    aoi_id: str | None
    job_type: str
    status: str
    progress_pct: int
    parameters_json: dict[str, Any]
    result_summary_json: dict[str, Any]
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None

