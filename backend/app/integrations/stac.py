"""STAC adapters for Microsoft Planetary Computer, Element 84 Earth Search, and NASA CMR."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.core.logging import get_logger
from app.integrations.base import BaseProviderAdapter, ProviderError, ProviderResponseError
from app.storage.manager import sanitize_url_for_storage

logger = get_logger(__name__)

# Normalized band mapping across MPC, Earth Search, Landsat, ASTER, and DEM collections
BAND_ALIASES: dict[str, list[str]] = {
    "blue": ["B02", "blue"],
    "green": ["B03", "green"],
    "red": ["B04", "red"],
    "nir": ["B08", "B8A", "nir", "nir08"],
    "swir1": ["B11", "swir16"],
    "swir2": ["B12", "swir22"],
    "scl": ["SCL", "scl"],
    "qa_pixel": ["qa_pixel"],
    "dem": ["data", "dem"],
    "aster_vnir": ["VNIR"],
    "aster_swir": ["SWIR"],
    "aster_tir": ["TIR"],
    "thermal": ["lwir11", "TIR"],
}

SENTINEL2_CANONICAL_BAND_ASSETS: dict[str, tuple[str, ...]] = {
    "B02": ("B02", "blue"),
    "B03": ("B03", "green"),
    "B04": ("B04", "red"),
    "B08": ("B08", "nir"),
    "B8A": ("B8A", "nir08"),
    "B11": ("B11", "swir16"),
    "B12": ("B12", "swir22"),
    "SCL": ("SCL", "scl"),
}

ASTER_GROUPED_ASSETS: tuple[str, ...] = ("VNIR", "SWIR", "TIR")


def _extract_compact_asset_info(assets_raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract non-secret band metadata summaries (eo:bands, raster:bands) per STAC asset."""
    info: dict[str, dict[str, Any]] = {}
    for key, val in assets_raw.items():
        if not isinstance(val, dict) or not isinstance(val.get("href"), str):
            continue
        entry: dict[str, Any] = {}
        if isinstance(val.get("title"), str):
            entry["title"] = val["title"]
        eo_bands = val.get("eo:bands")
        if isinstance(eo_bands, list):
            entry["eo_bands"] = [
                {
                    "name": b.get("name"),
                    "common_name": b.get("common_name"),
                    "center_wavelength": b.get("center_wavelength"),
                }
                for b in eo_bands
                if isinstance(b, dict)
            ]
        raster_bands = val.get("raster:bands")
        if isinstance(raster_bands, list):
            entry["raster_bands"] = [
                {
                    "name": b.get("name"),
                    "nodata": b.get("nodata"),
                    "data_type": b.get("data_type"),
                    "spatial_resolution": b.get("spatial_resolution"),
                }
                for b in raster_bands
                if isinstance(b, dict)
            ]
        if entry:
            info[str(key)] = entry
    return info


def resolve_scene_download_targets(
    *,
    collection: str | None,
    product_type: str | None,
    asset_hrefs: dict[str, str],
    band_key: str = "auto",
) -> list[tuple[str, str, str]]:
    """Resolve `(canonical_band_key, source_asset_key, raw_url)` targets for a scene.

    Never substitutes missing spectral bands with another band.
    """
    if not asset_hrefs:
        return []

    requested = band_key.strip()
    col = (collection or "").lower()
    ptype = (product_type or "").lower()

    if requested.lower() in {"auto", "all"}:
        if "sentinel-2" in col or "sentinel2" in ptype:
            targets: list[tuple[str, str, str]] = []
            for canon, candidates in SENTINEL2_CANONICAL_BAND_ASSETS.items():
                for cand in candidates:
                    if cand in asset_hrefs:
                        targets.append((canon, cand, asset_hrefs[cand]))
                        break
            return targets
        if "aster" in col or "ast_" in col or "aster" in ptype:
            return [
                (grp, grp, asset_hrefs[grp])
                for grp in ASTER_GROUPED_ASSETS
                if grp in asset_hrefs
            ]
        if "dem" in col or "dem" in ptype:
            for cand in ("data", "dem", "elevation"):
                if cand in asset_hrefs:
                    return [("DEM", cand, asset_hrefs[cand])]
        first_key = next(iter(asset_hrefs.keys()))
        return [(first_key, first_key, asset_hrefs[first_key])]

    # Explicit single or comma-separated band keys
    targets = []
    for raw_tok in [t.strip() for t in requested.split(",") if t.strip()]:
        if raw_tok in asset_hrefs:
            canon = next(
                (
                    k
                    for k, cands in SENTINEL2_CANONICAL_BAND_ASSETS.items()
                    if raw_tok in cands
                ),
                raw_tok,
            )
            targets.append((canon, raw_tok, asset_hrefs[raw_tok]))
            continue
        upper = raw_tok.upper()
        if upper in SENTINEL2_CANONICAL_BAND_ASSETS:
            for cand in SENTINEL2_CANONICAL_BAND_ASSETS[upper]:
                if cand in asset_hrefs:
                    targets.append((upper, cand, asset_hrefs[cand]))
                    break
            continue
        lower = raw_tok.lower()
        for alias_cands in BAND_ALIASES.values():
            if lower in [a.lower() for a in alias_cands]:
                for cand in alias_cands:
                    if cand in asset_hrefs:
                        targets.append((raw_tok, cand, asset_hrefs[cand]))
                        break
                break
    return targets


def estimate_clipped_raster_mb(
    aoi_area_km2: float,
    *,
    resolution_m: float = 10.0,
    band_count: int = 6,
    bytes_per_pixel: int = 2,
) -> float:
    """Estimate uncompressed/deflate raster footprint (MB) for an AOI window before downloading."""
    res = max(resolution_m, 1.0)
    pixels_per_km2 = (1000.0 / res) ** 2
    raw_bytes = aoi_area_km2 * pixels_per_km2 * max(band_count, 1) * bytes_per_pixel
    # Add 1.25x header/overviews safety factor
    return round((raw_bytes * 1.25) / (1024.0 * 1024.0), 3)


def _infer_collection_defaults(collection: str, props: dict[str, Any], asset_keys: list[str]) -> tuple[str, str, float | None]:
    col = collection.lower()
    if "sentinel-2" in col:
        return (str(props.get("platform") or "sentinel-2"), "multispectral_l2a", 10.0)
    if "landsat" in col or "hlsl30" in col:
        return (str(props.get("platform") or "landsat"), "multispectral_l2", 30.0)
    if "cop-dem-glo-30" in col:
        return ("copernicus-dem", "dem_glo30", 30.0)
    if "cop-dem-glo-90" in col:
        return ("copernicus-dem", "dem_glo90", 90.0)
    if "emitl2bmin" in col:
        return ("emit-iss", "hyperspectral_mineralogy", 60.0)
    if "emitl2arfl" in col:
        return ("emit-iss", "hyperspectral_reflectance", 60.0)
    if "aster" in col or "ast_" in col:
        has_tir_only = "TIR" in asset_keys and "VNIR" not in asset_keys and "SWIR" not in asset_keys
        return (
            "terra-aster",
            "aster_tir_only" if has_tir_only else "aster_multispectral",
            90.0 if has_tir_only else 15.0,
        )
    return (str(props.get("platform") or "unknown"), collection, None)


class STACSceneMetadata(BaseModel):
    """Normalized STAC item metadata (discovered before downloading large COGs)."""

    provider_key: str
    collection: str
    item_id: str
    platform: str | None = None
    product_type: str | None = None
    acquired_at: datetime | None = None
    cloud_cover_pct: float | None = None
    resolution_m: float | None = None
    requires_auth: bool = False
    auth_note: str | None = None
    estimated_size_mb: float | None = None
    bands_available: list[str] = Field(default_factory=list)
    bbox: list[float]
    geometry: dict[str, Any]
    asset_hrefs: dict[str, str] = Field(default_factory=dict)
    asset_info: dict[str, dict[str, Any]] = Field(default_factory=dict)


class STACSearchAdapter(BaseProviderAdapter):
    """Generic STAC API v1.0 `/search` and MPC SAS signer client."""

    def __init__(
        self,
        *,
        provider_key: str,
        base_url: str,
        sas_token_url: str = "https://planetarycomputer.microsoft.com/api/sas/v1/token",
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_key = provider_key
        self.sas_token_url = sas_token_url.rstrip("/")
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=3.0,
            cache=cache,
            transport=transport,
        )

    async def get_collections(self) -> list[str]:
        """Inspect available STAC collections dynamically from `/collections`."""
        resp = await self.request("GET", "/collections")
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid collections JSON: {exc}") from exc
        cols = payload.get("collections") if isinstance(payload, dict) else None
        if not isinstance(cols, list):
            raise ProviderResponseError(self.provider_key, "Malformed STAC /collections payload")
        return [str(c["id"]) for c in cols if isinstance(c, dict) and "id" in c]

    async def sign_mpc_asset_url(self, asset_href: str, collection: str) -> str:
        """Append ephemeral Microsoft Planetary Computer SAS query string to a COG blob URL."""
        if self.provider_key != "mpc_stac":
            return asset_href
        resp = await self.request("GET", f"{self.sas_token_url}/{collection}")
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid SAS JSON: {exc}") from exc
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderResponseError(self.provider_key, "Missing SAS token from MPC endpoint")
        parsed = urlparse(asset_href)
        new_query = f"{parsed.query}&{token}" if parsed.query else token
        return urlunparse(parsed._replace(query=new_query))

    async def search(
        self,
        *,
        bbox: tuple[float, float, float, float],
        collections: list[str],
        datetime_range: str | None = None,
        max_cloud_cover: float | None = 30.0,
        aoi_area_km2: float = 100.0,
        limit: int = 10,
    ) -> list[STACSceneMetadata]:
        body: dict[str, Any] = {
            "bbox": list(bbox),
            "collections": collections,
            "limit": limit,
        }
        if datetime_range:
            body["datetime"] = datetime_range
        if (
            max_cloud_cover is not None
            and self.provider_key != "nasa_cmr_stac"
            and any(
                c in ("sentinel-2-l2a", "sentinel-2-c1-l2a", "landsat-c2-l2", "aster-l1t")
                for c in collections
            )
        ):
            body["query"] = {"eo:cloud_cover": {"lte": max_cloud_cover}}

        resp = await self.request("POST", "/search", json_body=body)
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid STAC JSON: {exc}") from exc

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise ProviderResponseError(
                self.provider_key, "Malformed STAC search payload: missing 'features' list"
            )

        items: list[STACSceneMetadata] = []
        for feat in features:
            if not isinstance(feat, dict) or "id" not in feat:
                continue
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            item_bbox = feat.get("bbox")
            if not isinstance(geom, dict) or not isinstance(item_bbox, list) or len(item_bbox) < 4:
                continue

            dt_raw = props.get("datetime")
            acquired_at = None
            if isinstance(dt_raw, str):
                try:
                    acquired_at = datetime.fromisoformat(dt_raw)
                except ValueError:
                    acquired_at = None

            cloud = props.get("eo:cloud_cover")
            if max_cloud_cover is not None and cloud is not None and float(cloud) > max_cloud_cover:
                continue

            assets_raw = feat.get("assets") or {}
            asset_hrefs = {
                k: sanitize_url_for_storage(v["href"])
                for k, v in assets_raw.items()
                if isinstance(v, dict) and isinstance(v.get("href"), str)
            }
            asset_info = _extract_compact_asset_info(assets_raw)
            collection_id = str(feat.get("collection") or (collections[0] if collections else ""))
            asset_keys = sorted(asset_hrefs.keys())
            platform, product_type, resolution_m = _infer_collection_defaults(
                collection_id, props, asset_keys
            )

            requires_auth = self.provider_key == "nasa_cmr_stac"
            auth_note = (
                "NASA Earthdata Login bearer token required for scientific raster downloads."
                if requires_auth
                else (
                    "Ephemeral public SAS token required (auto-signed by backend)."
                    if self.provider_key == "mpc_stac"
                    else "Open public COG asset access."
                )
            )
            spectral_keys = [
                k for k in asset_keys if not k.endswith(("metadata", "preview", "xml", "json", "txt"))
            ]
            est_mb = estimate_clipped_raster_mb(
                aoi_area_km2,
                resolution_m=resolution_m or 30.0,
                band_count=max(1, min(len(spectral_keys), 6)),
            )

            items.append(
                STACSceneMetadata(
                    provider_key=self.provider_key,
                    collection=collection_id,
                    item_id=str(feat["id"]),
                    platform=platform,
                    product_type=product_type,
                    acquired_at=acquired_at,
                    cloud_cover_pct=float(cloud) if cloud is not None else None,
                    resolution_m=resolution_m,
                    requires_auth=requires_auth,
                    auth_note=auth_note,
                    estimated_size_mb=est_mb,
                    bands_available=asset_keys,
                    bbox=[float(x) for x in item_bbox[:4]],
                    geometry=geom,
                    asset_hrefs=asset_hrefs,
                    asset_info=asset_info,
                )
            )
        return items


class SentinelSTACWithFallback:
    """Queries Microsoft Planetary Computer STAC first, failing over to Element 84 Earth Search."""

    def __init__(
        self,
        *,
        primary: STACSearchAdapter,
        fallback: STACSearchAdapter,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    async def search_sentinel2(
        self,
        *,
        bbox: tuple[float, float, float, float],
        datetime_range: str | None = None,
        max_cloud_cover: float = 30.0,
        aoi_area_km2: float = 100.0,
        limit: int = 10,
    ) -> tuple[str, list[STACSceneMetadata]]:
        try:
            items = await self.primary.search(
                bbox=bbox,
                collections=["sentinel-2-l2a"],
                datetime_range=datetime_range,
                max_cloud_cover=max_cloud_cover,
                aoi_area_km2=aoi_area_km2,
                limit=limit,
            )
            return self.primary.provider_key, items
        except ProviderError as exc:
            logger.warning(
                "Primary STAC (%s) failed (%s); falling back to %s",
                self.primary.provider_key,
                exc,
                self.fallback.provider_key,
            )
            items = await self.fallback.search(
                bbox=bbox,
                collections=["sentinel-2-l2a"],
                datetime_range=datetime_range,
                max_cloud_cover=max_cloud_cover,
                aoi_area_km2=aoi_area_km2,
                limit=limit,
            )
            return self.fallback.provider_key, items
