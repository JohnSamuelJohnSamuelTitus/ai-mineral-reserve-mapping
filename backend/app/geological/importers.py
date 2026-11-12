"""Authorized multi-format geological file importers (CSV, GeoJSON, GPKG, Shapefile ZIP)."""

from __future__ import annotations

import csv
import json
import math
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd

from app.geological.normalizer import NormalizationBatchResult, normalize_occurrence_records
from app.storage.manager import managed_temp_dir, sanitize_filename

SUPPORTED_EXTENSIONS = {".csv", ".geojson", ".json", ".gpkg", ".zip", ".shp"}


def _dataframe_to_raw_rows(gdf: gpd.GeoDataFrame) -> tuple[list[dict[str, Any]], int]:
    """Reproject non-WGS84 GeoDataFrame when needed and extract centroid/point coordinates."""
    src_epsg = 4326
    if gdf.crs is not None:
        detected = gdf.crs.to_epsg()
        if detected:
            src_epsg = int(detected)
        if src_epsg != 4326:
            gdf = gdf.to_crs(epsg=4326)

    raw_rows: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        props = {k: (None if _is_na(v) else v) for k, v in row.items() if k != "geometry"}
        geom = row.get("geometry")
        if geom is not None and not geom.is_empty:
            pt = geom.centroid if geom.geom_type != "Point" else geom
            props["lon"] = float(pt.x)
            props["lat"] = float(pt.y)
        raw_rows.append(props)
    return raw_rows, src_epsg


def _is_na(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float):
        return math.isnan(val)
    return False


def parse_geological_file_to_raw_rows(
    file_path: Path,
    *,
    input_epsg: int = 4326,
) -> tuple[list[dict[str, Any]], int]:
    """Extract raw property dicts + lon/lat from CSV, GeoJSON, GPKG, or zipped Shapefile."""
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported geological file format '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if ext == ".csv":
        rows: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for r in reader:
                rows.append(dict(r))
        return rows, input_epsg

    if ext in (".geojson", ".json"):
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON file must be a valid FeatureCollection")
        rows = []
        for idx, feat in enumerate(payload.get("features") or []):
            if not isinstance(feat, dict):
                continue
            props = dict(feat.get("properties") or {})
            if "id" in feat and "id" not in props:
                props["id"] = feat["id"]
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            if geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
                props.setdefault("lon", coords[0])
                props.setdefault("lat", coords[1])
            elif "lon" not in props and "longitude" not in props:
                props.setdefault("_geometry_type", geom.get("type"))
                props.setdefault("_feature_index", idx)
            rows.append(props)
        return rows, input_epsg

    if ext == ".zip":
        with managed_temp_dir("shp_unzip_") as extract_dir:
            with zipfile.ZipFile(file_path, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    safe_name = sanitize_filename(member.filename)
                    target = (extract_dir / safe_name).resolve()
                    target.relative_to(extract_dir.resolve())
                    target.write_bytes(zf.read(member.filename))
            shp_files = list(extract_dir.glob("*.shp"))
            if not shp_files:
                raise ValueError("ZIP archive does not contain a .shp shapefile")
            gdf = gpd.read_file(shp_files[0])
            raw_rows, detected_epsg = _dataframe_to_raw_rows(gdf)
            return raw_rows, detected_epsg

    # .gpkg or .shp directly
    gdf = gpd.read_file(file_path)
    return _dataframe_to_raw_rows(gdf)


def import_and_normalize_geological_file(
    file_path: Path,
    *,
    source_provider_key: str,
    license_name: str,
    label_authority: str,
    data_origin: str = "real",
    input_epsg: int = 4326,
) -> NormalizationBatchResult:
    """Parse multi-format geological export and apply canonical normalization + quarantine."""
    raw_rows, _detected_epsg = parse_geological_file_to_raw_rows(file_path, input_epsg=input_epsg)
    # Note: GeoPandas already reprojected to 4326 if CRS existed, so only pass input_epsg for CSV/GeoJSON
    effective_epsg = (
        input_epsg if file_path.suffix.lower() in (".csv", ".geojson", ".json") else 4326
    )
    return normalize_occurrence_records(
        raw_rows,
        source_provider_key=source_provider_key,
        license_name=license_name,
        label_authority=label_authority,
        data_origin=data_origin,
        input_epsg=effective_epsg,
    )
