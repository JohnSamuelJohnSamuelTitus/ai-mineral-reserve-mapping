"""Database migration, spatial containment, India-first authority, and license tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.crs import validate_and_normalize_aoi_geojson
from app.db.models import MineralOccurrence
from app.db.repositories import (
    AOIRepository,
    DataSourceRepository,
    LicenseViolationError,
    MineralOccurrenceRepository,
)
from app.ingestion.pipeline import IngestionPipeline


def test_alembic_upgrade_downgrade_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "alembic_test.db"
    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file.as_posix()}")

    command.upgrade(cfg, "head")
    from app.db.session import create_db_engine

    eng = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    tables = set(inspect(eng).get_table_names())
    assert {
        "areas_of_interest",
        "data_sources",
        "mineral_occurrences",
        "geological_units",
        "raster_assets",
        "ingestion_jobs",
    }.issubset(tables)
    eng.dispose()

    command.downgrade(cfg, "base")
    eng2 = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    tables_after = set(inspect(eng2).get_table_names())
    assert "areas_of_interest" not in tables_after
    eng2.dispose()

    command.upgrade(cfg, "head")


def test_license_enforcement_blocks_mindat_ml_training(db_session: Session) -> None:
    repo = DataSourceRepository(db_session)
    assert repo.assert_ml_training_allowed("ngdr_geodataindia").is_ml_training_allowed is True
    assert repo.assert_ml_training_allowed("usgs_mrds").is_ml_training_allowed is True

    with pytest.raises(LicenseViolationError, match="restricted from ML training"):
        repo.assert_ml_training_allowed("mindat_v1")


def test_spatial_containment_and_india_authority_separation(
    db_session: Session, tmp_path: Path
) -> None:
    # Triangle polygon over Khetri region so bbox corners lie OUTSIDE polygon
    tri_geojson = {
        "type": "Polygon",
        "coordinates": [[[75.7, 27.9], [75.9, 27.9], [75.8, 28.1], [75.7, 27.9]]],
    }
    aoi = AOIRepository(db_session).create(
        name="Khetri Triangle Test",
        description="Spatial containment and authority test",
        jurisdiction="IN",
        commodity_focus=["Cu"],
        deposit_model="iron_oxide_copper_gold",
        normalized=validate_and_normalize_aoi_geojson(tri_geojson),
        data_origin="synthetic",
    )

    # Create synthetic Indian official GeoJSON with 1 point inside triangle, 1 in bbox corner outside triangle
    india_file = tmp_path / "ngdr_sample.geojson"
    india_file.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [75.80, 27.95]},
                        "properties": {"ngdr_id": "IN-INSIDE", "name": "Inside Prospect", "commodity": "Cu"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [75.71, 28.09]},
                        "properties": {"ngdr_id": "IN-CORNER", "name": "Outside Triangle", "commodity": "Cu"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    pipeline = IngestionPipeline(db_session)
    res = pipeline.ingest_indian_official_export(
        aoi, file_path=india_file, provider_key="ngdr_geodataindia", data_origin="synthetic"
    )
    assert res["records_written"] == 1

    # Also add an international supplement occurrence and a restricted Mindat occurrence inside triangle
    mrds_src = DataSourceRepository(db_session).get_by_key("usgs_mrds")
    mindat_src = DataSourceRepository(db_session).get_by_key("mindat_v1")
    assert mrds_src is not None and mindat_src is not None

    occ_repo = MineralOccurrenceRepository(db_session)
    occ_repo.upsert_many(
        [
            MineralOccurrence(
                source_id=mrds_src.id,
                aoi_id=aoi.id,
                external_id="MRDS-1",
                name="MRDS Intl Point",
                jurisdiction="IN",
                label_authority="international_supplement",
                data_origin="synthetic",
                lon=75.81,
                lat=27.95,
                geom_geojson=json.dumps({"type": "Point", "coordinates": [75.81, 27.95]}),
            ),
            MineralOccurrence(
                source_id=mindat_src.id,
                aoi_id=aoi.id,
                external_id="MINDAT-1",
                name="Restricted Mindat Point",
                jurisdiction="IN",
                label_authority="restricted",
                data_origin="synthetic",
                lon=75.82,
                lat=27.95,
                geom_geojson=json.dumps({"type": "Point", "coordinates": [75.82, 27.95]}),
            ),
        ]
    )

    indian_only = occ_repo.find_in_aoi(aoi, label_authority="indian_official")
    assert [o.external_id for o in indian_only] == ["IN-INSIDE"]

    ml_trainable = occ_repo.find_in_aoi(aoi, ml_trainable_only=True)
    ml_ids = {o.external_id for o in ml_trainable}
    assert ml_ids == {"IN-INSIDE", "MRDS-1"}
    assert "MINDAT-1" not in ml_ids

