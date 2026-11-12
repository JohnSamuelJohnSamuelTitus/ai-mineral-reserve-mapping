"""India-first official geological adapters (data.gov.in API & local GSI/IBM GeoJSON/CSV parser).

Scientific safeguard:
- Never treats HTML HTTP 200 portal homepages (e.g. geodataindia.gov.in, ibm.gov.in) as usable JSON/WFS APIs.
- Distinguishes verified Indian official occurrences (`label_authority='indian_official'`) from international
  supplements (`label_authority='international_supplement'`).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.integrations.base import BaseProviderAdapter, ProviderResponseError


class IndianOccurrenceRecord(BaseModel):
    external_id: str
    name: str
    commodity_primary: str | None = None
    commodities_all: list[str] = Field(default_factory=list)
    occurrence_type: str | None = None
    deposit_type: str | None = None
    state_ut: str | None = None
    district: str | None = None
    lon: float
    lat: float
    source_provider_key: str
    raw_attributes: dict[str, Any] = Field(default_factory=dict)


class DataGovInAdapter(BaseProviderAdapter):
    """Adapter for Open Government Data Platform India (`api.data.gov.in/resource/{id}`)."""

    provider_key = "data_gov_in"

    def __init__(
        self,
        *,
        base_url: str = "https://api.data.gov.in/resource",
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=2.0,
            cache=cache,
            transport=transport,
        )

    async def fetch_resource(
        self, resource_id: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderResponseError(
                self.provider_key,
                "DATA_GOV_IN_API_KEY is not configured; cannot query api.data.gov.in resources.",
            )
        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id is required")

        resp = await self.request(
            "GET",
            f"/{resource_id.strip()}",
            params={
                "api-key": self._api_key,
                "format": "json",
                "limit": limit,
                "offset": offset,
            },
        )
        content_type = resp.headers.get("content-type", "").lower()
        if "html" in content_type or resp.text.lstrip().startswith("<"):
            raise ProviderResponseError(
                self.provider_key,
                "Received HTML instead of JSON; endpoint is a web page rather than a usable API.",
            )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc

        if not isinstance(payload, dict) or "records" not in payload:
            raise ProviderResponseError(
                self.provider_key, "Malformed data.gov.in response: missing 'records'"
            )
        return payload


def parse_indian_official_geojson(
    geojson_data: dict[str, Any],
    *,
    source_provider_key: str = "ngdr_geodataindia",
) -> list[IndianOccurrenceRecord]:
    """Parse verified exported GSI/NGDR/IBM GeoJSON FeatureCollection into canonical records."""
    if geojson_data.get("type") != "FeatureCollection" or not isinstance(
        geojson_data.get("features"), list
    ):
        raise ProviderResponseError(
            source_provider_key, "Expected GeoJSON FeatureCollection for Indian mineral dataset"
        )

    records: list[IndianOccurrenceRecord] = []
    for idx, feat in enumerate(geojson_data["features"]):
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if geom.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue

        props = feat.get("properties") or {}
        ext_id = str(
            props.get("occurrence_id")
            or props.get("ngdr_id")
            or props.get("id")
            or feat.get("id")
            or f"{source_provider_key}-{idx}"
        )
        name = str(props.get("name") or props.get("prospect_name") or ext_id)
        comm = props.get("commodity") or props.get("commodity_primary")
        comm_list = [c.strip() for c in str(comm).split(",") if c.strip()] if comm else []

        records.append(
            IndianOccurrenceRecord(
                external_id=ext_id,
                name=name,
                commodity_primary=comm_list[0] if comm_list else None,
                commodities_all=comm_list,
                occurrence_type=props.get("occurrence_type") or props.get("status"),
                deposit_type=props.get("deposit_type") or props.get("mineralisation_style"),
                state_ut=props.get("state"),
                district=props.get("district"),
                lon=lon,
                lat=lat,
                source_provider_key=source_provider_key,
                raw_attributes=props,
            )
        )
    return records


def load_indian_official_csv(
    csv_path: Path,
    *,
    source_provider_key: str = "ibm_india",
) -> list[IndianOccurrenceRecord]:
    """Load verified IBM/GSI tabular CSV exports containing `lon`/`lat` columns."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Indian mineral CSV file not found: {csv_path}")

    records: list[IndianOccurrenceRecord] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            lon_raw = row.get("lon") or row.get("longitude")
            lat_raw = row.get("lat") or row.get("latitude")
            if lon_raw is None or lat_raw is None:
                continue
            try:
                lon, lat = float(lon_raw), float(lat_raw)
            except ValueError:
                continue
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                continue

            ext_id = str(row.get("external_id") or row.get("mine_code") or f"{source_provider_key}-{idx}")
            name = str(row.get("name") or row.get("mine_name") or ext_id)
            comm = row.get("commodity") or ""
            comm_list = [c.strip() for c in comm.split(",") if c.strip()]
            records.append(
                IndianOccurrenceRecord(
                    external_id=ext_id,
                    name=name,
                    commodity_primary=comm_list[0] if comm_list else None,
                    commodities_all=comm_list,
                    occurrence_type=row.get("occurrence_type"),
                    deposit_type=row.get("deposit_type"),
                    state_ut=row.get("state"),
                    district=row.get("district"),
                    lon=lon,
                    lat=lat,
                    source_provider_key=source_provider_key,
                    raw_attributes=dict(row),
                )
            )
    return records


def load_indian_official_geojson_file(
    geojson_path: Path,
    *,
    source_provider_key: str = "ngdr_geodataindia",
) -> list[IndianOccurrenceRecord]:
    if not geojson_path.exists():
        raise FileNotFoundError(f"Indian mineral GeoJSON file not found: {geojson_path}")
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    return parse_indian_official_geojson(data, source_provider_key=source_provider_key)

