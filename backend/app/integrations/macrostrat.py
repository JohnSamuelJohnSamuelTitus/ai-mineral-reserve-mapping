"""Macrostrat API v2 adapter for geologic units, lithologies, and stratigraphy."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.integrations.base import BaseProviderAdapter, ProviderResponseError


class MacrostratMapUnit(BaseModel):
    """Validated subset of a Macrostrat `/geologic_units/map` record."""

    map_id: int
    source_id: int | None = None
    name: str = "Unnamed unit"
    strat_name: str | None = None
    lith: str | None = None
    descrip: str | None = None
    t_age: float | None = None
    b_age: float | None = None
    t_int_name: str | None = None
    b_int_name: str | None = None
    color: str | None = None
    best_int_name: str | None = None
    macrostrat_url: str | None = None
    metadata_raw: dict[str, Any] = Field(default_factory=dict)


class MacrostratAdapter(BaseProviderAdapter):
    """Adapter for Macrostrat v2 (CC BY 4.0)."""

    provider_key = "macrostrat_v2"

    def __init__(
        self,
        *,
        base_url: str = "https://macrostrat.org/api/v2",
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=3.0,
            cache=cache,
            transport=transport,
        )

    async def get_geologic_units_at_point(
        self, *, lat: float, lon: float
    ) -> list[MacrostratMapUnit]:
        """Fetch bedrock geologic map units intersecting a WGS84 point."""
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError(f"Coordinates out of WGS84 bounds: lat={lat}, lon={lon}")

        resp = await self.request(
            "GET",
            "/geologic_units/map",
            params={"lat": round(lat, 5), "lng": round(lon, 5)},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON response: {exc}") from exc

        if not isinstance(payload, dict) or "success" not in payload:
            raise ProviderResponseError(
                self.provider_key, "Malformed Macrostrat payload: missing 'success' envelope"
            )

        data = payload.get("success", {}).get("data")
        if not isinstance(data, list):
            raise ProviderResponseError(
                self.provider_key, "Malformed Macrostrat payload: 'success.data' is not a list"
            )

        units: list[MacrostratMapUnit] = []
        for row in data:
            if not isinstance(row, dict) or "map_id" not in row:
                continue
            units.append(
                MacrostratMapUnit(
                    map_id=int(row["map_id"]),
                    source_id=row.get("source_id"),
                    name=str(row.get("name") or row.get("strat_name") or "Unnamed unit"),
                    strat_name=row.get("strat_name"),
                    lith=row.get("lith"),
                    descrip=row.get("descrip"),
                    t_age=float(row["t_age"]) if row.get("t_age") is not None else None,
                    b_age=float(row["b_age"]) if row.get("b_age") is not None else None,
                    t_int_name=row.get("t_int_name"),
                    b_int_name=row.get("b_int_name"),
                    color=row.get("color"),
                    best_int_name=row.get("best_int_name"),
                    metadata_raw=row,
                )
            )
        return units

    async def get_lithology_definitions(self) -> list[dict[str, Any]]:
        """Fetch controlled Macrostrat lithology vocabulary."""
        resp = await self.request("GET", "/defs/lithologies", params={"all": "true"})
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc
        data = payload.get("success", {}).get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ProviderResponseError(self.provider_key, "Missing lithology definitions list")
        return data
