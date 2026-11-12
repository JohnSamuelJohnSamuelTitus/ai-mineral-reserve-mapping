"""FastAPI v1 routes for AOIs, data sources, licensing checks, real ingestion, and lookup."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.features_routes import router as features_router
from app.api.v1.geology_routes import router as geology_router
from app.api.v1.satellite_routes import raster_asset_to_response
from app.api.v1.satellite_routes import router as satellite_router
from app.api.v1.schemas import (
    AOICreateRequest,
    AOIResponse,
    DataSourceResponse,
    GeologicalUnitResponse,
    HealthResponse,
    IngestionJobResponse,
    IngestionProviderResult,
    IngestionRunRequest,
    IngestionRunResponse,
    MineralOccurrenceResponse,
    RasterAssetResponse,
)
from app.core.cache import CacheBackend, InMemoryTTLCache
from app.core.config import Settings, get_settings
from app.core.crs import GeospatialValidationError, validate_and_normalize_aoi_geojson
from app.db.models import AreaOfInterest
from app.db.repositories import (
    AOIRepository,
    DataSourceRepository,
    GeologicalUnitRepository,
    IngestionJobRepository,
    LicenseViolationError,
    MineralOccurrenceRepository,
    RasterAssetRepository,
)
from app.db.session import get_db
from app.ingestion.pipeline import IngestionPipeline
from app.integrations.base import ProviderError
from app.integrations.elevation import (
    ElevationService,
    OpenMeteoElevationAdapter,
    OpenTopoDataAdapter,
)
from app.integrations.geocoding import NominatimAdapter
from app.integrations.literature import OpenAlexAdapter
from app.integrations.macrostrat import MacrostratAdapter
from app.integrations.stac import SentinelSTACWithFallback, STACSearchAdapter
from app.integrations.usgs_mrds import USGSMRDSAdapter

router = APIRouter()
router.include_router(geology_router)
router.include_router(satellite_router)
router.include_router(features_router)

_shared_cache = InMemoryTTLCache()

SCIENTIFIC_DISCLAIMER = (
    "Outputs represent geospatial data and relative mineral prospectivity proxies only; "
    "they do NOT establish proven or probable mineral reserves."
)


def get_cache() -> CacheBackend:
    return _shared_cache


def _aoi_to_response(aoi: AreaOfInterest) -> AOIResponse:
    return AOIResponse(
        id=aoi.id,
        name=aoi.name,
        description=aoi.description,
        jurisdiction=aoi.jurisdiction,
        commodity_focus=aoi.commodity_focus,
        deposit_model=aoi.deposit_model,
        geometry=json.loads(aoi.geom_geojson),
        bbox=[aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat],
        centroid=[aoi.centroid_lon, aoi.centroid_lat],
        processing_epsg=aoi.processing_epsg,
        area_km2=aoi.area_km2,
        data_origin=aoi.data_origin,
        created_at=aoi.created_at,
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    cache: CacheBackend = Depends(get_cache),
) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        database_backend="sqlite" if settings.is_sqlite else "postgresql",
        postgis_enabled=not settings.is_sqlite,
        cache_stats=cache.stats(),
        scientific_disclaimer=SCIENTIFIC_DISCLAIMER,
    )


@router.post(
    "/aois",
    response_model=AOIResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["aois"],
)
def create_aoi(
    payload: AOICreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AOIResponse:
    try:
        normalized = validate_and_normalize_aoi_geojson(
            payload.geometry, max_area_km2=settings.max_aoi_area_km2
        )
    except GeospatialValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    repo = AOIRepository(db)
    aoi = repo.create(
        name=payload.name,
        description=payload.description,
        jurisdiction=payload.jurisdiction,
        commodity_focus=payload.commodity_focus,
        deposit_model=payload.deposit_model,
        normalized=normalized,
        data_origin=payload.data_origin,
    )
    return _aoi_to_response(aoi)


@router.get("/aois", response_model=list[AOIResponse], tags=["aois"])
def list_aois(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[AOIResponse]:
    repo = AOIRepository(db)
    return [_aoi_to_response(a) for a in repo.list_all(limit=limit, offset=offset)]


@router.get("/aois/{aoi_id}", response_model=AOIResponse, tags=["aois"])
def get_aoi(aoi_id: str, db: Session = Depends(get_db)) -> AOIResponse:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")
    return _aoi_to_response(aoi)


@router.delete("/aois/{aoi_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["aois"])
def delete_aoi(aoi_id: str, db: Session = Depends(get_db)) -> None:
    deleted = AOIRepository(db).delete(aoi_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")


@router.get("/sources", response_model=list[DataSourceResponse], tags=["sources"])
def list_data_sources(db: Session = Depends(get_db)) -> list[DataSourceResponse]:
    sources = DataSourceRepository(db).list_all()
    return [
        DataSourceResponse(
            id=s.id,
            provider_key=s.provider_key,
            display_name=s.display_name,
            jurisdiction=s.jurisdiction,
            label_authority=s.label_authority,
            base_url=s.base_url,
            license=s.license,
            attribution_text=s.attribution_text,
            is_ml_training_allowed=s.is_ml_training_allowed,
            is_enabled=s.is_enabled,
            last_health_status=s.last_health_status,
            last_checked_at=s.last_checked_at,
            notes=s.notes,
        )
        for s in sources
    ]


@router.get("/sources/{provider_key}/ml-check", tags=["sources"])
def check_ml_license_permission(provider_key: str, db: Session = Depends(get_db)) -> dict:
    repo = DataSourceRepository(db)
    try:
        src = repo.assert_ml_training_allowed(provider_key)
    except LicenseViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {
        "provider_key": src.provider_key,
        "is_ml_training_allowed": src.is_ml_training_allowed,
        "label_authority": src.label_authority,
        "license": src.license,
    }


def _build_ingestion_pipeline(db: Session, settings: Settings, cache: CacheBackend) -> IngestionPipeline:
    mpc = STACSearchAdapter(
        provider_key="mpc_stac",
        base_url=settings.mpc_stac_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        cache=cache,
    )
    earth_search = STACSearchAdapter(
        provider_key="earth_search_stac",
        base_url=settings.earth_search_stac_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        cache=cache,
    )
    return IngestionPipeline(
        db,
        mrds_adapter=USGSMRDSAdapter(
            base_url=settings.usgs_mrds_wfs_url,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            cache=cache,
        ),
        macrostrat_adapter=MacrostratAdapter(
            base_url=settings.macrostrat_base_url,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            cache=cache,
        ),
        sentinel_stac=SentinelSTACWithFallback(primary=mpc, fallback=earth_search),
    )


@router.post("/ingestion/aois/{aoi_id}/run", response_model=IngestionRunResponse, tags=["ingestion"])
async def run_aoi_ingestion(
    aoi_id: str,
    payload: IngestionRunRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    cache: CacheBackend = Depends(get_cache),
) -> IngestionRunResponse:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    pipeline = _build_ingestion_pipeline(db, settings, cache)
    results: list[IngestionProviderResult] = []
    for provider in payload.providers:
        if provider == "macrostrat_v2":
            res = await pipeline.ingest_macrostrat(aoi)
        elif provider == "usgs_mrds":
            res = await pipeline.ingest_usgs_mrds(aoi, max_features=payload.mrds_max_features)
        elif provider == "sentinel2_stac":
            res = await pipeline.ingest_sentinel2_stac(
                aoi,
                max_cloud_cover=payload.max_cloud_cover,
                limit=payload.stac_limit,
            )
        else:
            continue
        results.append(IngestionProviderResult(**res))
    return IngestionRunResponse(aoi_id=aoi.id, results=results)


@router.get("/ingestion/jobs", response_model=list[IngestionJobResponse], tags=["ingestion"])
def list_ingestion_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[IngestionJobResponse]:
    jobs = IngestionJobRepository(db).list_recent(limit=limit)
    return [
        IngestionJobResponse(
            id=j.id,
            aoi_id=j.aoi_id,
            provider_key=j.provider_key,
            status=j.status,
            records_written=j.records_written,
            error_message=j.error_message,
            details_json=j.details_json,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]


@router.get("/aois/{aoi_id}/occurrences", response_model=list[MineralOccurrenceResponse], tags=["geology"])
def list_aoi_occurrences(
    aoi_id: str,
    label_authority: str | None = Query(default=None),
    data_origin: str | None = Query(default=None),
    ml_trainable_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[MineralOccurrenceResponse]:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    occs = MineralOccurrenceRepository(db).find_in_aoi(
        aoi,
        label_authority=label_authority,
        data_origin=data_origin,
        ml_trainable_only=ml_trainable_only,
    )
    return [
        MineralOccurrenceResponse(
            id=o.id,
            source_id=o.source_id,
            external_id=o.external_id,
            name=o.name,
            commodity_primary=o.commodity_primary,
            commodities_all=o.commodities_all,
            occurrence_type=o.occurrence_type,
            deposit_type=o.deposit_type,
            jurisdiction=o.jurisdiction,
            label_authority=o.label_authority,
            data_origin=o.data_origin,
            lon=o.lon,
            lat=o.lat,
            collected_at=o.collected_at,
        )
        for o in occs
    ]


@router.get("/aois/{aoi_id}/geology", response_model=list[GeologicalUnitResponse], tags=["geology"])
def list_aoi_geology(aoi_id: str, db: Session = Depends(get_db)) -> list[GeologicalUnitResponse]:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    units = GeologicalUnitRepository(db).find_in_aoi(aoi)
    return [
        GeologicalUnitResponse(
            id=u.id,
            external_map_id=u.external_map_id,
            unit_name=u.unit_name,
            strat_name=u.strat_name,
            lithology_raw=u.lithology_raw,
            lithology_class=u.lithology_class,
            age_min_ma=u.age_min_ma,
            age_max_ma=u.age_max_ma,
            period_name=u.period_name,
            data_origin=u.data_origin,
            collected_at=u.collected_at,
        )
        for u in units
    ]


@router.get("/aois/{aoi_id}/rasters", response_model=list[RasterAssetResponse], tags=["satellite"])
def list_aoi_rasters(aoi_id: str, db: Session = Depends(get_db)) -> list[RasterAssetResponse]:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    assets = RasterAssetRepository(db).list_for_aoi(aoi.id)
    return [raster_asset_to_response(r) for r in assets]


@router.get("/search/geocode", tags=["search"])
async def geocode_place(
    q: str = Query(..., min_length=2, max_length=200),
    settings: Settings = Depends(get_settings),
    cache: CacheBackend = Depends(get_cache),
) -> list[dict]:
    adapter = NominatimAdapter(
        base_url=settings.nominatim_base_url,
        user_agent=settings.nominatim_user_agent,
        timeout_seconds=settings.http_timeout_seconds,
        cache=cache,
    )
    try:
        places = await adapter.geocode(q)
        return [p.model_dump() for p in places]
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/search/literature", tags=["search"])
async def search_literature(
    q: str = Query(..., min_length=2, max_length=200),
    settings: Settings = Depends(get_settings),
    cache: CacheBackend = Depends(get_cache),
) -> list[dict]:
    api_key = settings.openalex_api_key.get_secret_value() if settings.openalex_api_key else None
    adapter = OpenAlexAdapter(
        base_url=settings.openalex_base_url,
        api_key=api_key,
        timeout_seconds=settings.http_timeout_seconds,
        cache=cache,
    )
    try:
        works = await adapter.search_works(q)
        return [w.model_dump() for w in works]
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/elevation/point", tags=["geology"])
async def lookup_point_elevation(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    settings: Settings = Depends(get_settings),
    cache: CacheBackend = Depends(get_cache),
) -> dict:
    service = ElevationService(
        primary=OpenTopoDataAdapter(
            base_url=settings.opentopodata_url,
            timeout_seconds=settings.http_timeout_seconds,
            cache=cache,
        ),
        fallback=OpenMeteoElevationAdapter(
            base_url=settings.openmeteo_elevation_url,
            timeout_seconds=settings.http_timeout_seconds,
            cache=cache,
        ),
    )
    try:
        pts = await service.get_points([(lat, lon)])
        return pts[0].model_dump()
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

