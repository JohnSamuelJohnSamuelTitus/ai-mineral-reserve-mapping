"""Reproducible spatial ML dataset builder with PU-learning rigor and leakage gating."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from app.core.config import Settings
from app.db.models import AreaOfInterest, FeatureManifest, MLDatasetVersion
from app.db.repositories import (
    FeatureManifestRepository,
    MineralOccurrenceRepository,
    MLDatasetVersionRepository,
)
from app.storage.manager import check_free_disk_space, resolve_safe_path, sanitize_filename

PU_KNOWN_OCCURRENCE = "known_occurrence"
PU_EXPLICIT_NEGATIVE = "explicit_negative"
PU_UNLABELED_BACKGROUND = "unlabeled_background"
PU_UNKNOWN = "unknown"

LEAKAGE_SENSITIVE_FEATURES = {"dist_to_occurrence_m"}


@dataclass(frozen=True)
class MLDatasetBuildOutcome:
    version: MLDatasetVersion
    dataset_csv_path: Path
    metadata_json_path: Path


def build_spatial_ml_dataset(
    *,
    db: Any,
    aoi: AreaOfInterest,
    settings: Settings,
    manifest_id: str | None = None,
    version_tag: str = "v1",
    block_size_m: float = 1000.0,
    seed: int = 42,
    include_dist_to_occurrence: bool = False,
    min_positives: int = 10,
    min_positive_blocks: int = 3,
    min_valid_coverage_pct: float = 50.0,
) -> MLDatasetBuildOutcome:
    """Build a deterministically blocked PU spatial ML dataset and run quality/leakage gates."""
    check_free_disk_space(settings.ml_datasets_dir, min_free_gb=settings.min_free_disk_gb, required_mb=20.0)

    man_repo = FeatureManifestRepository(db)
    if manifest_id is not None:
        manifest: FeatureManifest | None = man_repo.get(manifest_id)
    else:
        manifests = man_repo.list_for_aoi(aoi.id)
        manifest = manifests[0] if manifests else None

    if manifest is None or manifest.aoi_id != aoi.id:
        raise ValueError("No matching FeatureManifest found for this AOI; extract features first.")

    stack_raw = (manifest.output_files_json or {}).get("feature_stack_tif")
    if not stack_raw or not Path(stack_raw).exists():
        raise ValueError("FeatureManifest stack GeoTIFF is missing on disk.")
    stack_path = Path(stack_raw)

    # Read entire stack cleanly (bounded by <= 4096x4096 safety cap from 3B)
    with rasterio.open(stack_path) as src:
        band_data = src.read().astype(np.float32)  # shape: (B, H, W)
        transform = src.transform
        height, width = src.height, src.width
        nodata = float(src.nodata if src.nodata is not None else manifest.nodata_value)
        bounds = src.bounds

    all_features = list(manifest.feature_names or [])
    if len(all_features) != band_data.shape[0]:
        raise ValueError("Manifest feature_names count does not match GeoTIFF band count.")

    excluded_leakage_cols: list[str] = []
    selected_indices: list[int] = []
    feature_columns: list[str] = []
    target_leakage_detected = False

    for idx, fname in enumerate(all_features):
        if fname in LEAKAGE_SENSITIVE_FEATURES:
            if include_dist_to_occurrence:
                target_leakage_detected = True
                selected_indices.append(idx)
                feature_columns.append(fname)
            else:
                excluded_leakage_cols.append(fname)
            continue
        selected_indices.append(idx)
        feature_columns.append(fname)

    # Identify pixels where >=1 selected feature is valid
    if selected_indices:
        sub_stack = band_data[selected_indices]
        valid_any = np.any(np.isfinite(sub_stack) & (sub_stack != nodata), axis=0)
        valid_all = np.all(np.isfinite(sub_stack) & (sub_stack != nodata), axis=0)
    else:
        valid_any = np.zeros((height, width), dtype=bool)
        valid_all = np.zeros((height, width), dtype=bool)

    total_cells = height * width
    valid_coverage_pct = round(float(np.sum(valid_any)) / max(total_cells, 1) * 100.0, 2)

    # Query real ML-eligible occurrences vs restricted occurrences
    occ_repo = MineralOccurrenceRepository(db)
    occs_all = occ_repo.find_in_aoi(aoi, ml_trainable_only=False)
    occs_ml = occ_repo.find_in_aoi(aoi, ml_trainable_only=True)
    excluded_non_ml_count = len(occs_all) - len(occs_ml)

    observed_origins = {aoi.data_origin, manifest.data_origin}
    for occ in occs_ml:
        observed_origins.add(occ.data_origin)

    if "synthetic" in observed_origins:
        dataset_origin = "synthetic"
    elif "demonstration" in observed_origins:
        dataset_origin = "demonstration"
    else:
        dataset_origin = "real"

    # Project occurrences to metric raster pixels
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{manifest.target_crs_epsg}", always_xy=True)
    inv_transform = ~transform
    positive_pixels: dict[tuple[int, int], list[str]] = {}
    outside_or_nodata_positives = 0

    for occ in occs_ml:
        x_m, y_m = transformer.transform(occ.lon, occ.lat)
        col_f, row_f = inv_transform @ (x_m, y_m)
        row, col = math.floor(row_f), math.floor(col_f)
        if 0 <= row < height and 0 <= col < width and valid_any[row, col]:
            positive_pixels.setdefault((row, col), []).append(occ.id)
        else:
            outside_or_nodata_positives += 1

    # Helper to compute metric center + deterministic spatial block id for any pixel
    def _pixel_xy_block(r: int, c: int) -> tuple[float, float, str]:
        x_m, y_m = transform @ (c + 0.5, r + 0.5)
        bx = math.floor((x_m - bounds.left) / max(block_size_m, 10.0))
        by = math.floor((y_m - bounds.bottom) / max(block_size_m, 10.0))
        return float(x_m), float(y_m), f"B_{bx}_{by}"

    records: list[dict[str, Any]] = []
    pos_coords_m: list[tuple[float, float]] = []

    for (r, c), occ_ids in sorted(positive_pixels.items()):
        x_m, y_m, blk = _pixel_xy_block(r, c)
        pos_coords_m.append((x_m, y_m))
        rec: dict[str, Any] = {
            "row": r,
            "col": c,
            "x_m": round(x_m, 2),
            "y_m": round(y_m, 2),
            "spatial_block_id": blk,
            "pu_label": PU_KNOWN_OCCURRENCE,
            "label_int": 1,
            "source_occurrence_ids": "|".join(occ_ids),
        }
        for band_i, fname in zip(selected_indices, feature_columns, strict=True):
            val = float(band_data[band_i, r, c])
            rec[fname] = None if (not np.isfinite(val) or val == nodata) else round(val, 6)
        records.append(rec)

    # Sample deterministic unlabeled background pixels outside exclusion buffer around positives
    exclusion_buffer_m = max(manifest.resolution_m * 1.5, block_size_m * 0.25)
    valid_rc = np.argwhere(valid_any)
    candidate_bg: list[tuple[int, int]] = []
    for r_np, c_np in valid_rc:
        r, c = int(r_np), int(c_np)
        if (r, c) in positive_pixels:
            continue
        x_m, y_m, _ = _pixel_xy_block(r, c)
        if pos_coords_m:
            min_dist = min(math.hypot(x_m - px, y_m - py) for px, py in pos_coords_m)
            if min_dist < exclusion_buffer_m:
                continue
        candidate_bg.append((r, c))

    rng = np.random.default_rng(seed)
    target_bg = min(len(candidate_bg), max(50, len(positive_pixels) * 10))
    if target_bg > 0 and candidate_bg:
        chosen_idx = rng.choice(len(candidate_bg), size=target_bg, replace=False)
        for idx_bg in sorted(int(i) for i in chosen_idx):
            r, c = candidate_bg[idx_bg]
            x_m, y_m, blk = _pixel_xy_block(r, c)
            rec = {
                "row": r,
                "col": c,
                "x_m": round(x_m, 2),
                "y_m": round(y_m, 2),
                "spatial_block_id": blk,
                "pu_label": PU_UNLABELED_BACKGROUND,
                "label_int": -1,
                "source_occurrence_ids": "",
            }
            for band_i, fname in zip(selected_indices, feature_columns, strict=True):
                val = float(band_data[band_i, r, c])
                rec[fname] = None if (not np.isfinite(val) or val == nodata) else round(val, 6)
            records.append(rec)

    df = pd.DataFrame.from_records(records)
    positive_count = int(sum(1 for r in records if r["pu_label"] == PU_KNOWN_OCCURRENCE))
    unlabeled_count = int(sum(1 for r in records if r["pu_label"] == PU_UNLABELED_BACKGROUND))
    explicit_negative_count = 0  # Never auto-invented from unlabeled land

    all_blocks = sorted({r["spatial_block_id"] for r in records}) if records else []
    pos_blocks = sorted(
        {r["spatial_block_id"] for r in records if r["pu_label"] == PU_KNOWN_OCCURRENCE}
    )

    # Leakage verification checks
    pixel_keys = [(r["row"], r["col"]) for r in records]
    duplicate_pixel_overlap = len(pixel_keys) - len(set(pixel_keys))
    leakage_checks = {
        "duplicate_pixel_overlap": duplicate_pixel_overlap,
        "excluded_target_leakage_columns": excluded_leakage_cols,
        "target_leakage_detected": target_leakage_detected,
        "excluded_non_ml_occurrences": excluded_non_ml_count,
        "positive_to_background_min_buffer_m": round(exclusion_buffer_m, 2),
        "spatial_block_size_m": block_size_m,
        "random_split_used": False,
        "spatial_group_split_enforced": True,
    }

    blocking_reasons: list[str] = []
    if positive_count < min_positives:
        blocking_reasons.append(
            f"Insufficient ML-eligible positive occurrences: {positive_count} found inside valid raster coverage (minimum required: {min_positives})."
        )
    if len(pos_blocks) < min_positive_blocks:
        blocking_reasons.append(
            f"Insufficient spatial diversity across blocks: positives span {len(pos_blocks)} spatial block(s) (minimum required: {min_positive_blocks} at {block_size_m:.0f}m block size)."
        )
    if len(feature_columns) < 2:
        blocking_reasons.append(
            f"Insufficient independent predictor features ({len(feature_columns)} present; minimum required: 2)."
        )
    if valid_coverage_pct < min_valid_coverage_pct:
        blocking_reasons.append(
            f"Valid raster coverage is {valid_coverage_pct}% (minimum required: {min_valid_coverage_pct}%)."
        )
    if target_leakage_detected:
        blocking_reasons.append(
            "Target leakage detected: dist_to_occurrence_m cannot be included as an occurrence-prediction predictor."
        )
    if duplicate_pixel_overlap > 0:
        blocking_reasons.append(f"Detected {duplicate_pixel_overlap} duplicate pixel rows across classes.")
    if dataset_origin != "real":
        blocking_reasons.append(
            f"Dataset origin is '{dataset_origin}'; non-real data cannot enter empirical baseline training."
        )

    quality_passed = len(blocking_reasons) == 0

    version_id = str(uuid.uuid4())
    safe_aoi = sanitize_filename(aoi.id, fallback="aoi")
    out_dir = resolve_safe_path(settings.ml_datasets_dir, safe_aoi, version_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "dataset.csv"
    meta_path = out_dir / "metadata.json"

    df.to_csv(csv_path, index=False)

    stats_payload: dict[str, Any] = {
        "feature_columns": feature_columns,
        "excluded_leakage_columns": excluded_leakage_cols,
        "valid_coverage_pct": valid_coverage_pct,
        "all_valid_all_features_pixels": int(np.sum(valid_all)),
        "outside_or_nodata_positives": outside_or_nodata_positives,
        "positive_spatial_blocks": len(pos_blocks),
        "total_spatial_blocks": len(all_blocks),
        "block_size_m": block_size_m,
        "pu_policy": "Presence-Unlabeled: empty pixels are unlabeled_background (-1), NEVER barren_negative (0).",
        "leakage_checks": leakage_checks,
        "baseline_metrics": {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(
        json.dumps(
            {
                "version_id": version_id,
                "aoi_id": aoi.id,
                "manifest_id": manifest.id,
                "version_tag": version_tag,
                "seed": seed,
                "positive_count": positive_count,
                "unlabeled_count": unlabeled_count,
                "explicit_negative_count": explicit_negative_count,
                "spatial_block_count": len(all_blocks),
                "quality_passed": quality_passed,
                "blocking_reasons": blocking_reasons,
                "stats": stats_payload,
                "data_origin": dataset_origin,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    version_row = MLDatasetVersion(
        id=version_id,
        aoi_id=aoi.id,
        manifest_id=manifest.id,
        version_tag=version_tag,
        seed=seed,
        positive_count=positive_count,
        unlabeled_count=unlabeled_count,
        explicit_negative_count=explicit_negative_count,
        spatial_block_count=len(all_blocks),
        quality_passed=quality_passed,
        leakage_checked=True,
        blocking_reasons_json=blocking_reasons,
        stats_json=stats_payload,
        artifact_path=str(csv_path),
        data_origin=dataset_origin,
    )
    persisted = MLDatasetVersionRepository(db).create(version_row)
    return MLDatasetBuildOutcome(
        version=persisted,
        dataset_csv_path=csv_path,
        metadata_json_path=meta_path,
    )
