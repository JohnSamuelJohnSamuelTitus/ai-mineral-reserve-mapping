"""End-to-end geospatial feature-engineering pipeline for AOI feature stacks."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import Resampling

from app.core.config import Settings
from app.db.models import AreaOfInterest, FeatureManifest, RasterAsset
from app.db.repositories import (
    FeatureManifestRepository,
    GeologicalUnitRepository,
    MineralOccurrenceRepository,
    RasterAssetRepository,
)
from app.geospatial.proximity import compute_geological_features
from app.geospatial.raster_ops import (
    TargetGridSpec,
    align_raster_band_to_grid,
    build_aoi_target_grid,
    inspect_raster_metadata,
)
from app.geospatial.spectral import compute_aster_features, compute_sentinel2_features
from app.geospatial.terrain import compute_terrain_derivatives
from app.storage.manager import check_free_disk_space, resolve_safe_path, sanitize_filename

S2_BAND_ALIASES: dict[str, str] = {
    "b02": "B02",
    "blue": "B02",
    "b03": "B03",
    "green": "B03",
    "b04": "B04",
    "red": "B04",
    "b08": "B08",
    "nir": "B08",
    "b8a": "B8A",
    "nir08": "B8A",
    "b11": "B11",
    "swir16": "B11",
    "b12": "B12",
    "swir22": "B12",
    "scl": "SCL",
}


@dataclass(frozen=True)
class FeatureExtractionOutcome:
    manifest: FeatureManifest
    stack_path: Path
    manifest_json_path: Path
    feature_stats: dict[str, dict[str, float | int | None]]


def _summarize_feature_array(arr: np.ndarray, *, nodata: float) -> dict[str, float | int | None]:
    valid_mask = np.isfinite(arr) & (arr != nodata)
    total_px = int(arr.size)
    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        return {
            "valid_pixels": 0,
            "total_pixels": total_px,
            "valid_pct": 0.0,
            "min": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    vals = arr[valid_mask].astype(np.float64)
    return {
        "valid_pixels": valid_count,
        "total_pixels": total_px,
        "valid_pct": round((valid_count / max(total_px, 1)) * 100.0, 2),
        "min": round(float(np.min(vals)), 4),
        "max": round(float(np.max(vals)), 4),
        "mean": round(float(np.mean(vals)), 4),
        "std": round(float(np.std(vals)), 4),
    }


def _find_downloaded_dem_asset(assets: list[RasterAsset], preferred_id: str | None) -> RasterAsset | None:
    if preferred_id is not None:
        for asset in assets:
            if asset.id == preferred_id:
                return asset
        return None
    for asset in assets:
        col = (asset.stac_collection or "").lower()
        atype = (asset.asset_type or "").lower()
        if (
            asset.download_status == "downloaded"
            and asset.local_path
            and ("dem" in col or atype in {"data", "dem", "elevation"})
            and Path(asset.local_path).exists()
        ):
            return asset
    return None


def _normalize_s2_band_map(raw_paths: dict[str, Path]) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    for key, path in raw_paths.items():
        canon = S2_BAND_ALIASES.get(key.strip().lower(), key.strip().upper())
        normalized[canon] = path
    return normalized


def _write_feature_stack(
    *,
    stack_path: Path,
    grid: TargetGridSpec,
    features: dict[str, np.ndarray],
) -> list[str]:
    feature_names = list(features.keys())
    stack_path.parent.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": len(feature_names),
        "dtype": "float32",
        "crs": f"EPSG:{grid.crs_epsg}",
        "transform": grid.transform,
        "nodata": grid.nodata,
        "compress": "deflate",
    }
    if grid.width >= 16 and grid.height >= 16:
        profile.update(
            tiled=True,
            blockxsize=min(256, max(16, (grid.width // 16) * 16)),
            blockysize=min(256, max(16, (grid.height // 16) * 16)),
        )
    tmp_path = stack_path.with_suffix(".tif.tmp")
    with rasterio.open(tmp_path, "w", **profile) as dst:
        for idx, name in enumerate(feature_names, start=1):
            arr = features[name].astype(np.float32, copy=False)
            arr = np.where(np.isfinite(arr), arr, grid.nodata).astype(np.float32)
            dst.write(arr, idx)
            dst.set_band_description(idx, name)
    tmp_path.replace(stack_path)
    return feature_names


def extract_aoi_features(
    *,
    db: Any,
    aoi: AreaOfInterest,
    settings: Settings,
    resolution_m: float = 100.0,
    dem_asset_id: str | None = None,
    dem_local_path: Path | None = None,
    sentinel_band_paths: dict[str, Path] | None = None,
    aster_band_paths: dict[str, Path] | None = None,
    include_geology: bool = True,
    max_dimension_px: int = 4096,
) -> FeatureExtractionOutcome:
    """Build an aligned projected GeoTIFF feature stack and reproducible FeatureManifest for an AOI."""
    check_free_disk_space(settings.features_dir, min_free_gb=settings.min_free_disk_gb, required_mb=30.0)

    grid = build_aoi_target_grid(
        bbox_wgs84=(aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat),
        target_epsg=aoi.processing_epsg,
        resolution_m=resolution_m,
        max_dimension_px=max_dimension_px,
    )

    features: dict[str, np.ndarray] = {}
    feature_docs: list[dict[str, Any]] = []
    warnings: list[str] = []
    input_datasets: list[dict[str, Any]] = []
    input_scene_ids: list[str] = []
    observed_origins: set[str] = {aoi.data_origin}

    # 1. DEM Terrain Derivatives
    assets = RasterAssetRepository(db).list_for_aoi(aoi.id)
    chosen_dem_asset: RasterAsset | None = None
    resolved_dem_path: Path | None = dem_local_path
    if resolved_dem_path is None:
        chosen_dem_asset = _find_downloaded_dem_asset(assets, dem_asset_id)
        if chosen_dem_asset and chosen_dem_asset.local_path:
            resolved_dem_path = Path(chosen_dem_asset.local_path)

    if resolved_dem_path is not None and resolved_dem_path.exists():
        dem_meta = inspect_raster_metadata(resolved_dem_path)
        dem_aligned = align_raster_band_to_grid(
            resolved_dem_path, band_index=1, grid=grid, resampling=Resampling.bilinear
        )
        valid_dem = (dem_aligned != grid.nodata) & np.isfinite(dem_aligned)
        if np.any(valid_dem) and grid.height >= 3 and grid.width >= 3:
            terrain = compute_terrain_derivatives(
                dem_aligned,
                pixel_size_m=grid.resolution_m,
                is_projected_metric=True,
                nodata=grid.nodata,
            )
            terrain_layers = {
                "elevation_m": terrain.elevation_m,
                "slope_deg": terrain.slope_deg,
                "aspect_deg": terrain.aspect_deg,
                "hillshade": terrain.hillshade,
                "tri": terrain.tri,
                "tpi": terrain.tpi,
                "curvature": terrain.curvature,
                "drainage_proxy": terrain.drainage_proxy,
            }
            native_dem_res = (
                chosen_dem_asset.resolution_m
                if chosen_dem_asset and chosen_dem_asset.resolution_m
                else 30.0
            )
            for fname, farr in terrain_layers.items():
                features[fname] = farr
                feature_docs.append(
                    {
                        "name": fname,
                        "category": "terrain",
                        "native_resolution_m": native_dem_res,
                        "target_resolution_m": grid.resolution_m,
                        "source_crs_epsg": dem_meta.get("crs_epsg"),
                        "reprojected_to_epsg": grid.crs_epsg,
                    }
                )
            input_datasets.append(
                {
                    "type": "dem",
                    "asset_id": chosen_dem_asset.id if chosen_dem_asset else None,
                    "path": str(resolved_dem_path),
                    "source_epsg": dem_meta.get("crs_epsg"),
                    "native_resolution_m": native_dem_res,
                }
            )
            if chosen_dem_asset:
                input_scene_ids.append(chosen_dem_asset.stac_item_id)
                observed_origins.add(chosen_dem_asset.data_origin)
            if abs(float(native_dem_res) - float(grid.resolution_m)) > 1e-3:
                warnings.append(
                    f"DEM native resolution (~{native_dem_res}m) resampled via bilinear to target grid {grid.resolution_m}m."
                )
        else:
            warnings.append(
                "DEM file contained no valid pixels in AOI or grid smaller than 3x3; terrain derivatives skipped."
            )
    else:
        warnings.append(
            "No downloaded DEM GeoTIFF available for AOI; terrain derivatives skipped (synthetic terrain not fabricated)."
        )

    # 2. Optional Sentinel-2 Spectral Features
    if sentinel_band_paths:
        norm_paths = _normalize_s2_band_map(sentinel_band_paths)
        aligned_s2: dict[str, np.ndarray] = {}
        missing_paths: list[str] = []
        for bname, bpath in norm_paths.items():
            if not bpath.exists():
                missing_paths.append(f"{bname}:{bpath}")
                continue
            resamp = Resampling.nearest if bname == "SCL" else Resampling.bilinear
            aligned_s2[bname] = align_raster_band_to_grid(bpath, band_index=1, grid=grid, resampling=resamp)
        if missing_paths:
            warnings.append(f"Skipped missing Sentinel-2 band path(s): {', '.join(missing_paths)}")
        if aligned_s2:
            s2_feats, s2_docs = compute_sentinel2_features(
                aligned_s2, scl=aligned_s2.get("SCL"), nodata=grid.nodata
            )
            features.update(s2_feats)
            feature_docs.extend(s2_docs)
            input_datasets.append(
                {
                    "type": "sentinel2_l2a",
                    "bands_loaded": sorted(aligned_s2.keys()),
                    "cloud_masked": "SCL" in aligned_s2,
                }
            )
            warnings.append(
                f"Sentinel-2 bands (10m/20m native) harmonized onto {grid.resolution_m}m grid; spectral ratios reflect surface alteration proxies, not subsurface ore."
            )

    # 3. Optional ASTER Spectral Features
    if aster_band_paths:
        aligned_aster: dict[str, np.ndarray] = {}
        for bname, bpath in aster_band_paths.items():
            if bpath.exists():
                aligned_aster[bname.strip().upper()] = align_raster_band_to_grid(
                    bpath, band_index=1, grid=grid, resampling=Resampling.bilinear
                )
        if aligned_aster:
            a_feats, a_docs, a_warns = compute_aster_features(aligned_aster, nodata=grid.nodata)
            features.update(a_feats)
            feature_docs.extend(a_docs)
            warnings.extend(a_warns)
            input_datasets.append({"type": "aster", "bands_loaded": sorted(aligned_aster.keys())})

    # 4. Geological Proximity & Lithology (ML-eligible sources only; strict non-fabrication)
    if include_geology:
        occs_trainable = MineralOccurrenceRepository(db).find_in_aoi(
            aoi, ml_trainable_only=True
        )
        occs_all = MineralOccurrenceRepository(db).find_in_aoi(aoi, ml_trainable_only=False)
        excluded_count = len(occs_all) - len(occs_trainable)
        if excluded_count > 0:
            warnings.append(
                f"Excluded {excluded_count} occurrence(s) from non-ML-trainable sources (e.g. reference-only catalogs) during feature engineering."
            )

        units = GeologicalUnitRepository(db).find_in_aoi(aoi)
        for occ in occs_trainable:
            observed_origins.add(occ.data_origin)
        for unit in units:
            observed_origins.add(unit.data_origin)

        geo_feats, geo_docs, geo_warns = compute_geological_features(
            grid=grid,
            occurrences=occs_trainable,
            geological_units=units,
        )
        if "dist_to_occurrence_m" in geo_feats:
            warnings.append(
                "Target-leakage caution: dist_to_occurrence_m uses known deposit coordinates and must be excluded when training occurrence-prediction models."
            )
        features.update(geo_feats)
        feature_docs.extend(geo_docs)
        warnings.extend(geo_warns)
        input_datasets.append(
            {
                "type": "geological_vectors",
                "ml_trainable_occurrences": len(occs_trainable),
                "geological_units": len(units),
            }
        )

    if not features:
        raise ValueError(
            "No valid features could be produced for this AOI. Download a DEM or ingest geological occurrences/units first."
        )

    # Resolve manifest data_origin conservatively (never label mixed/synthetic as pure real)
    if "synthetic" in observed_origins:
        manifest_origin = "synthetic"
        warnings.append("Manifest contains synthetic-origin inputs and must NOT be treated as pure empirical data.")
    elif "demonstration" in observed_origins:
        manifest_origin = "demonstration"
    else:
        manifest_origin = "real"

    manifest_id = str(uuid.uuid4())
    safe_aoi = sanitize_filename(aoi.id, fallback="aoi")
    stack_path = resolve_safe_path(settings.features_dir, safe_aoi, manifest_id, "feature_stack.tif")
    manifest_json_path = resolve_safe_path(
        settings.features_dir, safe_aoi, manifest_id, "manifest.json"
    )

    feature_names = _write_feature_stack(stack_path=stack_path, grid=grid, features=features)
    feature_stats = {
        name: _summarize_feature_array(features[name], nodata=grid.nodata)
        for name in feature_names
    }

    manifest_payload = {
        "manifest_id": manifest_id,
        "aoi_id": aoi.id,
        "aoi_name": aoi.name,
        "target_crs_epsg": grid.crs_epsg,
        "resolution_m": grid.resolution_m,
        "grid_rows": grid.height,
        "grid_cols": grid.width,
        "transform": list(grid.transform)[:6],
        "bounds_metric": list(grid.bounds_metric),
        "bbox_wgs84": [
            aoi.bbox_min_lon,
            aoi.bbox_min_lat,
            aoi.bbox_max_lon,
            aoi.bbox_max_lat,
        ],
        "nodata_value": grid.nodata,
        "feature_names": feature_names,
        "feature_stats": feature_stats,
        "feature_docs": feature_docs,
        "input_datasets": input_datasets,
        "input_scene_ids": input_scene_ids,
        "warnings": warnings,
        "data_origin": manifest_origin,
        "created_at": datetime.now(UTC).isoformat(),
    }
    manifest_json_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")

    manifest_row = FeatureManifest(
        id=manifest_id,
        aoi_id=aoi.id,
        target_crs_epsg=grid.crs_epsg,
        resolution_m=grid.resolution_m,
        grid_rows=grid.height,
        grid_cols=grid.width,
        nodata_value=grid.nodata,
        status="completed",
        input_datasets_json=input_datasets,
        input_scene_ids=input_scene_ids,
        feature_names=feature_names,
        output_files_json={
            "feature_stack_tif": str(stack_path),
            "manifest_json": str(manifest_json_path),
        },
        warnings_json=warnings,
        manifest_json=manifest_payload,
        data_origin=manifest_origin,
    )
    persisted = FeatureManifestRepository(db).create(manifest_row)
    return FeatureExtractionOutcome(
        manifest=persisted,
        stack_path=stack_path,
        manifest_json_path=manifest_json_path,
        feature_stats=feature_stats,
    )
