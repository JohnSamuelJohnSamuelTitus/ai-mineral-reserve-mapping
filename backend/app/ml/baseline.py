"""Readiness-gated scikit-learn spatial cross-validation baseline (PU proxy evaluation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, recall_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.db.models import MLDatasetVersion
from app.ml.dataset_builder import (
    PU_EXPLICIT_NEGATIVE,
    PU_KNOWN_OCCURRENCE,
    PU_UNLABELED_BACKGROUND,
)


def evaluate_spatial_baseline(
    *,
    db: Any,
    dataset: MLDatasetVersion,
) -> MLDatasetVersion:
    """Evaluate spatial GroupKFold baseline models STRICTLY if dataset passed readiness/leakage gates."""
    if not dataset.quality_passed or not dataset.leakage_checked:
        reasons = "; ".join(dataset.blocking_reasons_json or ["Dataset quality gates failed"])
        raise ValueError(
            f"Baseline training BLOCKED due to insufficient dataset readiness/leakage audit: {reasons}"
        )
    if not dataset.artifact_path or not Path(dataset.artifact_path).exists():
        raise FileNotFoundError("ML dataset CSV artifact missing on disk.")

    df = pd.read_csv(dataset.artifact_path)
    feature_cols: list[str] = list((dataset.stats_json or {}).get("feature_columns") or [])
    if not feature_cols:
        raise ValueError("No predictor feature columns recorded in dataset version.")

    # Convert known_occurrence -> 1, explicit_negative / unlabeled_background -> 0 (PU proxy)
    valid_rows = df["pu_label"].isin([PU_KNOWN_OCCURRENCE, PU_EXPLICIT_NEGATIVE, PU_UNLABELED_BACKGROUND])
    work = df.loc[valid_rows].copy()
    X = work[feature_cols].to_numpy(dtype=np.float64)
    y = (work["pu_label"] == PU_KNOWN_OCCURRENCE).astype(int).to_numpy()
    groups = work["spatial_block_id"].astype(str).to_numpy()

    pos_groups = set(groups[y == 1])
    n_splits = min(5, len(pos_groups))
    if n_splits < 2:
        raise ValueError("Spatial GroupKFold requires at least 2 distinct spatial blocks with positives.")

    gkf = GroupKFold(n_splits=n_splits)

    lr_oof = np.zeros(len(work), dtype=np.float64)
    rf_oof = np.zeros(len(work), dtype=np.float64)
    evaluated_mask = np.zeros(len(work), dtype=bool)
    rf_importances = np.zeros(len(feature_cols), dtype=np.float64)
    evaluated_folds = 0
    fold_reports: list[dict[str, Any]] = []

    for fold_idx, (train_idx, test_idx) in enumerate(gkf.split(X, y, groups), start=1):
        y_train, y_test = y[train_idx], y[test_idx]
        if len(np.unique(y_train)) < 2 or np.sum(y_test == 1) == 0:
            continue

        # Assert strict block disjointness between train and test folds
        train_blocks = set(groups[train_idx])
        test_blocks = set(groups[test_idx])
        if train_blocks & test_blocks:
            raise RuntimeError("Spatial leakage error: overlapping spatial blocks in CV fold.")

        lr_pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        class_weight="balanced", max_iter=500, random_state=dataset.seed
                    ),
                ),
            ]
        )
        rf_pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=100,
                        class_weight="balanced_subsample",
                        random_state=dataset.seed,
                        n_jobs=1,
                    ),
                ),
            ]
        )

        lr_pipe.fit(X[train_idx], y_train)
        rf_pipe.fit(X[train_idx], y_train)

        lr_prob = lr_pipe.predict_proba(X[test_idx])[:, 1]
        rf_prob = rf_pipe.predict_proba(X[test_idx])[:, 1]
        lr_oof[test_idx] = lr_prob
        rf_oof[test_idx] = rf_prob
        evaluated_mask[test_idx] = True
        rf_importances += rf_pipe.named_steps["clf"].feature_importances_
        evaluated_folds += 1

        fold_reports.append(
            {
                "fold": fold_idx,
                "test_positives": int(np.sum(y_test == 1)),
                "test_background": int(np.sum(y_test == 0)),
                "lr_recall_at_0_5": round(float(recall_score(y_test, lr_prob >= 0.5, zero_division=0)), 4),
                "rf_recall_at_0_5": round(float(recall_score(y_test, rf_prob >= 0.5, zero_division=0)), 4),
            }
        )

    if evaluated_folds == 0:
        raise ValueError("Unable to evaluate spatial CV: no folds had both positives and background.")

    rf_importances = rf_importances / evaluated_folds
    ranked_importance = sorted(
        [
            {"feature": col, "importance": round(float(imp), 4)}
            for col, imp in zip(feature_cols, rf_importances, strict=True)
        ],
        key=lambda x: x["importance"],
        reverse=True,
    )

    y_eval = y[evaluated_mask]
    lr_eval = lr_oof[evaluated_mask]
    rf_eval = rf_oof[evaluated_mask]

    metrics = {
        "evaluation_scheme": f"Spatial GroupKFold ({evaluated_folds} valid block-disjoint folds)",
        "pu_disclaimer": (
            "Metrics measure recovery of known mineral occurrences vs unlabeled background (PU proxy), "
            "NOT accuracy against confirmed barren ground or proven economic reserves."
        ),
        "logistic_regression": {
            "pu_recall_at_0_5": round(float(recall_score(y_eval, lr_eval >= 0.5, zero_division=0)), 4),
            "pu_pr_auc": round(float(average_precision_score(y_eval, lr_eval)), 4),
        },
        "random_forest": {
            "pu_recall_at_0_5": round(float(recall_score(y_eval, rf_eval >= 0.5, zero_division=0)), 4),
            "pu_pr_auc": round(float(average_precision_score(y_eval, rf_eval)), 4),
            "feature_importances": ranked_importance,
        },
        "folds": fold_reports,
    }

    updated_stats = dict(dataset.stats_json or {})
    updated_stats["baseline_metrics"] = metrics
    dataset.stats_json = updated_stats
    db.commit()
    db.refresh(dataset)
    return dataset
