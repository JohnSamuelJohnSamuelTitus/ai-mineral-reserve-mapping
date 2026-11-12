"""Unit tests for geological normalization, CRS reprojection, quarantine, and multi-format import."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from app.geological.importers import import_and_normalize_geological_file
from app.geological.normalizer import normalize_commodity_token, normalize_occurrence_records
from app.geological.quality import SCIENTIFIC_BIAS_WARNING, build_dataset_quality_report


def test_commodity_symbol_normalization() -> None:
    assert normalize_commodity_token("copper") == "Cu"
    assert normalize_commodity_token("  GOLD ") == "Au"
    assert normalize_commodity_token("Iron Ore") == "Fe"
    assert normalize_commodity_token("zn") == "Zn"


def test_normalization_quarantines_bad_and_duplicate_rows() -> None:
    raw = [
        {"id": "GSI-1", "name": "Khetri South", "commodity": "copper; gold", "lon": 75.8, "lat": 28.0},
        {"id": "GSI-2", "name": "No Coords", "commodity": "Cu"},
        {"id": "GSI-3", "name": "Bad Lat", "commodity": "Cu", "lon": 75.8, "lat": 120.0},
        {"id": "GSI-4", "name": "Null Island", "commodity": "Fe", "lon": 0.0, "lat": 0.0},
        {"id": "GSI-1", "name": "Duplicate ID", "commodity": "Cu", "lon": 75.81, "lat": 28.01},
        {"id": "GSI-5", "name": "Khetri South", "commodity": "Cu", "lon": 75.80001, "lat": 28.00001},
    ]
    batch = normalize_occurrence_records(
        raw,
        source_provider_key="ngdr_geodataindia",
        license_name="GODL-India",
        label_authority="indian_official",
        data_origin="synthetic",
    )
    assert len(batch.accepted) == 1
    assert batch.accepted[0].commodity_primary == "Cu"
    assert batch.accepted[0].commodities_all == ["Cu", "Au"]
    assert len(batch.quarantined) == 5
    reasons = {q.external_id: q.rejection_reason for q in batch.quarantined}
    assert reasons["GSI-2"] == "missing_coordinates"
    assert reasons["GSI-3"] == "invalid_wgs84_coordinates"
    assert reasons["GSI-4"] == "invalid_wgs84_coordinates"
    assert reasons["GSI-1"] == "duplicate_external_id"
    assert reasons["GSI-5"] == "duplicate_spatial_location_name"

    report = build_dataset_quality_report(
        dataset_name="khetri_sample.csv",
        source_provider_key="ngdr_geodataindia",
        data_origin="synthetic",
        batch=batch,
        aoi_bbox=(75.7, 27.9, 75.9, 28.1),
    )
    assert report["accepted_rows"] == 1
    assert report["rejected_rows"] == 5
    assert report["duplicate_rows"] == 2
    assert SCIENTIFIC_BIAS_WARNING in report["warnings"]


def test_import_utm_csv_geopackage_and_zipped_shapefile(tmp_path: Path) -> None:
    # 1. UTM Zone 43N CSV (~578000E, 3097000N -> near Khetri ~75.79E, 28.00N)
    csv_path = tmp_path / "khetri_utm.csv"
    csv_path.write_text(
        "external_id,name,commodity,x,y,state\nIND-UTM-1,Madhan Kudhan,Copper,578000,3097000,Rajasthan\n",
        encoding="utf-8",
    )
    res_csv = import_and_normalize_geological_file(
        csv_path,
        source_provider_key="ngdr_geodataindia",
        license_name="GODL-India",
        label_authority="indian_official",
        data_origin="synthetic",
        input_epsg=32643,
    )
    assert len(res_csv.accepted) == 1
    assert 75.7 < res_csv.accepted[0].lon < 75.9
    assert 27.9 < res_csv.accepted[0].lat < 28.1

    # 2. GeoPackage + zipped Shapefile in EPSG:32643
    gdf = gpd.GeoDataFrame(
        [{"occurrence_id": "GPKG-1", "name": "Kolihan", "commodity": "Cu"}],
        geometry=[Point(577500, 3098000)],
        crs="EPSG:32643",
    )
    gpkg_path = tmp_path / "occurrences.gpkg"
    gdf.to_file(gpkg_path, driver="GPKG")
    res_gpkg = import_and_normalize_geological_file(
        gpkg_path,
        source_provider_key="ngdr_geodataindia",
        license_name="GODL-India",
        label_authority="indian_official",
        data_origin="synthetic",
    )
    assert len(res_gpkg.accepted) == 1
    assert pytest.approx(res_gpkg.accepted[0].lat, abs=0.05) == 28.0

    shp_dir = tmp_path / "shp_src"
    shp_dir.mkdir()
    shp_file = shp_dir / "occurrences.shp"
    gdf.to_file(shp_file)
    zip_path = tmp_path / "occurrences_shp.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, arcname=f.name)

    res_zip = import_and_normalize_geological_file(
        zip_path,
        source_provider_key="ngdr_geodataindia",
        license_name="GODL-India",
        label_authority="indian_official",
        data_origin="synthetic",
    )
    assert len(res_zip.accepted) == 1
    assert res_zip.accepted[0].name == "Kolihan"


def test_geojson_import_validates_format(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.geojson"
    bad_json.write_text(json.dumps({"type": "Point"}), encoding="utf-8")
    with pytest.raises(ValueError, match="FeatureCollection"):
        import_and_normalize_geological_file(
            bad_json,
            source_provider_key="ngdr_geodataindia",
            license_name="GODL",
            label_authority="indian_official",
        )

