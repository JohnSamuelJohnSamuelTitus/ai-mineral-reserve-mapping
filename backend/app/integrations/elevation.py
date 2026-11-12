"""Elevation adapter using Open Topo Data with Open-Meteo Elevation fallback."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.core.cache import CacheBackend
from app.core.logging import get_logger
from app.integrations.base import BaseProviderAdapter, ProviderError, ProviderResponseError

logger = get_logger(__name__)


class ElevationPoint(BaseModel):
    lat: float
    lon: float
    elevation_m: float | None
    dataset: str
    provider_key: str


class OpenTopoDataAdapter(BaseProviderAdapter):
    provider_key = "opentopodata"

    def __init__(
        self,
        *,
        base_url: str = "https://api.opentopodata.org/v1",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=1.0,  # Public Open Topo Data limit: 1 req/s
            cache=cache,
            transport=transport,
        )

    async def get_elevation(
        self, points: list[tuple[float, float]], *, dataset: str = "srtm30m"
    ) -> list[ElevationPoint]:
        if not points or len(points) > 100:
            raise ValueError("Open Topo Data accepts 1 to 100 (lat, lon) points per request")
        loc_str = "|".join(f"{round(lat, 6)},{round(lon, 6)}" for lat, lon in points)
        resp = await self.request("GET", f"/{dataset}", params={"locations": loc_str})
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or payload.get("status") != "OK":
            raise ProviderResponseError(self.provider_key, "Malformed Open Topo Data response")

        out: list[ElevationPoint] = []
        for item in results:
            loc = item.get("location") or {}
            out.append(
                ElevationPoint(
                    lat=float(loc["lat"]),
                    lon=float(loc["lng"]),
                    elevation_m=float(item["elevation"]) if item.get("elevation") is not None else None,
                    dataset=str(item.get("dataset") or dataset),
                    provider_key=self.provider_key,
                )
            )
        return out


class OpenMeteoElevationAdapter(BaseProviderAdapter):
    provider_key = "openmeteo_elevation"

    def __init__(
        self,
        *,
        base_url: str = "https://api.open-meteo.com/v1/elevation",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=5.0,
            cache=cache,
            transport=transport,
        )

    async def get_elevation(self, points: list[tuple[float, float]]) -> list[ElevationPoint]:
        if not points or len(points) > 100:
            raise ValueError("Open-Meteo Elevation accepts 1 to 100 points per request")
        lats = ",".join(str(round(lat, 6)) for lat, _ in points)
        lons = ",".join(str(round(lon, 6)) for _, lon in points)
        resp = await self.request("GET", self.base_url, params={"latitude": lats, "longitude": lons})
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc

        elevs = payload.get("elevation") if isinstance(payload, dict) else None
        if not isinstance(elevs, list) or len(elevs) != len(points):
            raise ProviderResponseError(self.provider_key, "Malformed Open-Meteo elevation payload")

        return [
            ElevationPoint(
                lat=lat,
                lon=lon,
                elevation_m=float(val) if val is not None else None,
                dataset="copernicus_glo90",
                provider_key=self.provider_key,
            )
            for (lat, lon), val in zip(points, elevs, strict=True)
        ]


class ElevationService:
    """Queries Open Topo Data first and falls back gracefully to Open-Meteo."""

    def __init__(
        self,
        *,
        primary: OpenTopoDataAdapter,
        fallback: OpenMeteoElevationAdapter,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    async def get_points(self, points: list[tuple[float, float]]) -> list[ElevationPoint]:
        try:
            return await self.primary.get_elevation(points)
        except ProviderError as exc:
            logger.warning("Primary elevation provider failed (%s); using Open-Meteo fallback", exc)
            return await self.fallback.get_elevation(points)

