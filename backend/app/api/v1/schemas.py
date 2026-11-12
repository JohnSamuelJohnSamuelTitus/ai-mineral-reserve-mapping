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
    acquired_at: datetime | None
    cloud_cover_pct: float | None
    resolution_m: float | None
    bbox: list[float]
    storage_uri: str
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

