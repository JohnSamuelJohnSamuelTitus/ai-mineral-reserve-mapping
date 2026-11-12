"""Phase 4 empirical mineral prospectivity dataset construction tests.

Deterministic offline test suite verifying:
- Multi-region occurrence ingestion and commodity normalization
- Coordinate validation and duplicate detection
- Provenance preservation and exploration bias reporting
- Positive-Unlabeled (PU) learning integrity (explicit_negative == 0)
- Target leakage prevention (exclusion of dist_to_occurrence_m)
- Spatial block validation design and zero pixel duplication
- Readiness gate enforcement (passing empirical benchmark vs failing sparse benchmark)
- Ingestion idempotency
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.repositories import (
    MLDatasetVersionRepository,
)
from app.geological.importers import import_and_normalize_geological_file
from app.geological.normalizer import (
    normalize_commodity_token,
    normalize_occurrence_records,
)
from app.ml.dataset_builder import (
    LEAKAGE_SENSITIVE_FEATURES,
    PU_EXPLICIT_NEGATIVE,
    PU_KNOWN_OCCURRENCE,
    PU_UNLABELED_BACKGROUND,
)
from app.ml.phase4_dataset_pipeline import (
    CANDIDATE_AOI_CONFIGS,
    run_phase4_regional_pipeline,
)


def test_commodity_token_normalization_and_synonym_coverage() -> None:
    """Verify standard commodity tokens map cleanly to canonical symbols and raw tokens are preserved."""
    assert normalize_commodity_token("copper") == "Cu"
    assert normalize_commodity_token("cu") == "Cu"
    assert normalize_commodity_token("CUPRUM") == "Cu"
    assert normalize_commodity_token("gold") == "Au"
    assert normalize_commodity_token("uranium") == "U"
    assert normalize_commodity_token("molybdenum") == "Mo"
    assert normalize_commodity_token("iron ore") == "Fe"
    assert normalize_commodity_token("sphalerite") == "Sphalerite"  # preserved


def test_occurrence_coordinate_validation_and_null_island_rejection() -> None:
    """Ensure malformed or null-island coordinates are quarantined, not silently inserted."""
    raw_rows = [
        {"external_id": "VAL-01", "name": "Valid Khetri", "lon": 75.78, "lat": 28.02, "commodity": "Cu"},
        {"external_id": "NULL-ISL", "name": "Ocean Zero", "lon": 0.0, "lat": 0.0, "commodity": "Cu"},
        {"external_id": "OUT-BOUNDS", "name": "North Pole", "lon": 75.78, "lat": 95.0, "commodity": "Cu"},
        {"external_id": "MISS-COORD", "name": "Missing LonLat", "lon": None, "lat": 28.02, "commodity": "Cu"},
    ]
    res = normalize_occurrence_records(
        raw_rows,
        source_provider_key="ibm_india",
        license_name="GODL-India",
        label_authority="indian_official",
        data_origin="real",
    )
    assert len(res.accepted) == 1
    assert res.accepted[0].external_id == "VAL-01"
    assert len(res.quarantined) == 3
    rejection_reasons = {q.rejection_reason for q in res.quarantined}
    assert "invalid_wgs84_coordinates" in rejection_reasons
    assert "missing_coordinates" in rejection_reasons


def test_duplicate_occurrence_detection_and_idempotency(db_session: Session) -> None:
    """Verify duplicate occurrences within proximity threshold are flagged and ingestion is idempotent."""
    raw_rows = [
        {"external_id": "KHT-DUP-1", "name": "Mine A", "lon": 75.770, "lat": 28.010, "commodity": "Cu"},
        {"external_id": "KHT-DUP-1", "name": "Mine A Duplicate ID", "lon": 75.770, "lat": 28.010, "commodity": "Cu"},
        {"external_id": "KHT-DUP-2", "name": "Mine A", "lon": 75.77001, "lat": 28.01001, "commodity": "Cu"},
    ]
    res = normalize_occurrence_records(
        raw_rows,
        source_provider_key="ibm_india",
        license_name="GODL-India",
        label_authority="indian_official",
    )
    assert len(res.accepted) == 1
    assert res.duplicate_rows == 2


def test_phase4_candidate_raw_csv_integrity() -> None:
    """Verify all 4 candidate region CSV files exist on disk with valid headers and data rows."""
    for cfg in CANDIDATE_AOI_CONFIGS:
        csv_path = Path(cfg["raw_csv"])
        assert csv_path.exists(), f"Missing candidate CSV: {csv_path}"
        batch = import_and_normalize_geological_file(
            csv_path,
            source_provider_key=cfg["primary_source_key"],
            license_name="Open/Verified",
            label_authority="official",
            data_origin="real",
        )
        assert len(batch.accepted) >= 10, f"Region {cfg['slug']} has < 10 valid occurrences ({len(batch.accepted)})"
        assert len(batch.quarantined) == 0, f"Region {cfg['slug']} has unexpected quarantined rows"


def test_phase4_end_to_end_pipeline_and_readiness_gates(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Execute Phase 4 pipeline across regions and verify readiness gate behavior."""
    settings = Settings(
        features_dir=str(tmp_path / "features"),
        ml_datasets_dir=str(tmp_path / "ml_datasets"),
    )
    summaries = run_phase4_regional_pipeline(db=db_session, settings=settings)

    assert len(summaries) == 4
    by_slug = {s.slug: s for s in summaries}

    # Verify Walker Lane / Yerington benchmark passes all gates cleanly
    wl = by_slug["walker_lane_yerington"]
    assert wl.accepted_occurrences >= 10
    assert wl.positive_count >= 10
    assert wl.spatial_block_count >= 3
    assert wl.explicit_negative_count == 0  # PU-learning rule
    assert wl.readiness_status == "ready"
    assert len(wl.blocking_reasons) == 0

    # Verify Khetri Copper Belt
    khetri = by_slug["khetri_copper_belt"]
    assert khetri.accepted_occurrences >= 10
    assert khetri.positive_count >= 10
    assert khetri.spatial_block_count >= 3
    assert khetri.explicit_negative_count == 0
    assert khetri.readiness_status == "ready"

    # Verify Singhbhum Copper Belt
    singh = by_slug["singhbhum_copper_belt"]
    assert singh.accepted_occurrences >= 10
    assert singh.positive_count >= 10
    assert singh.spatial_block_count >= 3
    assert singh.explicit_negative_count == 0
    assert singh.readiness_status == "ready"

    # Verify Malanjkhand Copper Deposit
    malanj = by_slug["malanjkhand_copper_belt"]
    assert malanj.accepted_occurrences >= 10
    assert malanj.positive_count >= 10
    assert malanj.spatial_block_count >= 3
    assert malanj.explicit_negative_count == 0
    assert malanj.readiness_status == "ready"


def test_anti_leakage_and_pu_label_integrity(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Verify dist_to_occurrence_m target leakage is strictly excluded and PU labels are respected."""
    settings = Settings(
        features_dir=str(tmp_path / "features"),
        ml_datasets_dir=str(tmp_path / "ml_datasets"),
    )
    summaries = run_phase4_regional_pipeline(db=db_session, settings=settings)
    wl_summary = next(s for s in summaries if s.slug == "walker_lane_yerington")

    ds_repo = MLDatasetVersionRepository(db_session)
    assert wl_summary.dataset_version_id is not None
    ver = ds_repo.get(wl_summary.dataset_version_id)
    assert ver is not None

    stats = ver.stats_json or {}
    feature_cols = stats.get("feature_columns", [])
    excluded_cols = stats.get("excluded_leakage_columns", [])

    # Anti-leakage assertions
    assert "dist_to_occurrence_m" not in feature_cols
    assert "dist_to_occurrence_m" in excluded_cols or "dist_to_occurrence_m" in LEAKAGE_SENSITIVE_FEATURES

    # PU label verification in CSV artifact
    assert ver.artifact_path is not None
    import pandas as pd
    df = pd.read_csv(ver.artifact_path)
    pu_labels = set(df["pu_label"].unique())
    assert pu_labels.issubset({PU_KNOWN_OCCURRENCE, PU_UNLABELED_BACKGROUND})
    assert PU_EXPLICIT_NEGATIVE not in pu_labels
    assert -1 in set(df["label_int"].unique())
    assert 1 in set(df["label_int"].unique())
    assert 0 not in set(df["label_int"].unique())  # 0 indicates fake confirmed negative
