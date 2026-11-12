"""Scientifically grounded Sentinel-2 and ASTER spectral feature calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.geospatial.raster_ops import DEFAULT_NODATA

# Sentinel-2 SCL classes considered obscured/invalid for surface mineral proxies:
# 0=NoData, 1=Saturated/Defective, 3=Cloud Shadows, 8=Cloud Medium Prob,
# 9=Cloud High Prob, 10=Thin Cirrus, 11=Snow/Ice
SENTINEL2_MASKED_SCL_CLASSES = (0, 1, 3, 8, 9, 10, 11)


@dataclass(frozen=True)
class SpectralFeatureMetadata:
    name: str
    category: str
    formula: str
    native_resolution_m: float
    interpretation: str
    is_direct_mineral_proof: bool = False


SENTINEL2_FEATURE_REGISTRY: dict[str, SpectralFeatureMetadata] = {
    "ndvi": SpectralFeatureMetadata(
        name="ndvi",
        category="landcover_mask",
        formula="(B08 - B04) / (B08 + B04)",
        native_resolution_m=10.0,
        interpretation="Vegetation vigor index used ONLY to mask vegetation interference; NOT a mineral detector.",
    ),
    "ndwi": SpectralFeatureMetadata(
        name="ndwi",
        category="landcover_mask",
        formula="(B03 - B08) / (B03 + B08)",
        native_resolution_m=10.0,
        interpretation="Open-water index (McFeeters) used for surface water masking; NOT a mineral detector.",
    ),
    "ndbi": SpectralFeatureMetadata(
        name="ndbi",
        category="landcover_mask",
        formula="(B11 - B08) / (B11 + B08)",
        native_resolution_m=20.0,
        interpretation="Built-up / bare surface contrast proxy (SWIR1 vs NIR); NOT specific to ore mineralization.",
    ),
    "s2_iron_oxide_ratio": SpectralFeatureMetadata(
        name="s2_iron_oxide_ratio",
        category="alteration_proxy",
        formula="B04 / B02",
        native_resolution_m=10.0,
        interpretation="Visible ferric iron (Fe3+) absorption proxy (hematite/goethite/gossan staining indicator).",
    ),
    "s2_ferrous_iron_ratio": SpectralFeatureMetadata(
        name="s2_ferrous_iron_ratio",
        category="alteration_proxy",
        formula="B12 / B8A",
        native_resolution_m=20.0,
        interpretation="Ferrous iron / Fe-bearing silicate alteration proxy (SWIR2/RedEdge-NIR).",
    ),
    "s2_clay_hydroxyl_ratio": SpectralFeatureMetadata(
        name="s2_clay_hydroxyl_ratio",
        category="alteration_proxy",
        formula="B11 / B12",
        native_resolution_m=20.0,
        interpretation="Hydroxyl/clay alteration proxy (Al-OH absorption near B12 ~2200nm relative to B11 ~1610nm).",
    ),
    "s2_bare_earth_mask": SpectralFeatureMetadata(
        name="s2_bare_earth_mask",
        category="quality_mask",
        formula="(cloud_free) & (ndvi < 0.25) & (ndwi < 0.10)",
        native_resolution_m=20.0,
        interpretation="1.0 where bedrock/soil exposure is weakly vegetated and cloud-free, else 0.0.",
    ),
}


def safe_normalized_difference(
    b1: np.ndarray,
    b2: np.ndarray,
    *,
    valid_mask: np.ndarray,
    nodata: float = DEFAULT_NODATA,
    eps: float = 1e-6,
) -> np.ndarray:
    """Compute (b1 - b2) / (b1 + b2) safely, guarding near-zero denominators and nodata."""
    out = np.full(b1.shape, nodata, dtype=np.float32)
    f1 = b1.astype(np.float64)
    f2 = b2.astype(np.float64)
    denom = f1 + f2
    ok = valid_mask & np.isfinite(f1) & np.isfinite(f2) & (np.abs(denom) > eps)
    out[ok] = ((f1[ok] - f2[ok]) / denom[ok]).astype(np.float32)
    return out


def safe_band_ratio(
    numerator: np.ndarray,
    denominator: np.ndarray,
    *,
    valid_mask: np.ndarray,
    nodata: float = DEFAULT_NODATA,
    eps: float = 1e-6,
) -> np.ndarray:
    """Compute numerator / denominator safely, avoiding zero or near-zero division."""
    out = np.full(numerator.shape, nodata, dtype=np.float32)
    num = numerator.astype(np.float64)
    den = denominator.astype(np.float64)
    ok = valid_mask & np.isfinite(num) & np.isfinite(den) & (np.abs(den) > eps) & (num >= 0.0) & (den > 0.0)
    out[ok] = (num[ok] / den[ok]).astype(np.float32)
    return out


def build_sentinel2_valid_mask(
    bands: dict[str, np.ndarray],
    *,
    scl: np.ndarray | None = None,
    nodata: float = DEFAULT_NODATA,
) -> np.ndarray:
    """Construct boolean pixel validity mask combining finite/non-nodata checks and SCL clouds."""
    first = next(iter(bands.values()))
    mask = np.ones(first.shape, dtype=bool)
    for arr in bands.values():
        mask &= np.isfinite(arr) & (arr != nodata) & (arr >= 0.0)
    if scl is not None:
        scl_int = scl.astype(np.int32)
        for bad_cls in SENTINEL2_MASKED_SCL_CLASSES:
            mask &= scl_int != bad_cls
    return mask


def compute_sentinel2_features(
    bands: dict[str, np.ndarray],
    *,
    scl: np.ndarray | None = None,
    nodata: float = DEFAULT_NODATA,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    """Compute supported Sentinel-2 indices & alteration proxies from aligned band arrays.

    Expected canonical keys where available: B02 (blue), B03 (green), B04 (red), B08 (nir),
    B8A (nir08), B11 (swir16), B12 (swir22). Features are computed strictly for available bands.
    """
    if not bands:
        return {}, []

    valid = build_sentinel2_valid_mask(bands, scl=scl, nodata=nodata)
    features: dict[str, np.ndarray] = {}
    docs: list[dict[str, Any]] = []

    if "B08" in bands and "B04" in bands:
        features["ndvi"] = safe_normalized_difference(bands["B08"], bands["B04"], valid_mask=valid, nodata=nodata)
        docs.append(SENTINEL2_FEATURE_REGISTRY["ndvi"].__dict__)

    if "B03" in bands and "B08" in bands:
        features["ndwi"] = safe_normalized_difference(bands["B03"], bands["B08"], valid_mask=valid, nodata=nodata)
        docs.append(SENTINEL2_FEATURE_REGISTRY["ndwi"].__dict__)

    if "B11" in bands and "B08" in bands:
        features["ndbi"] = safe_normalized_difference(bands["B11"], bands["B08"], valid_mask=valid, nodata=nodata)
        docs.append(SENTINEL2_FEATURE_REGISTRY["ndbi"].__dict__)

    if "B04" in bands and "B02" in bands:
        features["s2_iron_oxide_ratio"] = safe_band_ratio(
            bands["B04"], bands["B02"], valid_mask=valid, nodata=nodata
        )
        docs.append(SENTINEL2_FEATURE_REGISTRY["s2_iron_oxide_ratio"].__dict__)

    nir_band = bands.get("B8A") if "B8A" in bands else bands.get("B08")
    if "B12" in bands and nir_band is not None:
        features["s2_ferrous_iron_ratio"] = safe_band_ratio(
            bands["B12"], nir_band, valid_mask=valid, nodata=nodata
        )
        docs.append(SENTINEL2_FEATURE_REGISTRY["s2_ferrous_iron_ratio"].__dict__)

    if "B11" in bands and "B12" in bands:
        features["s2_clay_hydroxyl_ratio"] = safe_band_ratio(
            bands["B11"], bands["B12"], valid_mask=valid, nodata=nodata
        )
        docs.append(SENTINEL2_FEATURE_REGISTRY["s2_clay_hydroxyl_ratio"].__dict__)

    if "ndvi" in features and "ndwi" in features:
        bare = np.full(valid.shape, nodata, dtype=np.float32)
        ndvi_arr = features["ndvi"]
        ndwi_arr = features["ndwi"]
        known = valid & (ndvi_arr != nodata) & (ndwi_arr != nodata)
        bare_ok = known & (ndvi_arr < 0.25) & (ndwi_arr < 0.10)
        bare[known] = 0.0
        bare[bare_ok] = 1.0
        features["s2_bare_earth_mask"] = bare
        docs.append(SENTINEL2_FEATURE_REGISTRY["s2_bare_earth_mask"].__dict__)

    return features, docs


def compute_aster_features(
    aster_bands: dict[str, np.ndarray],
    *,
    nodata: float = DEFAULT_NODATA,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]], list[str]]:
    """Compute band-gated ASTER mineral alteration proxies.

    Because post-2008 ASTER scenes lack SWIR and nighttime scenes contain only TIR,
    indices are computed strictly when their required ASTER bands are provided.
    """
    features: dict[str, np.ndarray] = {}
    docs: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not aster_bands:
        return features, docs, ["No ASTER band arrays supplied."]

    first = next(iter(aster_bands.values()))
    valid = np.ones(first.shape, dtype=bool)
    for arr in aster_bands.values():
        valid &= np.isfinite(arr) & (arr != nodata)

    # Ferric iron (VNIR 15m): Band 2 (Red) / Band 1 (Green)
    if "B02" in aster_bands and "B01" in aster_bands:
        features["aster_ferric_iron"] = safe_band_ratio(
            aster_bands["B02"], aster_bands["B01"], valid_mask=valid, nodata=nodata
        )
        docs.append(
            {
                "name": "aster_ferric_iron",
                "formula": "ASTER B02 / B01",
                "native_resolution_m": 15.0,
                "interpretation": "Surface ferric iron proxy (VNIR only); requires bare rock.",
            }
        )
    else:
        warnings.append("ASTER VNIR B01/B02 missing; skipped aster_ferric_iron.")

    # OH/Al-OH Clay (SWIR 30m — pre-April 2008 only): (B05 + B07) / B06
    if {"B05", "B06", "B07"}.issubset(aster_bands.keys()):
        num = aster_bands["B05"].astype(np.float64) + aster_bands["B07"].astype(np.float64)
        features["aster_aloh_clay"] = safe_band_ratio(
            num, aster_bands["B06"], valid_mask=valid, nodata=nodata
        )
        docs.append(
            {
                "name": "aster_aloh_clay",
                "formula": "(ASTER B05 + B07) / B06",
                "native_resolution_m": 30.0,
                "interpretation": "Al-OH phyllosilicate/kaolinite-sericite proxy (pre-2008 SWIR scenes only).",
            }
        )
    else:
        warnings.append("ASTER SWIR bands B05-B07 unavailable (expected for post-2008/TIR-only scenes).")

    # Quartz / Silica richness proxy (TIR 90m): B13 / B10
    if "B13" in aster_bands and "B10" in aster_bands:
        features["aster_silica_tir_proxy"] = safe_band_ratio(
            aster_bands["B13"], aster_bands["B10"], valid_mask=valid, nodata=nodata
        )
        docs.append(
            {
                "name": "aster_silica_tir_proxy",
                "formula": "ASTER B13 / B10",
                "native_resolution_m": 90.0,
                "interpretation": "Qualitative TIR silicate emissivity proxy (90m; atmospheric/temperature sensitive).",
            }
        )

    return features, docs, warnings

