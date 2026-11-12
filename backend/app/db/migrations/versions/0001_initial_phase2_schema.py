"""Initial Phase 2 schema for AOIs, provenance-tracked data sources, occurrences, geology, rasters, and jobs.

Revision ID: 0001_initial_phase2
Revises:
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_phase2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "areas_of_interest",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False, server_default="IN"),
        sa.Column("commodity_focus", sa.JSON(), nullable=False),
        sa.Column("deposit_model", sa.String(length=100), nullable=True),
        sa.Column("geom_geojson", sa.Text(), nullable=False),
        sa.Column("geom_wkt", sa.Text(), nullable=False),
        sa.Column("bbox_min_lon", sa.Float(), nullable=False),
        sa.Column("bbox_min_lat", sa.Float(), nullable=False),
        sa.Column("bbox_max_lon", sa.Float(), nullable=False),
        sa.Column("bbox_max_lat", sa.Float(), nullable=False),
        sa.Column("centroid_lon", sa.Float(), nullable=False),
        sa.Column("centroid_lat", sa.Float(), nullable=False),
        sa.Column("processing_epsg", sa.Integer(), nullable=False),
        sa.Column("area_km2", sa.Float(), nullable=False),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False, server_default="INTL"),
        sa.Column(
            "label_authority",
            sa.String(length=48),
            nullable=False,
            server_default="international_supplement",
        ),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("license", sa.String(length=128), nullable=False),
        sa.Column("attribution_text", sa.Text(), nullable=False),
        sa.Column("is_ml_training_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("license_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_status", sa.String(length=64), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("provider_key", name="uq_data_sources_provider_key"),
    )
    op.create_index("ix_data_sources_provider_key", "data_sources", ["provider_key"])

    op.create_table(
        "mineral_occurrences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("commodity_primary", sa.String(length=64), nullable=True),
        sa.Column("commodities_all", sa.JSON(), nullable=False),
        sa.Column("occurrence_type", sa.String(length=64), nullable=True),
        sa.Column("deposit_type", sa.String(length=128), nullable=True),
        sa.Column("geologic_age", sa.String(length=128), nullable=True),
        sa.Column("host_rock", sa.String(length=256), nullable=True),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False, server_default="INTL"),
        sa.Column(
            "label_authority",
            sa.String(length=48),
            nullable=False,
            server_default="international_supplement",
        ),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("geom_geojson", sa.Text(), nullable=False),
        sa.Column("raw_attributes", sa.JSON(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_occurrence_source_ext"),
    )
    op.create_index("ix_occ_lon_lat", "mineral_occurrences", ["lon", "lat"])
    op.create_index(
        "ix_occ_authority_origin", "mineral_occurrences", ["label_authority", "data_origin"]
    )

    op.create_table(
        "geological_units",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True),
        sa.Column("external_map_id", sa.String(length=128), nullable=False),
        sa.Column("unit_name", sa.String(length=256), nullable=False),
        sa.Column("strat_name", sa.String(length=256), nullable=True),
        sa.Column("lithology_raw", sa.Text(), nullable=True),
        sa.Column("lithology_class", sa.JSON(), nullable=False),
        sa.Column("age_min_ma", sa.Float(), nullable=True),
        sa.Column("age_max_ma", sa.Float(), nullable=True),
        sa.Column("period_name", sa.String(length=128), nullable=True),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("geom_geojson", sa.Text(), nullable=False),
        sa.Column("bbox_min_lon", sa.Float(), nullable=False),
        sa.Column("bbox_min_lat", sa.Float(), nullable=False),
        sa.Column("bbox_max_lon", sa.Float(), nullable=False),
        sa.Column("bbox_max_lat", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_map_id", name="uq_geounit_source_ext"),
    )
    op.create_index(
        "ix_geounit_bbox",
        "geological_units",
        ["bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"],
    )

    op.create_table(
        "raster_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=False),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("stac_collection", sa.String(length=128), nullable=True),
        sa.Column("stac_item_id", sa.String(length=200), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cloud_cover_pct", sa.Float(), nullable=True),
        sa.Column("resolution_m", sa.Float(), nullable=True),
        sa.Column("crs_epsg", sa.Integer(), nullable=True),
        sa.Column("footprint_geojson", sa.Text(), nullable=False),
        sa.Column("bbox_min_lon", sa.Float(), nullable=False),
        sa.Column("bbox_min_lat", sa.Float(), nullable=False),
        sa.Column("bbox_max_lon", sa.Float(), nullable=False),
        sa.Column("bbox_max_lat", sa.Float(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("band_metadata", sa.JSON(), nullable=False),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "stac_item_id", "asset_type", name="uq_raster_item_asset"),
    )
    op.create_index(
        "ix_raster_bbox",
        "raster_assets",
        ["bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"],
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_provider_key", "ingestion_jobs", ["provider_key"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_provider_key", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_raster_bbox", table_name="raster_assets")
    op.drop_table("raster_assets")
    op.drop_index("ix_geounit_bbox", table_name="geological_units")
    op.drop_table("geological_units")
    op.drop_index("ix_occ_authority_origin", table_name="mineral_occurrences")
    op.drop_index("ix_occ_lon_lat", table_name="mineral_occurrences")
    op.drop_table("mineral_occurrences")
    op.drop_index("ix_data_sources_provider_key", table_name="data_sources")
    op.drop_table("data_sources")
    op.drop_table("areas_of_interest")
