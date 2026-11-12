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


class AOIUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    commodity_focus: list[str] | None = None
    deposit_model: str | None = Field(default=None, max_length=100)
    geometry: dict[str, Any] | None = None


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
    geometry: dict[str, Any] = Field(default_factory=dict)
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


class FeatureExtractRequest(BaseModel):
    resolution_m: float = Field(default=100.0, gt=5.0, le=5000.0)
    dem_asset_id: str | None = None
    include_geology: bool = True
    run_sync: bool = False


class FeatureManifestResponse(BaseModel):
    id: str
    aoi_id: str
    target_crs_epsg: int
    resolution_m: float
    grid_rows: int
    grid_cols: int
    nodata_value: float
    status: str
    input_datasets_json: list[dict[str, Any]]
    input_scene_ids: list[str]
    feature_names: list[str]
    output_files_json: dict[str, str]
    warnings_json: list[str]
    manifest_json: dict[str, Any]
    data_origin: str
    created_at: datetime


class RasterInspectResponse(BaseModel):
    asset_id: str
    local_path: str
    epsg: int | None
    is_geographic: bool
    crs_wkt: str | None
    width: int
    height: int
    count: int
    dtype: str
    nodata: float | None
    resolution: list[float]
    bounds: list[float]
    stats: dict[str, Any]


class FeatureOverlayDescriptorResponse(BaseModel):
    manifest_id: str
    feature_name: str
    min: float | None
    max: float | None
    mean: float | None
    valid_pct: float | None
    nodata_value: float
    wgs84_corners: list[list[float]]
    image_url: str


class AOICoverageResponse(BaseModel):
    aoi_id: str
    aoi_name: str
    processing_epsg: int
    area_km2: float
    occurrence_total: int
    occurrence_ml_trainable: int
    occurrence_reference_only: int
    quarantined_count: int
    quality_reports_count: int
    geological_units_count: int
    raster_scenes_discovered: int
    raster_scenes_downloaded: int
    feature_manifests_count: int
    latest_manifest_id: str | None
    missing_layers: list[str]
    warnings: list[str]


class MLDatasetBuildRequest(BaseModel):
    manifest_id: str | None = None
    version_tag: str = Field(default="v1", min_length=1, max_length=64)
    block_size_m: float = Field(default=1000.0, gt=50.0, le=50000.0)
    seed: int = Field(default=42, ge=0, le=1_000_000)
    include_dist_to_occurrence: bool = False
    min_positives: int = Field(default=10, ge=1, le=500)
    min_positive_blocks: int = Field(default=3, ge=1, le=50)
    min_valid_coverage_pct: float = Field(default=50.0, ge=0.0, le=100.0)


class MLDatasetVersionResponse(BaseModel):
    id: str
    aoi_id: str
    manifest_id: str | None
    version_tag: str
    seed: int
    positive_count: int
    unlabeled_count: int
    explicit_negative_count: int
    spatial_block_count: int
    feature_columns: list[str]
    readiness_status: Literal["ready", "blocked"]
    blocking_reasons: list[str]
    leakage_checks: dict[str, Any]
    metrics_json: dict[str, Any]
    artifact_path: str | None
    data_origin: str
    created_at: datetime

