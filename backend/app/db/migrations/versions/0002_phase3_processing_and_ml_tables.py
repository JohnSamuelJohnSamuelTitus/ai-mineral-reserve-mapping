"""Phase 3 tables for quarantine, quality reports, processing jobs, manifests, and ML datasets.

Revision ID: 0002_phase3_tables
Revises: 0001_initial_phase2
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_phase3_tables"
down_revision = "0001_initial_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("raster_assets") as batch_op:
        batch_op.add_column(sa.Column("platform", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("product_type", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("local_path", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "download_status",
                sa.String(length=32),
                nullable=False,
                server_default="discovered",
            )
        )
        batch_op.add_column(
            sa.Column(
                "requires_auth",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("estimated_size_mb", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("bands_available", sa.JSON(), nullable=False, server_default="[]")
        )

    op.create_table(
        "occurrence_quarantined",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True
        ),
        sa.Column("source_provider_key", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("rejection_reason", sa.String(length=128), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("raw_record", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_occurrence_quarantined_provider", "occurrence_quarantined", ["source_provider_key"]
    )

    op.create_table(
        "dataset_quality_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True
        ),
        sa.Column("source_provider_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_name", sa.String(length=200), nullable=False),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_coords_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_coords_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_commodity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completeness_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("commodity_distribution", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quality_reports_provider", "dataset_quality_reports", ["source_provider_key"]
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=True
        ),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("result_summary_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_processing_jobs_type", "processing_jobs", ["job_type"])

    op.create_table(
        "feature_manifests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=False
        ),
        sa.Column("target_crs_epsg", sa.Integer(), nullable=False),
        sa.Column("resolution_m", sa.Float(), nullable=False),
        sa.Column("grid_rows", sa.Integer(), nullable=False),
        sa.Column("grid_cols", sa.Integer(), nullable=False),
        sa.Column("nodata_value", sa.Float(), nullable=False, server_default="-9999.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("input_datasets_json", sa.JSON(), nullable=False),
        sa.Column("input_scene_ids", sa.JSON(), nullable=False),
        sa.Column("feature_names", sa.JSON(), nullable=False),
        sa.Column("output_files_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_manifests_aoi", "feature_manifests", ["aoi_id"])

    op.create_table(
        "ml_dataset_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "aoi_id", sa.String(length=36), sa.ForeignKey("areas_of_interest.id"), nullable=False
        ),
        sa.Column(
            "manifest_id",
            sa.String(length=36),
            sa.ForeignKey("feature_manifests.id"),
            nullable=True,
        ),
        sa.Column("version_tag", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unlabeled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("explicit_negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spatial_block_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("leakage_checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocking_reasons_json", sa.JSON(), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("data_origin", sa.String(length=24), nullable=False, server_default="real"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ml_dataset_versions_aoi", "ml_dataset_versions", ["aoi_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_dataset_versions_aoi", table_name="ml_dataset_versions")
    op.drop_table("ml_dataset_versions")
    op.drop_index("ix_feature_manifests_aoi", table_name="feature_manifests")
    op.drop_table("feature_manifests")
    op.drop_index("ix_processing_jobs_type", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_quality_reports_provider", table_name="dataset_quality_reports")
    op.drop_table("dataset_quality_reports")
    op.drop_index("ix_occurrence_quarantined_provider", table_name="occurrence_quarantined")
    op.drop_table("occurrence_quarantined")
    with op.batch_alter_table("raster_assets") as batch_op:
        batch_op.drop_column("bands_available")
        batch_op.drop_column("estimated_size_mb")
        batch_op.drop_column("requires_auth")
        batch_op.drop_column("download_status")
        batch_op.drop_column("local_path")
        batch_op.drop_column("product_type")
        batch_op.drop_column("platform")

