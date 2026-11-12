# Spatial ML Dataset Preparation, PU Learning & Anti-Leakage Guide

Implemented in [`backend/app/ml/dataset_builder.py`](backend/app/ml/dataset_builder.py), [`backend/app/ml/baseline.py`](backend/app/ml/baseline.py), and [`backend/app/api/v1/ml_routes.py`](backend/app/api/v1/ml_routes.py).

---

## 1. Positive-Unlabeled (PU) Labeling Rigor

In mineral prospectivity mapping, historical mineral databases tell us where deposits or occurrences have been discovered (`known_occurrence`), **not** where bedrock has been conclusively proved barren across a region.

Therefore, `build_spatial_ml_dataset` enforces:
- **`PU_KNOWN_OCCURRENCE = "known_occurrence"`** (`label_int = 1`): Pixels falling on ML-eligible real known occurrences inside valid raster coverage.
- **`PU_UNLABELED_BACKGROUND = "unlabeled_background"`** (`label_int = -1`): Deterministically sampled background pixels drawn outside a metric exclusion halo (`exclusion_buffer_m = max(resolution_m * 1.5, block_size_m * 0.25)`) around every known occurrence.
- **`explicit_negative_count = 0`**: Unlabeled background pixels are **never** mislabeled as verified negatives unless explicit negative drill/survey evidence is supplied.

---

## 2. Deterministic Spatial Blocking (`B_{bx}_{by}`)

Random pixel-level train/test splits suffer from severe **spatial autocorrelation leakage**: neighboring pixels share lithology, alteration halos, and terrain values, falsely inflating accuracy metrics.

1. Every pixel center $(x_m, y_m)$ in the AOI UTM CRS is assigned deterministically to a metric spatial block:
   $$b_x = \left\lfloor \frac{x_m - \text{min}_x}{\text{block\_size\_m}} \right\rfloor, \quad b_y = \left\lfloor \frac{y_m - \text{min}_y}{\text{block\_size\_m}} \right\rfloor, \quad \text{id} = \text{B\_}\{b_x\}\_\text{\{}b_y\text{\}}$$
2. Background sampling uses `np.random.default_rng(seed)` so repeated builds with identical `seed`, `manifest_id`, and `block_size_m` produce **byte-identical datasets**.

---

## 3. Anti-Leakage & Licensing Checks

1. **Target Leakage Guard (`LEAKAGE_SENSITIVE_FEATURES = {"dist_to_occurrence_m"}`):**
   - `dist_to_occurrence_m` is automatically stripped from predictor columns by default (`excluded_target_leakage_columns`).
   - If a user forces `include_dist_to_occurrence=True`, `target_leakage_detected` is marked `True`, a blocking reason is added, and downstream baseline evaluation is blocked.
2. **ML Licensing Enforcement (`is_ml_training_allowed`):**
   - Occurrences linked to non-ML sources such as `mindat_v1` (`is_ml_training_allowed = False`) are excluded before positive pixel labeling, and the excluded count is logged in `leakage_checks["excluded_non_ml_occurrences"]`.
3. **Origin Check:** Only `real` datasets pass readiness for model evaluation (`dataset_origin != "real"` blocks training).
4. **Duplicate Pixel Check:** Verifies zero `(row, col)` overlap between positive and background rows.

---

## 4. Readiness Quality Gates & Gated Baseline (`baseline.py`)

`build_spatial_ml_dataset` sets `quality_passed = True` and `leakage_checked = True` **only** if all gates pass:
- `positive_count >= min_positives` (default `10`)
- Distinct positive spatial blocks $\ge$ `min_positive_blocks` (default `3`)
- Independent predictor features $\ge 2$
- Valid raster coverage $\ge$ `min_valid_coverage_pct` (default `50.0%`)
- Zero target leakage, zero duplicate pixel overlap, `data_origin == "real"`

### Evaluation Endpoint (`POST /api/v1/ml/datasets/{dataset_id}/evaluate`)
- If `not quality_passed` or `not leakage_checked`, returns **`HTTP 422 Unprocessable Content`** with explicit `blocking_reasons_json` — **refusing to train**.
- When ready, runs `GroupKFold(n_splits=min(5, len(pos_groups)))` grouped strictly by `spatial_block_id`, verifying zero train/test block overlap per fold.
- Evaluates `LogisticRegression` (median impute + `StandardScaler` + `class_weight="balanced"`) and `RandomForestClassifier` (`n_estimators=100`, `class_weight="balanced_subsample"`), reporting out-of-fold PU proxy metrics (`pu_recall_at_0_5`, `pu_pr_auc`), ranked RF feature importances, and an explicit PU disclaimer (`"Evaluation treats unlabeled_background as negative proxy (PU setting); metrics measure relative positive ranking under exploration bias, not true reserve probability."`).
