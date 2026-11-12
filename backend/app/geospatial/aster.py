"""Verified band resolver and grid loader for grouped ASTER L1T COG files (VNIR, SWIR, TIR)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import Resampling

from app.geospatial.raster_ops import TargetGridSpec, align_raster_band_to_grid

ASTER_BAND_SPECS: dict[int, dict[str, Any]] = {
    1: {"scientific_band": "B01", "group": "VNIR", "native_resolution_m": 15.0, "center_wavelength_um": 0.56},
    2: {"scientific_band": "B02", "group": "VNIR", "native_resolution_m": 15.0, "center_wavelength_um": 0.66},
    3: {"scientific_band": "B03N", "group": "VNIR", "native_resolution_m": 15.0, "center_wavelength_um": 0.82},
    4: {"scientific_band": "B04", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 1.65},
    5: {"scientific_band": "B05", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 2.165},
    6: {"scientific_band": "B06", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 2.205},
    7: {"scientific_band": "B07", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 2.26},
    8: {"scientific_band": "B08", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 2.339},
    9: {"scientific_band": "B09", "group": "SWIR", "native_resolution_m": 30.0, "center_wavelength_um": 2.395},
    10: {"scientific_band": "B10", "group": "TIR", "native_resolution_m": 90.0, "center_wavelength_um": 8.30},
    11: {"scientific_band": "B11", "group": "TIR", "native_resolution_m": 90.0, "center_wavelength_um": 8.65},
    12: {"scientific_band": "B12", "group": "TIR", "native_resolution_m": 90.0, "center_wavelength_um": 9.11},
    13: {"scientific_band": "B13", "group": "TIR", "native_resolution_m": 90.0, "center_wavelength_um": 10.60},
    14: {"scientific_band": "B14", "group": "TIR", "native_resolution_m": 90.0, "center_wavelength_um": 11.30},
}

_GROUP_ALLOWED_NUMS: dict[str, set[int]] = {
    "VNIR": {1, 2, 3},
    "SWIR": {4, 5, 6, 7, 8, 9},
    "TIR": {10, 11, 12, 13, 14},
}

_BAND_DESC_PATTERNS = (
    re.compile(r"ImageData(\d+)[NB]?\b", re.IGNORECASE),
    re.compile(r"(?:VNIR|SWIR|TIR)_Band(\d+)", re.IGNORECASE),
    re.compile(r"\bB(0?[1-9]|1[0-4])[NB]?\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ResolvedASTERBand:
    """Verified mapping from a grouped ASTER GeoTIFF band index to a canonical scientific band."""

    scientific_band: str
    group: str
    band_index: int
    source_path: str
    description: str
    native_resolution_m: float
    center_wavelength_um: float
    nodata: float | None

    def to_manifest_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_band_number(text: str | None) -> int | None:
    if not text:
        return None
    for pattern in _BAND_DESC_PATTERNS:
        m = pattern.search(text.strip())
        if m:
            num = int(m.group(1))
            if num in ASTER_BAND_SPECS:
                return num
    return None


def resolve_aster_grouped_bands(
    grouped_paths: dict[str, Path],
    *,
    stac_asset_info: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[ResolvedASTERBand], list[str]]:
    """Inspect grouped VNIR/SWIR/TIR ASTER GeoTIFFs and verify every band index without guessing.

    Raises ValueError if a grouped file lacks verifiable band descriptions/metadata, contains
    contradictory STAC vs raster metadata, or maps a band outside its swath group.
    """
    resolved: list[ResolvedASTERBand] = []
    warnings: list[str] = []
    seen_scientific_bands: set[str] = set()

    for raw_group, path in grouped_paths.items():
        group = raw_group.strip().upper()
        if group not in _GROUP_ALLOWED_NUMS:
            raise ValueError(
                f"Unsupported ASTER asset group '{raw_group}'; expected one of VNIR, SWIR, TIR."
            )
        if not path.exists():
            warnings.append(f"ASTER {group} file missing on disk: {path}")
            continue

        group_info = (stac_asset_info or {}).get(group, {})
        eo_bands = group_info.get("eo_bands") if isinstance(group_info.get("eo_bands"), list) else []
        raster_bands = (
            group_info.get("raster_bands")
            if isinstance(group_info.get("raster_bands"), list)
            else []
        )

        with rasterio.open(path) as src:
            if src.crs is None:
                raise ValueError(f"ASTER {group} file '{path.name}' lacks CRS metadata.")
            if src.count <= 0:
                raise ValueError(f"ASTER {group} file '{path.name}' has 0 raster bands.")

            descriptions = list(src.descriptions or [])
            native_res = float(abs(src.res[0]))

            for band_idx in range(1, src.count + 1):
                desc = (
                    descriptions[band_idx - 1]
                    if band_idx - 1 < len(descriptions) and descriptions[band_idx - 1]
                    else None
                )
                desc_num = _extract_band_number(desc)

                stac_band = eo_bands[band_idx - 1] if band_idx - 1 < len(eo_bands) else {}
                stac_name = stac_band.get("name") if isinstance(stac_band, dict) else None
                stac_num = _extract_band_number(stac_name)

                if desc_num is not None and stac_num is not None and desc_num != stac_num:
                    raise ValueError(
                        f"ASTER {group} band {band_idx} description '{desc}' contradicts "
                        f"STAC eo:bands '{stac_name}'."
                    )

                verified_num = desc_num if desc_num is not None else stac_num
                if verified_num is None:
                    raise ValueError(
                        f"Cannot verify ASTER {group} band {band_idx} in '{path.name}': "
                        f"missing band description ({desc!r}) and STAC eo:bands metadata."
                    )

                if verified_num not in _GROUP_ALLOWED_NUMS[group]:
                    raise ValueError(
                        f"ASTER band number {verified_num} does not belong to {group} swath "
                        f"(allowed: {sorted(_GROUP_ALLOWED_NUMS[group])})."
                    )

                spec = ASTER_BAND_SPECS[verified_num]
                sci_band = str(spec["scientific_band"])
                if sci_band in seen_scientific_bands:
                    raise ValueError(
                        f"Duplicate mapping for scientific ASTER band '{sci_band}' in '{path.name}'."
                    )
                seen_scientific_bands.add(sci_band)

                rb = raster_bands[band_idx - 1] if band_idx - 1 < len(raster_bands) else {}
                stac_nodata = rb.get("nodata") if isinstance(rb, dict) else None
                effective_nodata = src.nodata if src.nodata is not None else stac_nodata
                wavelength = (
                    float(stac_band["center_wavelength"])
                    if isinstance(stac_band, dict) and stac_band.get("center_wavelength") is not None
                    else float(spec["center_wavelength_um"])
                )
                resolved.append(
                    ResolvedASTERBand(
                        scientific_band=sci_band,
                        group=group,
                        band_index=band_idx,
                        source_path=str(path),
                        description=desc or stac_name or sci_band,
                        native_resolution_m=round(native_res, 3),
                        center_wavelength_um=round(wavelength, 4),
                        nodata=float(effective_nodata) if effective_nodata is not None else None,
                    )
                )

    if resolved:
        groups_present = {r.group for r in resolved}
        if "SWIR" not in groups_present:
            warnings.append(
                "ASTER SWIR group absent (expected for post-April 2008 or TIR-only acquisitions); SWIR clay ratios skipped."
            )
        if "VNIR" not in groups_present:
            warnings.append(
                "ASTER VNIR group absent (expected for nighttime TIR-only acquisitions); VNIR ferric ratio skipped."
            )
    return resolved, warnings


def load_aster_bands_to_grid(
    *,
    grouped_paths: dict[str, Path] | None = None,
    single_band_paths: dict[str, Path] | None = None,
    grid: TargetGridSpec,
    stac_asset_info: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]], list[str]]:
    """Load verified ASTER bands from grouped VNIR/SWIR/TIR COGs or single-band paths."""
    aligned: dict[str, np.ndarray] = {}
    band_mappings: list[dict[str, Any]] = []
    warnings: list[str] = []

    if grouped_paths:
        resolved, grp_warnings = resolve_aster_grouped_bands(
            grouped_paths, stac_asset_info=stac_asset_info
        )
        warnings.extend(grp_warnings)
        for item in resolved:
            aligned[item.scientific_band] = align_raster_band_to_grid(
                Path(item.source_path),
                band_index=item.band_index,
                grid=grid,
                resampling=Resampling.bilinear,
                nodata_override=item.nodata,
            )
            band_mappings.append(item.to_manifest_dict())

    if single_band_paths:
        for bname, bpath in single_band_paths.items():
            key = bname.strip().upper()
            if key in {"VNIR", "SWIR", "TIR"}:
                continue
            if not bpath.exists():
                warnings.append(f"ASTER single-band file missing on disk: {bname}:{bpath}")
                continue
            aligned[key] = align_raster_band_to_grid(
                bpath,
                band_index=1,
                grid=grid,
                resampling=Resampling.bilinear,
            )
            band_mappings.append(
                {
                    "scientific_band": key,
                    "group": "SINGLE_BAND",
                    "band_index": 1,
                    "source_path": str(bpath),
                    "description": key,
                    "native_resolution_m": None,
                    "center_wavelength_um": None,
                    "nodata": None,
                }
            )

    return aligned, band_mappings, warnings

