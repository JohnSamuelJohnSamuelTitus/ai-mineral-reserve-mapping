"""STAC adapters for Microsoft Planetary Computer, Element 84 Earth Search, and NASA CMR."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.core.logging import get_logger
from app.integrations.base import BaseProviderAdapter, ProviderError, ProviderResponseError

logger = get_logger(__name__)


class STACSceneMetadata(BaseModel):
    """Normalized STAC item metadata (discovered before downloading large COGs)."""

    provider_key: str
    collection: str
    item_id: str
    acquired_at: datetime | None = None
    cloud_cover_pct: float | None = None
    bbox: list[float]
    geometry: dict[str, Any]
    asset_hrefs: dict[str, str] = Field(default_factory=dict)


class STACSearchAdapter(BaseProviderAdapter):
    """Generic STAC API v1.0 `/search` client."""

    def __init__(
        self,
        *,
        provider_key: str,
        base_url: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_key = provider_key
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=3.0,
            cache=cache,
            transport=transport,
        )

    async def search(
        self,
        *,
        bbox: tuple[float, float, float, float],
        collections: list[str],
        datetime_range: str | None = None,
        max_cloud_cover: float | None = 30.0,
        limit: int = 10,
    ) -> list[STACSceneMetadata]:
        body: dict[str, Any] = {
            "bbox": list(bbox),
            "collections": collections,
            "limit": limit,
        }
        if datetime_range:
            body["datetime"] = datetime_range
        if max_cloud_cover is not None and self.provider_key != "nasa_cmr_stac":
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
            assets_raw = feat.get("assets") or {}
            asset_hrefs = {
                k: v["href"]
                for k, v in assets_raw.items()
                if isinstance(v, dict) and isinstance(v.get("href"), str)
            }

            items.append(
                STACSceneMetadata(
                    provider_key=self.provider_key,
                    collection=str(feat.get("collection") or (collections[0] if collections else "")),
                    item_id=str(feat["id"]),
                    acquired_at=acquired_at,
                    cloud_cover_pct=float(cloud) if cloud is not None else None,
                    bbox=[float(x) for x in item_bbox[:4]],
                    geometry=geom,
                    asset_hrefs=asset_hrefs,
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
        limit: int = 10,
    ) -> tuple[str, list[STACSceneMetadata]]:
        try:
            items = await self.primary.search(
                bbox=bbox,
                collections=["sentinel-2-l2a"],
                datetime_range=datetime_range,
                max_cloud_cover=max_cloud_cover,
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
                limit=limit,
            )
            return self.fallback.provider_key, items
