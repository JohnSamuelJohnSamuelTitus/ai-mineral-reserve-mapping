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
from app.geospatial.aster import load_aster_bands_to_grid
from app.geospatial.proximity import compute_geological_features
from app.geospatial.raster_ops import (
    TargetGridSpec,
    align_raster_band_to_grid,
    build_aoi_target_grid,
    inspect_raster_metadata,
    mosaic_compatible_dem_tiles,
)
from app.geospatial.spectral import compute_aster_features, compute_sentinel2_features
from app.geospatial.terrain import compute_terrain_derivatives
from app.storage.manager import (
    check_free_disk_space,
    managed_temp_dir,
    resolve_safe_path,
    sanitize_filename,
)

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


def _is_dem_asset(asset: RasterAsset) -> bool:
    col = (asset.stac_collection or "").lower()
    atype = (asset.asset_type or "").lower()
    ptype = (asset.product_type or "").lower()
    return "dem" in col or "dem" in atype or "dem" in ptype or atype in {"data", "elevation"}


def _is_sentinel2_asset(asset: RasterAsset) -> bool:
    col = (asset.stac_collection or "").lower()
    atype = (asset.asset_type or "").lower()
    ptype = (asset.product_type or "").lower()
    return "sentinel-2" in col or "sentinel2" in atype or "multispectral_l2a" in ptype


def _is_aster_asset(asset: RasterAsset) -> bool:
    col = (asset.stac_collection or "").lower()
    atype = (asset.asset_type or "").lower()
    ptype = (asset.product_type or "").lower()
    return "aster" in col or "ast_" in col or "aster" in atype or "aster" in ptype


def _extract_downloaded_band_map(asset: RasterAsset) -> dict[str, dict[str, Any]]:
    meta = asset.band_metadata or {}
    downloaded = meta.get("downloaded_bands")
    if isinstance(downloaded, dict) and downloaded:
        valid: dict[str, dict[str, Any]] = {}
        for band_key, info in downloaded.items():
            if isinstance(info, dict) and info.get("local_path"):
                p = Path(str(info["local_path"]))
                if p.exists():
                    valid[str(band_key)] = info
        if valid:
            return valid
    return {}


def _find_downloaded_dem_assets(
    assets: list[RasterAsset],
    preferred_id: str | None = None,
    preferred_ids: list[str] | None = None,
) -> tuple[list[RasterAsset], list[RasterAsset]]:
    """Return `(downloaded_dem_assets, missing_discovered_dem_assets)` deduplicated by tile ID."""
    if preferred_ids:
        id_set = set(preferred_ids)
        chosen = [a for a in assets if a.id in id_set and a.local_path and Path(a.local_path).exists()]
        return chosen, []
    if preferred_id is not None:
        chosen = [a for a in assets if a.id == preferred_id]
        return chosen, []

    downloaded_by_item: dict[str, RasterAsset] = {}
    undownloaded_by_item: dict[str, RasterAsset] = {}
    for asset in assets:
        if not _is_dem_asset(asset):
            continue
        band_map = _extract_downloaded_band_map(asset)
        primary_path = (
            Path(str(band_map["DEM"]["local_path"]))
            if "DEM" in band_map
            else (Path(asset.local_path) if asset.local_path else None)
        )
        if asset.download_status == "downloaded" and primary_path and primary_path.exists():
            downloaded_by_item.setdefault(asset.stac_item_id, asset)
        elif asset.stac_item_id not in downloaded_by_item:
            undownloaded_by_item.setdefault(asset.stac_item_id, asset)

    missing = [
        a for item_id, a in undownloaded_by_item.items() if item_id not in downloaded_by_item
    ]
    return list(downloaded_by_item.values()), missing


def _find_downloaded_multispectral_asset(
    assets: list[RasterAsset],
    *,
    predicate: Any,
    preferred_id: str | None,
) -> RasterAsset | None:
    if preferred_id is not None:
        for asset in assets:
            if asset.id == preferred_id:
                return asset
        return None
    # Prefer fully downloaded scenes first, then partial scenes with local bands on disk
    candidates = [a for a in assets if predicate(a) and _extract_downloaded_band_map(a)]
    candidates.sort(
        key=lambda a: (
            1 if a.download_status == "downloaded" else 0,
            len(_extract_downloaded_band_map(a)),
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


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
    dem_asset_ids: list[str] | None = None,
    dem_local_path: Path | None = None,
    dem_local_paths: list[Path] | None = None,
    sentinel_asset_id: str | None = None,
    sentinel_band_paths: dict[str, Path] | None = None,
    aster_asset_id: str | None = None,
    aster_band_paths: dict[str, Path] | None = None,
    include_sentinel2: bool = True,
    include_aster: bool = True,
    include_geology: bool = True,
    max_dimension_px: int = 4096,
) -> FeatureExtractionOutcome:
    """Build an aligned projected GeoTIFF feature stack and reproducible FeatureManifest for an AOI."""
    check_free_disk_space(settings.features_dir, min_free_gb=settings.min_free_disk_gb, required_mb=30.0)

    manifest_id = str(uuid.uuid4())
    safe_aoi = sanitize_filename(aoi.id, fallback="aoi")
    stack_path = resolve_safe_path(settings.features_dir, safe_aoi, manifest_id, "feature_stack.tif")
    manifest_json_path = resolve_safe_path(
        settings.features_dir, safe_aoi, manifest_id, "manifest.json"
    )

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
    dem_tile_ids: list[str] = []
    dem_coverage_pct: float | None = None
    aster_band_mapping: list[dict[str, Any]] = []

    assets = RasterAssetRepository(db).list_for_aoi(aoi.id)
    aoi_bbox = (aoi.bbox_min_lon, aoi.bbox_min_lat, aoi.bbox_max_lon, aoi.bbox_max_lat)

    # 1. DEM Cross-Tile Mosaicking & Terrain Derivatives
    chosen_dem_assets: list[RasterAsset] = []
    resolved_dem_paths: list[Path] = []
    if dem_local_paths:
        resolved_dem_paths = [p for p in dem_local_paths if p.exists()]
    elif dem_local_path is not None:
        if dem_local_path.exists():
            resolved_dem_paths = [dem_local_path]
    else:
        chosen_dem_assets, missing_dem_assets = _find_downloaded_dem_assets(
            assets, preferred_id=dem_asset_id, preferred_ids=dem_asset_ids
        )
        for asset in chosen_dem_assets:
            bmap = _extract_downloaded_band_map(asset)
            p = (
                Path(str(bmap["DEM"]["local_path"]))
                if "DEM" in bmap
                else (Path(asset.local_path) if asset.local_path else None)
            )
            if p and p.exists():
                resolved_dem_paths.append(p)
        if missing_dem_assets:
            missing_ids = [a.stac_item_id for a in missing_dem_assets]
            warnings.append(
                f"Intersecting DEM tile(s) discovered in catalog are not yet downloaded: {', '.join(missing_ids)}."
            )

    if resolved_dem_paths:
        if len(resolved_dem_paths) == 1:
            dem_source_path = resolved_dem_paths[0]
            dem_meta = inspect_raster_metadata(dem_source_path)
            dem_aligned = align_raster_band_to_grid(
                dem_source_path, band_index=1, grid=grid, resampling=Resampling.bilinear
            )
            dem_source_epsg = dem_meta.get("crs_epsg")
            dem_tile_ids = [
                a.stac_item_id for a in chosen_dem_assets
            ] or [dem_source_path.stem]
            native_dem_res = (
                float(chosen_dem_assets[0].resolution_m)
                if chosen_dem_assets and chosen_dem_assets[0].resolution_m
                else float(abs((dem_meta.get("pixel_size") or [30.0])[0]))
            )
        else:
            with managed_temp_dir("aoi_dem_mosaic_") as mosaic_tmp:
                mosaic_out_path = mosaic_tmp / "dem_mosaic.tif"
                mosaic_res = mosaic_compatible_dem_tiles(
                    tile_paths=resolved_dem_paths,
                    output_path=mosaic_out_path,
                    aoi_bbox_wgs84=aoi_bbox,
                    nodata=grid.nodata,
                )
                warnings.extend(mosaic_res.warnings)
                dem_aligned = align_raster_band_to_grid(
                    mosaic_res.mosaic_path,
                    band_index=1,
                    grid=grid,
                    resampling=Resampling.bilinear,
                )
                dem_source_epsg = mosaic_res.source_crs_epsg
                dem_tile_ids = [
                    a.stac_item_id for a in chosen_dem_assets
                ] or [p.stem for p in resolved_dem_paths]
                native_dem_res = (
                    float(chosen_dem_assets[0].resolution_m)
                    if chosen_dem_assets and chosen_dem_assets[0].resolution_m
                    else 30.0
                )

        valid_dem = (dem_aligned != grid.nodata) & np.isfinite(dem_aligned)
        dem_coverage_pct = round(float(np.sum(valid_dem)) / max(int(dem_aligned.size), 1) * 100.0, 2)
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
            for fname, farr in terrain_layers.items():
                features[fname] = farr
                feature_docs.append(
                    {
                        "name": fname,
                        "category": "terrain",
                        "native_resolution_m": native_dem_res,
                        "target_resolution_m": grid.resolution_m,
                        "source_crs_epsg": dem_source_epsg,
                        "reprojected_to_epsg": grid.crs_epsg,
                        "source_tile_ids": dem_tile_ids,
                    }
                )
            input_datasets.append(
                {
                    "type": "dem",
                    "asset_ids": [a.id for a in chosen_dem_assets],
                    "source_tile_ids": dem_tile_ids,
                    "paths": [str(p) for p in resolved_dem_paths],
                    "source_epsg": dem_source_epsg,
                    "native_resolution_m": native_dem_res,
                    "coverage_pct": dem_coverage_pct,
                    "mosaicked": len(resolved_dem_paths) > 1,
                }
            )
            for asset in chosen_dem_assets:
                if asset.stac_item_id not in input_scene_ids:
                    input_scene_ids.append(asset.stac_item_id)
                observed_origins.add(asset.data_origin)
            if abs(float(native_dem_res) - float(grid.resolution_m)) > 1e-3:
                warnings.append(
                    f"DEM native resolution (~{native_dem_res}m) resampled via bilinear to target grid {grid.resolution_m}m."
                )
            if dem_coverage_pct < 99.0:
                warnings.append(
                    f"DEM tiles ({', '.join(dem_tile_ids)}) cover {dem_coverage_pct}% of AOI grid; missing cells preserved as NoData ({grid.nodata}) without fabrication."
                )
        else:
            warnings.append(
                "DEM file(s) contained no valid pixels in AOI or grid smaller than 3x3; terrain derivatives skipped."
            )
    else:
        warnings.append(
            "No downloaded DEM GeoTIFF available for AOI; terrain derivatives skipped (synthetic terrain not fabricated)."
        )

    # 2. Sentinel-2 Multi-Band Spectral Features (explicit path dict OR persisted RasterAsset bands)
    chosen_s2_asset: RasterAsset | None = None
    s2_paths_to_load: dict[str, Path] | None = (
        dict(sentinel_band_paths) if sentinel_band_paths else None
    )
    s2_nodata_map: dict[str, float | None] = {}
    if s2_paths_to_load is None and include_sentinel2:
        chosen_s2_asset = _find_downloaded_multispectral_asset(
            assets, predicate=_is_sentinel2_asset, preferred_id=sentinel_asset_id
        )
        if chosen_s2_asset is not None:
            bmap = _extract_downloaded_band_map(chosen_s2_asset)
            s2_paths_to_load = {k: Path(str(v["local_path"])) for k, v in bmap.items()}
            s2_nodata_map = {
                k: (float(v["nodata"]) if v.get("nodata") is not None else 0.0)
                for k, v in bmap.items()
            }

    if s2_paths_to_load:
        norm_paths = _normalize_s2_band_map(s2_paths_to_load)
        aligned_s2: dict[str, np.ndarray] = {}
        missing_paths: list[str] = []
        for bname, bpath in norm_paths.items():
            if not bpath.exists():
                missing_paths.append(f"{bname}:{bpath}")
                continue
            resamp = Resampling.nearest if bname == "SCL" else Resampling.bilinear
            aligned_s2[bname] = align_raster_band_to_grid(
                bpath,
                band_index=1,
                grid=grid,
                resampling=resamp,
                nodata_override=s2_nodata_map.get(bname),
            )
        if missing_paths:
            warnings.append(f"Skipped missing Sentinel-2 band path(s): {', '.join(missing_paths)}")

        expected_s2 = {"B02", "B03", "B04", "B08", "B8A", "B11", "B12", "SCL"}
        absent_s2 = sorted(expected_s2 - set(aligned_s2.keys()))
        if absent_s2:
            warnings.append(
                f"Sentinel-2 band(s) not downloaded ({', '.join(absent_s2)}); affected indices skipped without substitution."
            )

        if aligned_s2:
            s2_feats, s2_docs = compute_sentinel2_features(
                aligned_s2, scl=aligned_s2.get("SCL"), nodata=grid.nodata
            )
            features.update(s2_feats)
            feature_docs.extend(s2_docs)
            if chosen_s2_asset is not None:
                if chosen_s2_asset.stac_item_id not in input_scene_ids:
                    input_scene_ids.append(chosen_s2_asset.stac_item_id)
                observed_origins.add(chosen_s2_asset.data_origin)
            input_datasets.append(
                {
                    "type": "sentinel2_l2a",
                    "asset_id": chosen_s2_asset.id if chosen_s2_asset else None,
                    "scene_id": chosen_s2_asset.stac_item_id if chosen_s2_asset else None,
                    "product_type": chosen_s2_asset.product_type if chosen_s2_asset else None,
                    "acquired_at": (
                        chosen_s2_asset.acquired_at.isoformat()
                        if chosen_s2_asset and chosen_s2_asset.acquired_at
                        else None
                    ),
                    "bands_loaded": sorted(aligned_s2.keys()),
                    "missing_bands": absent_s2,
                    "cloud_masked": "SCL" in aligned_s2,
                }
            )
            warnings.append(
                f"Sentinel-2 bands (10m/20m native; SCL nearest-neighbor, reflectance bilinear) harmonized onto {grid.resolution_m}m grid; spectral ratios reflect surface alteration proxies, not subsurface ore."
            )

    # 3. ASTER Grouped COG / Single-Band Spectral Features
    chosen_aster_asset: RasterAsset | None = None
    aster_paths_to_load: dict[str, Path] | None = (
        dict(aster_band_paths) if aster_band_paths else None
    )
    aster_stac_info: dict[str, dict[str, Any]] | None = None
    if aster_paths_to_load is None and include_aster:
        chosen_aster_asset = _find_downloaded_multispectral_asset(
            assets, predicate=_is_aster_asset, preferred_id=aster_asset_id
        )
        if chosen_aster_asset is not None:
            bmap = _extract_downloaded_band_map(chosen_aster_asset)
            aster_paths_to_load = {k: Path(str(v["local_path"])) for k, v in bmap.items()}
            raw_info = (chosen_aster_asset.band_metadata or {}).get("asset_info")
            if isinstance(raw_info, dict):
                aster_stac_info = raw_info

    if aster_paths_to_load:
        grouped_paths = {
            k.strip().upper(): v
            for k, v in aster_paths_to_load.items()
            if k.strip().upper() in {"VNIR", "SWIR", "TIR"}
        }
        single_paths = {
            k.strip().upper(): v
            for k, v in aster_paths_to_load.items()
            if k.strip().upper() not in {"VNIR", "SWIR", "TIR"}
        }
        aligned_aster, aster_band_mapping, load_warns = load_aster_bands_to_grid(
            grouped_paths=grouped_paths or None,
            single_band_paths=single_paths or None,
            grid=grid,
            stac_asset_info=aster_stac_info,
        )
        warnings.extend(load_warns)
        if aligned_aster:
            a_feats, a_docs, a_warns = compute_aster_features(aligned_aster, nodata=grid.nodata)
            features.update(a_feats)
            feature_docs.extend(a_docs)
            warnings.extend(a_warns)
            if chosen_aster_asset is not None:
                if chosen_aster_asset.stac_item_id not in input_scene_ids:
                    input_scene_ids.append(chosen_aster_asset.stac_item_id)
                observed_origins.add(chosen_aster_asset.data_origin)
            input_datasets.append(
                {
                    "type": "aster",
                    "asset_id": chosen_aster_asset.id if chosen_aster_asset else None,
                    "scene_id": chosen_aster_asset.stac_item_id if chosen_aster_asset else None,
                    "bands_loaded": sorted(aligned_aster.keys()),
                    "band_mapping": aster_band_mapping,
                }
            )

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
            "No valid features could be produced for this AOI. Download a DEM, Sentinel-2/ASTER scene, or ingest geological occurrences/units first."
        )

    # Resolve manifest data_origin conservatively (never label mixed/synthetic as pure real)
    if "synthetic" in observed_origins:
        manifest_origin = "synthetic"
        warnings.append("Manifest contains synthetic-origin inputs and must NOT be treated as pure empirical data.")
    elif "demonstration" in observed_origins:
        manifest_origin = "demonstration"
    else:
        manifest_origin = "real"

    feature_names = _write_feature_stack(stack_path=stack_path, grid=grid, features=features)
    feature_stats = {
        name: _summarize_feature_array(features[name], nodata=grid.nodata)
        for name in feature_names
    }

    manifest_payload: dict[str, Any] = {
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
        "dem_source_tile_ids": dem_tile_ids,
        "dem_coverage_pct": dem_coverage_pct,
        "aster_band_mapping": aster_band_mapping,
        "processing_parameters": {
            "resolution_m": grid.resolution_m,
            "target_crs_epsg": grid.crs_epsg,
            "nodata_value": grid.nodata,
            "continuous_resampling": "bilinear",
            "categorical_resampling": "nearest",
            "include_sentinel2": include_sentinel2,
            "include_aster": include_aster,
            "include_geology": include_geology,
        },
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
