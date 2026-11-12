"""Geological dataset quality assessment reports and scientific caveats."""

from __future__ import annotations

from collections import Counter

from app.geological.normalizer import NormalizationBatchResult

SCIENTIFIC_BIAS_WARNING = (
    "Absence of recorded mineral occurrences does NOT prove an area is mineral-free; "
    "databases reflect historical exploration intensity, access, and reporting completeness."
)


def build_dataset_quality_report(
    *,
    dataset_name: str,
    source_provider_key: str,
    data_origin: str,
    batch: NormalizationBatchResult,
    aoi_bbox: tuple[float, float, float, float] | None = None,
) -> dict:
    """Compute quantitative quality metrics and scientific warnings for a normalized dataset."""
    commodity_counts: Counter[str] = Counter()
    in_aoi_count = 0
    flagged_count = 0
    for rec in batch.accepted:
        for comm in rec.commodities_all or ["UNKNOWN"]:
            commodity_counts[comm] += 1
        if rec.quality_flags:
            flagged_count += 1
        if aoi_bbox is not None:
            min_lon, min_lat, max_lon, max_lat = aoi_bbox
            if min_lon <= rec.lon <= max_lon and min_lat <= rec.lat <= max_lat:
                in_aoi_count += 1

    accepted_count = len(batch.accepted)
    rejected_count = len(batch.quarantined)
    completeness_pct = (
        round((accepted_count - batch.missing_commodity_count) / max(batch.total_rows, 1) * 100.0, 2)
        if batch.total_rows > 0
        else 0.0
    )

    warnings: list[str] = [SCIENTIFIC_BIAS_WARNING]
    if rejected_count > 0:
        warnings.append(
            f"{rejected_count} record(s) quarantined due to missing/invalid coordinates, CRS issues, or duplicates."
        )
    if batch.missing_commodity_count > 0:
        warnings.append(f"{batch.missing_commodity_count} accepted record(s) lack commodity tags.")
    if data_origin != "real":
        warnings.append(f"Dataset flagged with non-real origin '{data_origin}'; keep isolated from real labels.")

    return {
        "dataset_name": dataset_name,
        "source_provider_key": source_provider_key,
        "data_origin": data_origin,
        "total_rows": batch.total_rows,
        "accepted_rows": accepted_count,
        "rejected_rows": rejected_count,
        "duplicate_rows": batch.duplicate_rows,
        "missing_coords_count": batch.missing_coords_count,
        "invalid_coords_count": batch.invalid_coords_count,
        "missing_commodity_count": batch.missing_commodity_count,
        "flagged_accepted_count": flagged_count,
        "in_aoi_bbox_count": in_aoi_count if aoi_bbox is not None else None,
        "completeness_pct": completeness_pct,
        "commodity_distribution": dict(commodity_counts),
        "warnings": warnings,
    }
