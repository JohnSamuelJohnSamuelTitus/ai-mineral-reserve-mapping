"""USGS Mineral Resources Data System (MRDS) WFS 1.0.0 GML2 adapter."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.geological.normalizer import COMMODITY_SYNONYMS
from app.integrations.base import BaseProviderAdapter, ProviderResponseError

_MRDS_DELIM_RE = re.compile(r"[\s,;|/]+")


class MRDSOccurrenceRecord(BaseModel):
    """Normalized USGS MRDS mineral occurrence parsed from WFS GML2."""

    external_id: str
    name: str
    commodity_primary: str | None = None
    commodities_all: list[str] = Field(default_factory=list)
    raw_commodities: list[str] = Field(default_factory=list)
    unknown_commodity_codes: list[str] = Field(default_factory=list)
    occurrence_type: str | None = None
    deposit_type: str | None = None
    lon: float
    lat: float
    raw_attributes: dict[str, Any] = Field(default_factory=dict)


class USGSMRDSAdapter(BaseProviderAdapter):
    """Queries USGS MRDS WFS 1.0.0 (`mrds-low` / `mrds-high` GML2) within a bounding box."""

    provider_key = "usgs_mrds"

    def __init__(
        self,
        *,
        base_url: str = "https://mrdata.usgs.gov/services/mrds",
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=2.0,
            cache=cache,
            transport=transport,
        )

    async def fetch_occurrences_bbox(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        max_features: int = 150,
        typename: str = "mrds-low",
    ) -> list[MRDSOccurrenceRecord]:
        """Fetch MRDS features in GML2 format for a WGS84 bounding box."""
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("Invalid bbox: min must be less than max")
        if typename not in ("mrds-low", "mrds-high"):
            raise ValueError("USGS MRDS WFS typename must be 'mrds-low' or 'mrds-high'")

        params = {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typename": typename,
            "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "maxfeatures": str(max_features),
        }
        resp = await self.request("GET", self.base_url, params=params)
        return self.parse_gml2(resp.text)

    @classmethod
    def parse_gml2(cls, xml_text: str | bytes) -> list[MRDSOccurrenceRecord]:
        """Parse USGS MapServer WFS 1.0.0 GML2 XML safely."""
        provider_key = getattr(cls, "provider_key", "usgs_mrds")
        if isinstance(xml_text, bytes):
            xml_text = xml_text.decode("utf-8", errors="replace")
        if not xml_text or not xml_text.strip():
            raise ProviderResponseError(provider_key, "Empty XML response from MRDS WFS")

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise ProviderResponseError(provider_key, f"Malformed XML from MRDS WFS: {exc}") from exc

        root_tag = root.tag.split("}")[-1]
        if root_tag == "ServiceExceptionReport":
            msg = " ".join(elem.text.strip() for elem in root.iter() if elem.text and elem.text.strip())
            raise ProviderResponseError(provider_key, f"WFS ServiceException: {msg[:300]}")

        records: list[MRDSOccurrenceRecord] = []
        for member in root.iter():
            if member.tag.split("}")[-1] != "featureMember":
                continue

            feature_elem = next(iter(member), None)
            if feature_elem is None:
                continue

            attrs: dict[str, str] = {}
            coords_text: str | None = None
            for elem in feature_elem.iter():
                local = elem.tag.split("}")[-1]
                if local == "coordinates" and elem.text:
                    coords_text = elem.text.strip()
                elif elem.text and elem.text.strip() and len(list(elem)) == 0:
                    attrs[local.lower()] = elem.text.strip()

            lon_lat = cls._parse_coords(coords_text, attrs)
            if lon_lat is None:
                continue
            lon, lat = lon_lat
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                continue

            dep_id = attrs.get("dep_id") or attrs.get("mrds_id") or feature_elem.attrib.get("fid")
            if not dep_id:
                continue

            site_name = attrs.get("site_name") or attrs.get("name") or f"MRDS-{dep_id}"
            explicit_commods = cls._split_commodities(
                attrs.get("commod1"),
                attrs.get("commod2"),
                attrs.get("commod3"),
                attrs.get("commodity"),
            )
            code_list_raw = attrs.get("code_list")
            raw_code_tokens = cls._split_code_list(code_list_raw)
            normalized_codes, unknown_codes = cls._normalize_code_tokens(raw_code_tokens)

            raw_commodities = cls._dedupe_preserve_order([*explicit_commods, *raw_code_tokens])
            # Preserve explicit text tokens (e.g. ["Copper", "Gold"]) when commod1..3 are given;
            # otherwise populate normalized commodities from `code_list` (standard on mrds-low).
            combined_commods = cls._dedupe_preserve_order(
                [*explicit_commods, *normalized_codes]
            )
            primary = combined_commods[0] if combined_commods else None

            raw_attrs_out: dict[str, Any] = dict(attrs)
            if raw_code_tokens:
                raw_attrs_out["raw_commodity_codes"] = raw_code_tokens
            if unknown_codes:
                raw_attrs_out["unknown_commodity_codes"] = unknown_codes

            records.append(
                MRDSOccurrenceRecord(
                    external_id=str(dep_id),
                    name=site_name,
                    commodity_primary=primary,
                    commodities_all=combined_commods,
                    raw_commodities=raw_commodities,
                    unknown_commodity_codes=unknown_codes,
                    occurrence_type=attrs.get("dev_stat") or attrs.get("oper_type"),
                    deposit_type=attrs.get("dep_type") or attrs.get("ore_body"),
                    lon=lon,
                    lat=lat,
                    raw_attributes=raw_attrs_out,
                )
            )
        return records

    @staticmethod
    def _parse_coords(coords_text: str | None, attrs: dict[str, str]) -> tuple[float, float] | None:
        if coords_text:
            first_pair = coords_text.split()[0]
            parts = first_pair.split(",")
            if len(parts) >= 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        if "longitude" in attrs and "latitude" in attrs:
            try:
                return float(attrs["longitude"]), float(attrs["latitude"])
            except ValueError:
                return None
        return None

    @staticmethod
    def _dedupe_preserve_order(tokens: list[str]) -> list[str]:
        seen: list[str] = []
        for token in tokens:
            if token and token not in seen:
                seen.append(token)
        return seen

    @staticmethod
    def _split_commodities(*values: str | None) -> list[str]:
        seen: list[str] = []
        for val in values:
            if not val:
                continue
            for token in val.replace(";", ",").replace("|", ",").split(","):
                cleaned = token.strip()
                if cleaned and cleaned not in seen:
                    seen.append(cleaned)
        return seen

    @staticmethod
    def _split_code_list(code_list_raw: str | None) -> list[str]:
        """Extract ordered tokens from USGS MRDS `code_list` (typically space-delimited)."""
        if not code_list_raw or not code_list_raw.strip():
            return []
        tokens: list[str] = []
        for raw_tok in _MRDS_DELIM_RE.split(code_list_raw.strip()):
            cleaned = raw_tok.strip()
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)
        return tokens

    @staticmethod
    def _normalize_code_tokens(raw_tokens: list[str]) -> tuple[list[str], list[str]]:
        """Map recognized USGS MRDS commodity codes; preserve unknown codes without guessing."""
        normalized: list[str] = []
        unknown: list[str] = []
        for token in raw_tokens:
            lowered = token.strip().lower()
            if not lowered:
                continue
            if lowered in COMMODITY_SYNONYMS:
                canon = COMMODITY_SYNONYMS[lowered]
                if canon not in normalized:
                    normalized.append(canon)
            else:
                preserved = token.strip()
                if preserved not in normalized:
                    normalized.append(preserved)
                if preserved not in unknown:
                    unknown.append(preserved)
        return normalized, unknown
