"""Canonical geological mineral occurrence normalization and quarantine logic."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pyproj import Transformer
from pyproj.exceptions import ProjError

COMMODITY_SYNONYMS: dict[str, str] = {
    "copper": "Cu",
    "cu": "Cu",
    "cuprum": "Cu",
    "gold": "Au",
    "au": "Au",
    "silver": "Ag",
    "ag": "Ag",
    "iron": "Fe",
    "iron ore": "Fe",
    "fe": "Fe",
    "hematite": "Fe",
    "magnetite": "Fe",
    "zinc": "Zn",
    "zn": "Zn",
    "lead": "Pb",
    "pb": "Pb",
    "nickel": "Ni",
    "ni": "Ni",
    "cobalt": "Co",
    "co": "Co",
    "lithium": "Li",
    "li": "Li",
    "spodumene": "Li",
    "uranium": "U",
    "u": "U",
    "manganese": "Mn",
    "mn": "Mn",
    "chromium": "Cr",
    "chromite": "Cr",
    "cr": "Cr",
    "tin": "Sn",
    "sn": "Sn",
    "tungsten": "W",
    "w": "W",
    "molybdenum": "Mo",
    "mo": "Mo",
    "bauxite": "Al",
    "aluminium": "Al",
    "aluminum": "Al",
    "al": "Al",
    "graphite": "C",
    "rare earth elements": "REE",
    "ree": "REE",
    "titanium": "Ti",
    "ti": "Ti",
    "limestone": "Limestone",
    "diamond": "Diamond",
    "phosphate": "P",
    "p": "P",
    "barite": "Ba",
    "barium": "Ba",
    "ba": "Ba",
    "platinum": "Pt",
    "pt": "Pt",
    "palladium": "Pd",
    "pd": "Pd",
    "antimony": "Sb",
    "sb": "Sb",
    "arsenic": "As",
    "as": "As",
    "mercury": "Hg",
    "hg": "Hg",
    "bismuth": "Bi",
    "bi": "Bi",
    "beryllium": "Be",
    "be": "Be",
    "thorium": "Th",
    "th": "Th",
    "zirconium": "Zr",
    "zr": "Zr",
    "niobium": "Nb",
    "nb": "Nb",
    "tantalum": "Ta",
    "ta": "Ta",
    "vanadium": "V",
    "v": "V",
    "sulfur": "S",
    "sulphur": "S",
    "s": "S",
    "re": "REE",
    "pgm": "PGM",
}


def normalize_commodity_token(raw_token: str) -> str:
    """Map inconsistent commodity strings to canonical chemical/commodity symbols."""
    cleaned = raw_token.strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in COMMODITY_SYNONYMS:
        return COMMODITY_SYNONYMS[lowered]
    return cleaned.title() if len(cleaned) > 3 else cleaned.upper()


def parse_commodity_list(raw_value: Any) -> list[str]:
    """Normalize delimited strings or lists into unique ordered canonical symbols."""
    tokens: list[str] = []
    if isinstance(raw_value, str):
        for sep_part in raw_value.replace(";", ",").replace("|", ",").split(","):
            norm = normalize_commodity_token(sep_part)
            if norm and norm not in tokens:
                tokens.append(norm)
    elif isinstance(raw_value, (list, tuple)):
        for item in raw_value:
            for norm in parse_commodity_list(item):
                if norm not in tokens:
                    tokens.append(norm)
    return tokens


@dataclass
class NormalizedOccurrence:
    external_id: str
    name: str
    commodity_primary: str | None
    commodities_all: list[str]
    occurrence_type: str | None
    deposit_type: str | None
    geologic_age: str | None
    host_rock: str | None
    country: str | None
    region: str | None
    lon: float
    lat: float
    source_provider_key: str
    license_name: str
    label_authority: str
    data_origin: str
    collection_date: datetime
    source_publication_date: str | None
    quality_flags: list[str]
    raw_attributes: dict[str, Any]


@dataclass
class QuarantinedRecord:
    source_provider_key: str
    external_id: str | None
    rejection_reason: str
    quality_flags: list[str]
    raw_record: dict[str, Any]


@dataclass
class NormalizationBatchResult:
    accepted: list[NormalizedOccurrence] = field(default_factory=list)
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    total_rows: int = 0
    duplicate_rows: int = 0
    missing_coords_count: int = 0
    invalid_coords_count: int = 0
    missing_commodity_count: int = 0


def _coerce_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped.lower() in {"na", "nan", "null", "none", ""}:
            return None
        try:
            f = float(stripped)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except ValueError:
            return None
    return None


def normalize_occurrence_records(
    raw_rows: list[dict[str, Any]],
    *,
    source_provider_key: str,
    license_name: str,
    label_authority: str,
    data_origin: str = "real",
    input_epsg: int = 4326,
    deduplicate_proximity_deg: float = 1e-4,
) -> NormalizationBatchResult:
    """Normalize raw mineral occurrence dicts while quarantining problematic rows."""
    result = NormalizationBatchResult(total_rows=len(raw_rows))
    transformer = (
        Transformer.from_crs(f"EPSG:{input_epsg}", "EPSG:4326", always_xy=True)
        if input_epsg != 4326
        else None
    )

    seen_external_ids: set[str] = set()
    seen_spatial_keys: set[tuple[int, int, str]] = set()
    now = datetime.now(UTC)

    for idx, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            result.quarantined.append(
                QuarantinedRecord(
                    source_provider_key=source_provider_key,
                    external_id=None,
                    rejection_reason="non_dict_record",
                    quality_flags=["malformed_row"],
                    raw_record={"value": str(row)},
                )
            )
            continue

        ext_id_raw = (
            row.get("external_id")
            or row.get("occurrence_id")
            or row.get("ngdr_id")
            or row.get("dep_id")
            or row.get("mine_code")
            or row.get("id")
        )
        ext_id = str(ext_id_raw).strip() if ext_id_raw is not None else f"{source_provider_key}-{idx}"
        flags: list[str] = []

        # 1. Extract coordinates from common geospatial field names
        x_val = _coerce_float(
            row.get("lon")
            if row.get("lon") is not None
            else (row.get("longitude") if row.get("longitude") is not None else row.get("x"))
        )
        y_val = _coerce_float(
            row.get("lat")
            if row.get("lat") is not None
            else (row.get("latitude") if row.get("latitude") is not None else row.get("y"))
        )

        if x_val is None or y_val is None:
            result.missing_coords_count += 1
            result.quarantined.append(
                QuarantinedRecord(
                    source_provider_key=source_provider_key,
                    external_id=ext_id,
                    rejection_reason="missing_coordinates",
                    quality_flags=["missing_coordinates"],
                    raw_record=row,
                )
            )
            continue

        if transformer is not None:
            try:
                lon, lat = transformer.transform(x_val, y_val)
                flags.append(f"reprojected_from_epsg_{input_epsg}")
            except (ProjError, ValueError, TypeError):
                result.invalid_coords_count += 1
                result.quarantined.append(
                    QuarantinedRecord(
                        source_provider_key=source_provider_key,
                        external_id=ext_id,
                        rejection_reason="crs_reprojection_failed",
                        quality_flags=["invalid_coordinates", f"source_epsg_{input_epsg}"],
                        raw_record=row,
                    )
                )
                continue
        else:
            lon, lat = x_val, y_val

        # Validate WGS84 ranges and guard against (0, 0) null-island artifacts
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0) or (
            abs(lon) < 1e-8 and abs(lat) < 1e-8
        ):
            result.invalid_coords_count += 1
            result.quarantined.append(
                QuarantinedRecord(
                    source_provider_key=source_provider_key,
                    external_id=ext_id,
                    rejection_reason="invalid_wgs84_coordinates",
                    quality_flags=["invalid_coordinates"],
                    raw_record=row,
                )
            )
            continue

        # 2. Duplicate checks (exact ID or near-identical location + name)
        name_raw = str(
            row.get("name") or row.get("site_name") or row.get("prospect_name") or row.get("mine_name") or ext_id
        ).strip()
        if not row.get("name") and not row.get("site_name"):
            flags.append("missing_site_name_defaulted")

        if ext_id in seen_external_ids:
            result.duplicate_rows += 1
            result.quarantined.append(
                QuarantinedRecord(
                    source_provider_key=source_provider_key,
                    external_id=ext_id,
                    rejection_reason="duplicate_external_id",
                    quality_flags=["duplicate_record"],
                    raw_record=row,
                )
            )
            continue

        grid_x = round(lon / deduplicate_proximity_deg)
        grid_y = round(lat / deduplicate_proximity_deg)
        spatial_sig = (grid_x, grid_y, name_raw.lower())
        if spatial_sig in seen_spatial_keys:
            result.duplicate_rows += 1
            result.quarantined.append(
                QuarantinedRecord(
                    source_provider_key=source_provider_key,
                    external_id=ext_id,
                    rejection_reason="duplicate_spatial_location_name",
                    quality_flags=["duplicate_record", "spatial_collision"],
                    raw_record=row,
                )
            )
            continue

        seen_external_ids.add(ext_id)
        seen_spatial_keys.add(spatial_sig)

        # 3. Commodity normalization
        commodities = parse_commodity_list(
            row.get("commodities_all")
            or row.get("commodity")
            or row.get("commodity_primary")
            or row.get("commod1")
        )
        if not commodities:
            result.missing_commodity_count += 1
            flags.append("missing_commodity")

        raw_with_meta = dict(row)
        country = row.get("country") or ("IN" if label_authority == "indian_official" else None)
        region = row.get("region") or row.get("state") or row.get("district")
        pub_date = row.get("source_publication_date") or row.get("publication_date")
        if region is None:
            flags.append("missing_region")

        raw_with_meta["_provenance"] = {
            "source_provider_key": source_provider_key,
            "license": license_name,
            "label_authority": label_authority,
            "data_origin": data_origin,
            "country": country,
            "region": region,
            "source_publication_date": str(pub_date) if pub_date else None,
            "collection_date": now.isoformat(),
            "quality_flags": flags,
        }

        result.accepted.append(
            NormalizedOccurrence(
                external_id=ext_id,
                name=name_raw,
                commodity_primary=commodities[0] if commodities else None,
                commodities_all=commodities,
                occurrence_type=row.get("occurrence_type") or row.get("dev_stat") or row.get("status"),
                deposit_type=row.get("deposit_type") or row.get("mineralisation_style"),
                geologic_age=row.get("geologic_age"),
                host_rock=row.get("host_rock") or row.get("geological_setting"),
                country=str(country) if country else None,
                region=str(region) if region else None,
                lon=lon,
                lat=lat,
                source_provider_key=source_provider_key,
                license_name=license_name,
                label_authority=label_authority,
                data_origin=data_origin,
                collection_date=now,
                source_publication_date=str(pub_date) if pub_date else None,
                quality_flags=flags,
                raw_attributes=raw_with_meta,
            )
        )

    return result
