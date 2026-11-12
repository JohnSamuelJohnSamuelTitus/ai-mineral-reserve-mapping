"""Spatial ML dataset preparation, readiness inspection, and gated baseline evaluation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.schemas import MLDatasetBuildRequest, MLDatasetVersionResponse
from app.core.config import Settings, get_settings
from app.db.models import MLDatasetVersion
from app.db.repositories import AOIRepository, MLDatasetVersionRepository
from app.db.session import get_db
from app.ml.baseline import evaluate_spatial_baseline
from app.ml.dataset_builder import build_spatial_ml_dataset
from app.storage.manager import StorageLimitError

router = APIRouter(prefix="/ml", tags=["ml"])


def _ml_version_to_response(m: MLDatasetVersion) -> MLDatasetVersionResponse:
    stats = m.stats_json or {}
    return MLDatasetVersionResponse(
        id=m.id,
        aoi_id=m.aoi_id,
        manifest_id=m.manifest_id,
        version_tag=m.version_tag,
        seed=m.seed,
        positive_count=m.positive_count,
        unlabeled_count=m.unlabeled_count,
        explicit_negative_count=m.explicit_negative_count,
        spatial_block_count=m.spatial_block_count,
        feature_columns=list(stats.get("feature_columns") or []),
        readiness_status="ready" if (m.quality_passed and m.leakage_checked) else "blocked",
        blocking_reasons=list(m.blocking_reasons_json or []),
        leakage_checks=dict(stats.get("leakage_checks") or {}),
        metrics_json=dict(stats.get("baseline_metrics") or {}),
        artifact_path=m.artifact_path,
        data_origin=m.data_origin,
        created_at=m.created_at,
    )


@router.post("/aois/{aoi_id}/datasets/build", response_model=MLDatasetVersionResponse)
def build_ml_dataset_for_aoi(
    aoi_id: str,
    payload: MLDatasetBuildRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MLDatasetVersionResponse:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    try:
        outcome = build_spatial_ml_dataset(
            db=db,
            aoi=aoi,
            settings=settings,
            manifest_id=payload.manifest_id,
            version_tag=payload.version_tag,
            block_size_m=payload.block_size_m,
            seed=payload.seed,
            include_dist_to_occurrence=payload.include_dist_to_occurrence,
            min_positives=payload.min_positives,
            min_positive_blocks=payload.min_positive_blocks,
            min_valid_coverage_pct=payload.min_valid_coverage_pct,
        )
    except StorageLimitError as exc:
        raise HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return _ml_version_to_response(outcome.version)


@router.get("/aois/{aoi_id}/datasets", response_model=list[MLDatasetVersionResponse])
def list_ml_datasets_for_aoi(
    aoi_id: str,
    db: Session = Depends(get_db),
) -> list[MLDatasetVersionResponse]:
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")
    versions = MLDatasetVersionRepository(db).list_for_aoi(aoi_id)
    return [_ml_version_to_response(v) for v in versions]


@router.get("/datasets/{dataset_id}", response_model=MLDatasetVersionResponse)
def get_ml_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> MLDatasetVersionResponse:
    version = MLDatasetVersionRepository(db).get(dataset_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ML dataset not found")
    return _ml_version_to_response(version)


@router.post("/datasets/{dataset_id}/evaluate", response_model=MLDatasetVersionResponse)
def evaluate_ml_baseline_for_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> MLDatasetVersionResponse:
    version = MLDatasetVersionRepository(db).get(dataset_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ML dataset not found")
    try:
        updated = evaluate_spatial_baseline(db=db, dataset=version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _ml_version_to_response(updated)

