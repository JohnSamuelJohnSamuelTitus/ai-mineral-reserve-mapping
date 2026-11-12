"""AOI-scoped data ingestion orchestrator with provenance, licensing, and failure isolation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import Point, box, mapping, shape
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import (
    AreaOfInterest,
    GeologicalUnit,
    MineralOccurrence,
    RasterAsset,
)
from app.db.repositories import (
    DataSourceRepository,
    GeologicalUnitRepository,
    IngestionJobRepository,
    MineralOccurrenceRepository,
    RasterAssetRepository,
)
from app.integrations.base import ProviderError
from app.integrations.india_sources import (
    load_indian_official_csv,
    load_indian_official_geojson_file,
)
from app.integrations.macrostrat import MacrostratAdapter
from app.integrations.stac import SentinelSTACWithFallback, STACSearchAdapter
from app.integrations.usgs_mrds import USGSMRDSAdapter

logger = get_logger(__name__)


class IngestionPipeline:
    """Coordinates real external ingestion into SQLite/PostGIS with full audit trails."""

    def __init__(
        self,
        db: Session,
        *,
        mrds_adapter: USGSMRDSAdapter | None = None,
        macrostrat_adapter: MacrostratAdapter | None = None,
        sentinel_stac: SentinelSTACWithFallback | None = None,
        nasa_cmr_stac: STACSearchAdapter | None = None,
    ) -> None:
        self.db = db
        self.sources = DataSourceRepository(db)
        self.occurrences = MineralOccurrenceRepository(db)
        self.units = GeologicalUnitRepository(db)
        self.rasters = RasterAssetRepository(db)
        self.jobs = IngestionJobRepository(db)
        self.mrds = mrds_adapter
        self.macrostrat = macrostrat_adapter
        self.sentinel_stac = sentinel_stac
        self.nasa_cmr_stac = nasa_cmr_stac

    async def ingest_usgs_mrds(self, aoi: AreaOfInterest, *, max_features: int = 150) -> dict:
        provider_key = "usgs_mrds"
        source = self.sources.get_by_key(provider_key)
        if source is None:
            raise ValueError(f"DataSource '{provider_key}' is not seeded")

        job = self.jobs.create(provider_key=provider_key, aoi_id=aoi.id)
        try:
            assert self.mrds is not None, "USGSMRDSAdapter not configured"
            raw_records = await self.mrds.fetch_occurrences_bbox(
                min_lon=aoi.bbox_min_lon,
                min_lat=aoi.bbox_min_lat,
                max_lon=aoi.bbox_max_lon,
                max_lat=aoi.bbox_max_lat,
                max_features=max_features,
            )
            aoi_poly = shape(json.loads(aoi.geom_geojson))
            now = datetime.now(UTC)
            to_save: list[MineralOccurrence] = []
            for rec in raw_records:
                if not aoi_poly.intersects(Point(rec.lon, rec.lat)):
                    continue
                to_save.append(
                    MineralOccurrence(
                        source_id=source.id,
                        aoi_id=aoi.id,
                        external_id=rec.external_id,
                        name=rec.name,
                        commodity_primary=rec.commodity_primary,
                        commodities_all=rec.commodities_all,
                        occurrence_type=rec.occurrence_type,
                        deposit_type=rec.deposit_type,
                        jurisdiction=aoi.jurisdiction,
                        label_authority="international_supplement",
                        data_origin="real",
                        lon=rec.lon,
                        lat=rec.lat,
                        geom_geojson=json.dumps(
                            {"type": "Point", "coordinates": [rec.lon, rec.lat]}
                        ),
                        raw_attributes=rec.raw_attributes,
                        collected_at=now,
                    )
                )
            written = self.occurrences.upsert_many(to_save)
            self.sources.update_health(provider_key, "ok")
            self.jobs.complete(
                job,
                records_written=written,
                details={"fetched_bbox_count": len(raw_records), "in_aoi_count": len(to_save)},
            )
            return {
                "provider_key": provider_key,
                "status": "completed",
                "records_written": written,
                "fetched_count": len(raw_records),
            }
        except (ProviderError, ValueError, KeyError, TypeError, OSError, SQLAlchemyError) as exc:
            logger.error("Ingestion failed for %s: %s", provider_key, exc)
            self.sources.update_health(provider_key, f"error: {type(exc).__name__}")
            self.jobs.fail(job, error_message=str(exc))
            return {
                "provider_key": provider_key,
                "status": "failed",
                "records_written": 0,
                "error": str(exc),
            }

    async def ingest_macrostrat(self, aoi: AreaOfInterest) -> dict:
        provider_key = "macrostrat_v2"
        source = self.sources.get_by_key(provider_key)
        if source is None:
            raise ValueError(f"DataSource '{provider_key}' is not seeded")

        job = self.jobs.create(provider_key=provider_key, aoi_id=aoi.id)
        try:
            assert self.macrostrat is not None, "MacrostratAdapter not configured"
            fetched = await self.macrostrat.get_geologic_units_at_point(
                lat=aoi.centroid_lat, lon=aoi.centroid_lon
            )
            now = datetime.now(UTC)
            aoi_box_geojson = json.dumps(
                mapping(
                    box(
                        aoi.bbox_min_lon,
                        aoi.bbox_min_lat,
                        aoi.bbox_max_lon,
                        aoi.bbox_max_lat,
                    )
                )
            )
            to_save: list[GeologicalUnit] = []
            for unit in fetched:
                lith_tokens = (
                    [t.strip() for t in unit.lith.split(",") if t.strip()] if unit.lith else []
                )
                to_save.append(
                    GeologicalUnit(
                        source_id=source.id,
                        aoi_id=aoi.id,
                        external_map_id=str(unit.map_id),
                        unit_name=unit.name,
                        strat_name=unit.strat_name,
                        lithology_raw=unit.lith,
                        lithology_class=lith_tokens,
                        age_min_ma=unit.t_age,
                        age_max_ma=unit.b_age,
                        period_name=unit.best_int_name or unit.t_int_name,
                        data_origin="real",
                        geom_geojson=aoi_box_geojson,
                        bbox_min_lon=aoi.bbox_min_lon,
                        bbox_min_lat=aoi.bbox_min_lat,
                        bbox_max_lon=aoi.bbox_max_lon,
                        bbox_max_lat=aoi.bbox_max_lat,
                        metadata_json=unit.metadata_raw,
                        collected_at=now,
                    )
                )
            written = self.units.upsert_many(to_save)
            self.sources.update_health(provider_key, "ok")
            self.jobs.complete(job, records_written=written, details={"fetched": len(fetched)})
            return {
                "provider_key": provider_key,
                "status": "completed",
                "records_written": written,
                "fetched_count": len(fetched),
            }
        except (ProviderError, ValueError, KeyError, TypeError, OSError, SQLAlchemyError) as exc:
            logger.error("Ingestion failed for %s: %s", provider_key, exc)
            self.sources.update_health(provider_key, f"error: {type(exc).__name__}")
            self.jobs.fail(job, error_message=str(exc))
            return {
                "provider_key": provider_key,
                "status": "failed",
                "records_written": 0,
                "error": str(exc),
            }

    async def ingest_sentinel2_stac(
        self,
        aoi: AreaOfInterest,
        *,
        datetime_range: str | None = None,
        max_cloud_cover: float = 30.0,
        limit: int = 5,
    ) -> dict:
        job = self.jobs.create(provider_key="mpc_stac", aoi_id=aoi.id)
        try:
            assert self.sentinel_stac is not None, "SentinelSTACWithFallback not configured"
            used_provider, scenes = await self.sentinel_stac.search_sentinel2(
                bbox=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
                datetime_range=datetime_range,
                max_cloud_cover=max_cloud_cover,
                aoi_area_km2=aoi.area_km2,
                limit=limit,
            )
            source = self.sources.get_by_key(used_provider)
            if source is None:
                raise ValueError(f"DataSource '{used_provider}' is not seeded")

            now = datetime.now(UTC)
            to_save: list[RasterAsset] = []
            for scene in scenes:
                storage_uri = (
                    scene.asset_hrefs.get("visual")
                    or scene.asset_hrefs.get("B04")
                    or scene.asset_hrefs.get("red")
                    or next(iter(scene.asset_hrefs.values()), f"stac://{scene.collection}/{scene.item_id}")
                )
                to_save.append(
                    RasterAsset(
                        aoi_id=aoi.id,
                        source_id=source.id,
                        stac_collection=scene.collection,
                        stac_item_id=scene.item_id,
                        asset_type="sentinel2_l2a_stac_item",
                        platform=scene.platform,
                        product_type=scene.product_type,
                        acquired_at=scene.acquired_at,
                        cloud_cover_pct=scene.cloud_cover_pct,
                        resolution_m=scene.resolution_m or 10.0,
                        footprint_geojson=json.dumps(scene.geometry),
                        bbox_min_lon=scene.bbox[0],
                        bbox_min_lat=scene.bbox[1],
                        bbox_max_lon=scene.bbox[2],
                        bbox_max_lat=scene.bbox[3],
                        storage_uri=storage_uri,
                        download_status="discovered",
                        requires_auth=scene.requires_auth,
                        estimated_size_mb=scene.estimated_size_mb,
                        bands_available=scene.bands_available,
                        band_metadata={
                            "assets": sorted(scene.asset_hrefs.keys()),
                            "asset_hrefs": scene.asset_hrefs,
                            "auth_note": scene.auth_note,
                        },
                        data_origin="real",
                        collected_at=now,
                    )
                )
            written = self.rasters.upsert_many(to_save)
            self.sources.update_health(used_provider, "ok")
            self.jobs.complete(
                job,
                records_written=written,
                details={"provider_used": used_provider, "scenes_found": len(scenes)},
            )
            return {
                "provider_key": used_provider,
                "status": "completed",
                "records_written": written,
                "fetched_count": len(scenes),
            }
        except (ProviderError, ValueError, KeyError, TypeError, OSError, SQLAlchemyError) as exc:
            logger.error("STAC ingestion failed: %s", exc)
            self.sources.update_health("mpc_stac", f"error: {type(exc).__name__}")
            self.jobs.fail(job, error_message=str(exc))
            return {
                "provider_key": "mpc_stac",
                "status": "failed",
                "records_written": 0,
                "error": str(exc),
            }

    def ingest_indian_official_export(
        self,
        aoi: AreaOfInterest,
        *,
        file_path: Path,
        provider_key: str = "ngdr_geodataindia",
        data_origin: str = "real",
    ) -> dict:
        """Ingest verified local Indian GSI/NGDR GeoJSON or IBM CSV files with official authority tags."""
        source = self.sources.get_by_key(provider_key)
        if source is None:
            raise ValueError(f"DataSource '{provider_key}' is not seeded")
        if source.label_authority != "indian_official":
            raise ValueError(f"Provider '{provider_key}' is not an indian_official source")

        job = self.jobs.create(provider_key=provider_key, aoi_id=aoi.id)
        try:
            if file_path.suffix.lower() in (".geojson", ".json"):
                records = load_indian_official_geojson_file(
                    file_path, source_provider_key=provider_key
                )
            elif file_path.suffix.lower() == ".csv":
                records = load_indian_official_csv(file_path, source_provider_key=provider_key)
            else:
                raise ValueError(f"Unsupported Indian export file format: {file_path.suffix}")

            aoi_poly = shape(json.loads(aoi.geom_geojson))
            now = datetime.now(UTC)
            to_save: list[MineralOccurrence] = []
            for rec in records:
                if not aoi_poly.intersects(Point(rec.lon, rec.lat)):
                    continue
                to_save.append(
                    MineralOccurrence(
                        source_id=source.id,
                        aoi_id=aoi.id,
                        external_id=rec.external_id,
                        name=rec.name,
                        commodity_primary=rec.commodity_primary,
                        commodities_all=rec.commodities_all,
                        occurrence_type=rec.occurrence_type,
                        deposit_type=rec.deposit_type,
                        jurisdiction="IN",
                        label_authority="indian_official",
                        data_origin=data_origin,
                        lon=rec.lon,
                        lat=rec.lat,
                        geom_geojson=json.dumps(
                            {"type": "Point", "coordinates": [rec.lon, rec.lat]}
                        ),
                        raw_attributes=rec.raw_attributes,
                        collected_at=now,
                    )
                )
            written = self.occurrences.upsert_many(to_save)
            self.jobs.complete(
                job,
                records_written=written,
                details={"file": file_path.name, "in_aoi": len(to_save)},
            )
            return {
                "provider_key": provider_key,
                "status": "completed",
                "records_written": written,
                "fetched_count": len(records),
            }
        except (ValueError, KeyError, TypeError, OSError, SQLAlchemyError) as exc:
            self.jobs.fail(job, error_message=str(exc))
            return {
                "provider_key": provider_key,
                "status": "failed",
                "records_written": 0,
                "error": str(exc),
            }

