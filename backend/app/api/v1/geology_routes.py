"""Geological import, occurrence normalization, quarantine, and data quality endpoints."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from shapely.geometry import Point, shape
from sqlalchemy.orm import Session

from app.api.v1.schemas import DatasetQualityReportResponse, QuarantinedRecordResponse
from app.core.config import Settings, get_settings
from app.db.models import DatasetQualityReport, MineralOccurrence, OccurrenceQuarantine
from app.db.repositories import (
    AOIRepository,
    DataSourceRepository,
    MineralOccurrenceRepository,
    QuarantineAndQualityRepository,
)
from app.db.session import get_db
from app.geological.importers import SUPPORTED_EXTENSIONS, import_and_normalize_geological_file
from app.geological.quality import build_dataset_quality_report
from app.storage.manager import (
    StorageLimitError,
    UnsafePathError,
    managed_temp_dir,
    sanitize_filename,
    validate_file_size,
)

router = APIRouter(prefix="/geology", tags=["geology"])


@router.post("/aois/{aoi_id}/import", response_model=DatasetQualityReportResponse)
async def import_authorized_geological_file(
    aoi_id: str,
    file: UploadFile = File(...),
    source_provider_key: str = Form(default="ngdr_geodataindia"),
    data_origin: Literal["real", "synthetic", "demonstration"] = Form(default="real"),
    input_epsg: int = Form(default=4326, ge=2000, le=999999),
    clip_to_aoi: bool = Form(default=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DatasetQualityReportResponse:
    """Import GSI/NGDR/IBM or external GeoJSON/CSV/GPKG/Shapefile ZIP with full QA & quarantine."""
    aoi = AOIRepository(db).get(aoi_id)
    if aoi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")

    source = DataSourceRepository(db).get_by_key(source_provider_key)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown source_provider_key '{source_provider_key}'",
        )

    raw_name = sanitize_filename(file.filename or "dataset.csv")
    suffix = f".{raw_name.rsplit('.', 1)[-1].lower()}" if "." in raw_name else ""
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    payload = await file.read()
    try:
        validate_file_size(len(payload), max_mb=settings.upload_max_file_mb)
    except StorageLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc

    with managed_temp_dir("geo_import_") as tmpdir:
        safe_tmp_file = (tmpdir / raw_name).resolve()
        try:
            safe_tmp_file.relative_to(tmpdir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsafe filename") from exc
        safe_tmp_file.write_bytes(payload)

        try:
            batch = import_and_normalize_geological_file(
                safe_tmp_file,
                source_provider_key=source.provider_key,
                license_name=source.license,
                label_authority=source.label_authority,
                data_origin=data_origin,
                input_epsg=input_epsg,
            )
        except (UnsafePathError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    aoi_poly = shape(json.loads(aoi.geom_geojson))
    to_persist: list[MineralOccurrence] = []
    for norm in batch.accepted:
        if clip_to_aoi and not aoi_poly.intersects(Point(norm.lon, norm.lat)):
            continue
        to_persist.append(
            MineralOccurrence(
                source_id=source.id,
                aoi_id=aoi.id,
                external_id=norm.external_id,
                name=norm.name,
                commodity_primary=norm.commodity_primary,
                commodities_all=norm.commodities_all,
                occurrence_type=norm.occurrence_type,
                deposit_type=norm.deposit_type,
                geologic_age=norm.geologic_age,
                host_rock=norm.host_rock,
                jurisdiction="IN" if source.label_authority == "indian_official" else (norm.country or aoi.jurisdiction),
                label_authority=source.label_authority,
                data_origin=data_origin,
                lon=norm.lon,
                lat=norm.lat,
                geom_geojson=json.dumps({"type": "Point", "coordinates": [norm.lon, norm.lat]}),
                raw_attributes=norm.raw_attributes,
                collected_at=norm.collection_date,
            )
        )

    if to_persist:
        MineralOccurrenceRepository(db).upsert_many(to_persist)

    summary = build_dataset_quality_report(
        dataset_name=raw_name,
        source_provider_key=source.provider_key,
        data_origin=data_origin,
        batch=batch,
        aoi_bbox=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
    )

    report_row = DatasetQualityReport(
        aoi_id=aoi.id,
        source_provider_key=source.provider_key,
        dataset_name=summary["dataset_name"],
        data_origin=data_origin,
        total_rows=summary["total_rows"],
        accepted_rows=summary["accepted_rows"],
        rejected_rows=summary["rejected_rows"],
        duplicate_rows=summary["duplicate_rows"],
        missing_coords_count=summary["missing_coords_count"],
        invalid_coords_count=summary["invalid_coords_count"],
        missing_commodity_count=summary["missing_commodity_count"],
        completeness_pct=summary["completeness_pct"],
        commodity_distribution=summary["commodity_distribution"],
        warnings_json=summary["warnings"],
        report_json=summary,
    )
    quarantine_rows = [
        OccurrenceQuarantine(
            aoi_id=aoi.id,
            source_provider_key=q.source_provider_key,
            external_id=q.external_id,
            rejection_reason=q.rejection_reason,
            quality_flags=q.quality_flags,
            raw_record=q.raw_record,
        )
        for q in batch.quarantined
    ]
    saved_report = QuarantineAndQualityRepository(db).save_report_and_quarantine(
        report_row, quarantine_rows
    )
    return DatasetQualityReportResponse(
        id=saved_report.id,
        aoi_id=saved_report.aoi_id,
        source_provider_key=saved_report.source_provider_key,
        dataset_name=saved_report.dataset_name,
        data_origin=saved_report.data_origin,
        total_rows=saved_report.total_rows,
        accepted_rows=saved_report.accepted_rows,
        rejected_rows=saved_report.rejected_rows,
        duplicate_rows=saved_report.duplicate_rows,
        missing_coords_count=saved_report.missing_coords_count,
        invalid_coords_count=saved_report.invalid_coords_count,
        missing_commodity_count=saved_report.missing_commodity_count,
        completeness_pct=saved_report.completeness_pct,
        commodity_distribution=saved_report.commodity_distribution,
        warnings=saved_report.warnings_json,
        created_at=saved_report.created_at,
    )


@router.get("/aois/{aoi_id}/quality-reports", response_model=list[DatasetQualityReportResponse])
def list_quality_reports(aoi_id: str, db: Session = Depends(get_db)) -> list[DatasetQualityReportResponse]:
    if AOIRepository(db).get(aoi_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")
    reports = QuarantineAndQualityRepository(db).list_reports_for_aoi(aoi_id)
    return [
        DatasetQualityReportResponse(
            id=r.id,
            aoi_id=r.aoi_id,
            source_provider_key=r.source_provider_key,
            dataset_name=r.dataset_name,
            data_origin=r.data_origin,
            total_rows=r.total_rows,
            accepted_rows=r.accepted_rows,
            rejected_rows=r.rejected_rows,
            duplicate_rows=r.duplicate_rows,
            missing_coords_count=r.missing_coords_count,
            invalid_coords_count=r.invalid_coords_count,
            missing_commodity_count=r.missing_commodity_count,
            completeness_pct=r.completeness_pct,
            commodity_distribution=r.commodity_distribution,
            warnings=r.warnings_json,
            created_at=r.created_at,
        )
        for r in reports
    ]


@router.get("/aois/{aoi_id}/quarantine", response_model=list[QuarantinedRecordResponse])
def list_quarantined_records(
    aoi_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[QuarantinedRecordResponse]:
    if AOIRepository(db).get(aoi_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AOI not found")
    rows = QuarantineAndQualityRepository(db).list_quarantined_for_aoi(aoi_id, limit=limit)
    return [
        QuarantinedRecordResponse(
            id=q.id,
            aoi_id=q.aoi_id,
            source_provider_key=q.source_provider_key,
            external_id=q.external_id,
            rejection_reason=q.rejection_reason,
            quality_flags=q.quality_flags,
            raw_record=q.raw_record,
            created_at=q.created_at,
        )
        for q in rows
    ]

