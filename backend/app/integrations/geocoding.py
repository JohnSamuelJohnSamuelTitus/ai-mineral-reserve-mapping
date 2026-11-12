"""OSM Nominatim geocoding adapter honoring strict 1 req/s and User-Agent policy."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.core.cache import CacheBackend
from app.integrations.base import BaseProviderAdapter, ProviderResponseError


class GeocodedPlace(BaseModel):
    display_name: str
    lat: float
    lon: float
    boundingbox: list[float]  # [min_lat, max_lat, min_lon, max_lon]


class NominatimAdapter(BaseProviderAdapter):
    provider_key = "nominatim"

    def __init__(
        self,
        *,
        base_url: str = "https://nominatim.openstreetmap.org",
        user_agent: str = "AIMineralProspectivityAssistant/0.2",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=1.0,  # Nominatim usage policy max 1 req/s
            cache=cache,
            user_agent=user_agent,
            transport=transport,
        )

    async def geocode(self, query: str, *, limit: int = 5) -> list[GeocodedPlace]:
        if not query or not query.strip():
            raise ValueError("Geocoding query cannot be empty")
        resp = await self.request(
            "GET",
            "/search",
            params={"q": query.strip(), "format": "jsonv2", "limit": min(max(limit, 1), 10)},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise ProviderResponseError(self.provider_key, "Expected JSON list from Nominatim")

        places: list[GeocodedPlace] = []
        for row in payload:
            if not isinstance(row, dict) or "lat" not in row or "lon" not in row:
                continue
            bbox_raw = row.get("boundingbox") or []
            bbox = [float(x) for x in bbox_raw[:4]] if len(bbox_raw) >= 4 else []
            places.append(
                GeocodedPlace(
                    display_name=str(row.get("display_name") or query),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    boundingbox=bbox,
                )
            )
        return places

