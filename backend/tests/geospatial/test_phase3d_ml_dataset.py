"""Tests for Phase 3D spatial ML dataset builder, PU labeling, leakage checks, and gated baseline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import DataSource, MineralOccurrence, RasterAsset
from app.db.repositories import AOIRepository, DataSourceRepository


def _setup_aoi_with_dem_and_occurrences(
    client: TestClient,
    db_session: Session,
    *,
    num_ml_occurrences: int,
    include_mindat_non_ml: bool = True,
) -> tuple[str, str, Settings]:
    settings: Settings = client.app.dependency_overrides[get_settings]()  # type: ignore[union-attr]

    aoi_resp = client.post(
        "/api/v1/aois",
        json={
            "name": "Khetri Phase3D ML Test AOI",
            "jurisdiction": "IN",
            "commodity_focus": ["Cu"],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [75.75, 27.95],
                        [75.85, 27.95],
                        [75.85, 28.05],
                        [75.75, 28.05],
                        [75.75, 27.95],
                    ]
                ],
            },
        },
    )
    assert aoi_resp.status_code == 201, aoi_resp.text
    aoi_id = aoi_resp.json()["id"]
    aoi = AOIRepository(db_session).get(aoi_id)
    assert aoi is not None

    # Write local synthetic EPSG:4326 DEM across AOI
    rasters_dir = settings.rasters_dir / aoi_id
    rasters_dir.mkdir(parents=True, exist_ok=True)
    dem_path = rasters_dir / "ml_dem_4326.tif"
    rows, cols = 60, 60
    xs = np.linspace(75.74, 75.86, cols, dtype=np.float32)
    ys = np.linspace(28.06, 27.94, rows, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    # Ridge structure correlated subtly with southern half where occurrences sit
    dem_vals = (400.0 + 120.0 * np.sin((xx - 75.74) * 40.0) + (28.06 - yy) * 800.0).astype(np.float32)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(75.74, 28.06, (75.86 - 75.74) / cols, (28.06 - 27.94) / rows),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem_vals, 1)

    cop_src = DataSourceRepository(db_session).get_by_key("copernicus_dem")
    assert cop_src is not None
    asset = RasterAsset(
        aoi_id=aoi.id,
        source_id=cop_src.id,
        stac_collection="cop-dem-glo-30",
        stac_item_id="ML_Test_DEM",
        asset_type="dem",
        acquired_at=datetime.now(UTC),
        resolution_m=30.0,
        footprint_geojson=json.dumps(
            {
                "type": "Polygon",
                "coordinates": [[[75.74, 27.94], [75.86, 27.94], [75.86, 28.06], [75.74, 28.06], [75.74, 27.94]]],
            }
        ),
        bbox_min_lon=75.74,
        bbox_min_lat=27.94,
        bbox_max_lon=75.86,
        bbox_max_lat=28.06,
        storage_uri="https://example.invalid/dem.tif",
        local_path=str(dem_path),
        download_status="downloaded",
        crs_epsg=4326,
        data_origin="real",
    )
    db_session.add(asset)

    ngdr_src: DataSource | None = DataSourceRepository(db_session).get_by_key("ngdr_geodataindia")
    assert ngdr_src is not None
    mindat_src = DataSourceRepository(db_session).get_by_key("mindat_v1")
    assert mindat_src is not None

    # Insert spatially distributed real ML-eligible occurrences across > 3 spatial blocks
    coords = [
        (75.76 + (i % 4) * 0.022, 27.96 + (i // 4) * 0.022)
        for i in range(num_ml_occurrences)
    ]
    for idx, (lon, lat) in enumerate(coords):
        db_session.add(
            MineralOccurrence(
                aoi_id=aoi.id,
                source_id=ngdr_src.id,
                external_id=f"ngdr-ml-{idx}",
                name=f"Prospect {idx}",
                commodity_primary="Cu",
                commodities_all=["Cu"],
                jurisdiction="IN",
                label_authority="national_gsi_ngdr",
                data_origin="real",
                lon=lon,
                lat=lat,
                geom_geojson=json.dumps({"type": "Point", "coordinates": [lon, lat]}),
            )
        )

    if include_mindat_non_ml:
        db_session.add(
            MineralOccurrence(
                aoi_id=aoi.id,
                source_id=mindat_src.id,
                external_id="mindat-blocked-1",
                name="Mindat Non-ML Locality",
                commodity_primary="Cu",
                commodities_all=["Cu"],
                jurisdiction="IN",
                label_authority="reference_only",
                data_origin="real",
                lon=75.80,
                lat=28.00,
                geom_geojson=json.dumps({"type": "Point", "coordinates": [75.80, 28.00]}),
            )
        )

    db_session.commit()

    # Extract features at 250m grid
    ext_resp = client.post(
        f"/api/v1/features/aois/{aoi_id}/extract",
        json={"resolution_m": 250.0, "dem_asset_id": asset.id, "include_geology": True, "run_sync": True},
    )
    assert ext_resp.status_code == 200, ext_resp.text
    manifest_id = ext_resp.json()["result_summary_json"]["manifest_id"]
    return aoi_id, manifest_id, settings


def test_ml_dataset_blocks_sparse_and_leakage_and_excludes_mindat(
    client: TestClient, db_session: Session
) -> None:
    aoi_id, manifest_id, _ = _setup_aoi_with_dem_and_occurrences(
        client, db_session, num_ml_occurrences=2, include_mindat_non_ml=True
    )

    # 1. Build with default thresholds (min 10 positives) -> must succeed build, mark BLOCKED
    build_resp = client.post(
        f"/api/v1/ml/aois/{aoi_id}/datasets/build",
        json={"manifest_id": manifest_id, "version_tag": "sparse-v1", "block_size_m": 1500.0},
    )
    assert build_resp.status_code == 200, build_resp.text
    ds = build_resp.json()
    assert ds["readiness_status"] == "blocked"
    assert ds["positive_count"] == 2
    assert ds["explicit_negative_count"] == 0  # Empty space never fabricated as barren negative
    assert ds["unlabeled_count"] > 0
    assert "dist_to_occurrence_m" not in ds["feature_columns"]
    assert ds["leakage_checks"]["excluded_non_ml_occurrences"] == 1
    assert ds["leakage_checks"]["random_split_used"] is False
    assert any("Insufficient ML-eligible positive occurrences" in r for r in ds["blocking_reasons"])

    # Attempting to train baseline on blocked dataset MUST fail with 422
    eval_resp = client.post(f"/api/v1/ml/datasets/{ds['id']}/evaluate")
    assert eval_resp.status_code == 422
    assert "BLOCKED" in eval_resp.json()["detail"]

    # Check PU labels written to CSV artifact
    df = pd.read_csv(ds["artifact_path"])
    assert set(df["pu_label"].unique()) == {"known_occurrence", "unlabeled_background"}
    assert "explicit_negative" not in set(df["pu_label"].unique())

    # 2. Explicitly enabling dist_to_occurrence_m must trip leakage gate even with relaxed min_positives
    leak_resp = client.post(
        f"/api/v1/ml/aois/{aoi_id}/datasets/build",
        json={
            "manifest_id": manifest_id,
            "version_tag": "leak-test",
            "include_dist_to_occurrence": True,
            "min_positives": 1,
            "min_positive_blocks": 1,
        },
    )
    assert leak_resp.status_code == 200
    leak_ds = leak_resp.json()
    assert leak_ds["readiness_status"] == "blocked"
    assert leak_ds["leakage_checks"]["target_leakage_detected"] is True
    assert any("leakage" in r.lower() for r in leak_ds["blocking_reasons"])


def test_ml_dataset_ready_reproducible_and_spatial_cv_baseline(
    client: TestClient, db_session: Session
) -> None:
    aoi_id, manifest_id, _ = _setup_aoi_with_dem_and_occurrences(
        client, db_session, num_ml_occurrences=12, include_mindat_non_ml=True
    )

    payload = {
        "manifest_id": manifest_id,
        "version_tag": "ready-v1",
        "block_size_m": 1500.0,
        "seed": 123,
        "min_positives": 10,
        "min_positive_blocks": 3,
    }
    r1 = client.post(f"/api/v1/ml/aois/{aoi_id}/datasets/build", json=payload)
    r2 = client.post(f"/api/v1/ml/aois/{aoi_id}/datasets/build", json=payload)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    d1, d2 = r1.json(), r2.json()
    assert d1["readiness_status"] == "ready"
    assert d1["positive_count"] == 12
    assert d1["spatial_block_count"] >= 4
    assert "dist_to_occurrence_m" not in d1["feature_columns"]

    # Determinism check: identical CSV feature/block sample rows under same seed
    df1 = pd.read_csv(Path(d1["artifact_path"]))
    df2 = pd.read_csv(Path(d2["artifact_path"]))
    pd.testing.assert_frame_equal(df1, df2)

    # Evaluate gated spatial CV baseline
    eval_resp = client.post(f"/api/v1/ml/datasets/{d1['id']}/evaluate")
    assert eval_resp.status_code == 200, eval_resp.text
    evaluated = eval_resp.json()
    metrics = evaluated["metrics_json"]
    assert "Spatial GroupKFold" in metrics["evaluation_scheme"]
    assert "unlabeled background" in metrics["pu_disclaimer"].lower()
    assert 0.0 <= metrics["logistic_regression"]["pu_pr_auc"] <= 1.0
    assert 0.0 <= metrics["random_forest"]["pu_pr_auc"] <= 1.0
    assert len(metrics["random_forest"]["feature_importances"]) == len(d1["feature_columns"])

