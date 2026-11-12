"""Idempotent seed data for verified data sources and licensing guardrails."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DataSource

DEFAULT_DATA_SOURCES: list[dict] = [
    # --- India-First Authoritative Sources ---
    {
        "provider_key": "ngdr_geodataindia",
        "display_name": "GSI National Geoscience Data Repository (NGDR)",
        "jurisdiction": "IN",
        "label_authority": "indian_official",
        "base_url": "https://geodataindia.gov.in/",
        "license": "Government Open Data License - India (GODL) / NDSAP",
        "attribution_text": "Geological Survey of India (GSI), Ministry of Mines, Government of India",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Primary Indian official geoscience portal. Portal HTTP 200; bulk/API endpoints require registered portal access.",
    },
    {
        "provider_key": "ibm_india",
        "display_name": "Indian Bureau of Mines (IBM) National Mineral Inventory",
        "jurisdiction": "IN",
        "label_authority": "indian_official",
        "base_url": "https://ibm.gov.in/",
        "license": "GODL-India / Ministry of Mines Terms",
        "attribution_text": "Indian Bureau of Mines (IBM), Ministry of Mines, Government of India",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Official Indian mineral inventory & production statistics (manual/tabular ingest; no public developer REST API).",
    },
    {
        "provider_key": "data_gov_in",
        "display_name": "Open Government Data Platform India (data.gov.in)",
        "jurisdiction": "IN",
        "label_authority": "indian_official",
        "base_url": "https://api.data.gov.in/resource",
        "license": "Government Open Data License - India (GODL)",
        "attribution_text": "Open Government Data (OGD) Platform India / Ministry of Mines",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "REST API for published Indian mineral statistics; requires free registration API key.",
    },
    # --- Verified International Supplements ---
    {
        "provider_key": "usgs_mrds",
        "display_name": "USGS Mineral Resources Data System (MRDS)",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://mrdata.usgs.gov/services/mrds",
        "license": "U.S. Government Public Domain",
        "attribution_text": "U.S. Geological Survey (USGS) Mineral Resources Data System",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Verified WFS 1.0.0 GML2 (mrds-high / mrds-low). International supplement; not equivalent to verified Indian GSI/IBM labels.",
    },
    {
        "provider_key": "macrostrat_v2",
        "display_name": "Macrostrat Geologic Map & Stratigraphy API v2",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://macrostrat.org/api/v2",
        "license": "CC BY 4.0",
        "attribution_text": "Macrostrat (UW-Madison) and underlying geological map contributors (CC BY 4.0)",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Verified JSON/GeoJSON API for bedrock units and lithology.",
    },
    {
        "provider_key": "mpc_stac",
        "display_name": "Microsoft Planetary Computer STAC",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://planetarycomputer.microsoft.com/api/stac/v1",
        "license": "Copernicus Open / USGS Public Domain (COG assets)",
        "attribution_text": "ESA Copernicus Sentinel / USGS Landsat via Microsoft Planetary Computer",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Primary STAC catalog for Sentinel-2 L2A, Landsat C2 L2, ASTER, COP30 DEM.",
    },
    {
        "provider_key": "earth_search_stac",
        "display_name": "Element 84 Earth Search STAC (AWS Open Data)",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://earth-search.aws.element84.com/v1",
        "license": "Copernicus Open Access",
        "attribution_text": "ESA Copernicus Sentinel-2 via Element 84 Earth Search / AWS Open Data",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Failover STAC catalog when Planetary Computer is throttled.",
    },
    {
        "provider_key": "nasa_cmr_stac",
        "display_name": "NASA CMR-STAC (LPCLOUD — EMIT & ASTER)",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://cmr.earthdata.nasa.gov/stac/LPCLOUD",
        "license": "NASA / USGS Public Domain",
        "attribution_text": "NASA LP DAAC (EMIT / ASTER)",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Discovery open; asset download requires Earthdata Login token.",
    },
    {
        "provider_key": "opentopodata",
        "display_name": "Open Topo Data Elevation API",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://api.opentopodata.org/v1",
        "license": "MIT / NASA SRTM Public Domain",
        "attribution_text": "Open Topo Data (SRTM 30m / ASTER)",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Public limit: 100 locations/req, 1 req/s, 1000 calls/day.",
    },
    {
        "provider_key": "openmeteo_elevation",
        "display_name": "Open-Meteo Elevation API",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://api.open-meteo.com/v1/elevation",
        "license": "CC BY 4.0 (Non-Commercial); Commercial Plan Required for Commercial Use",
        "attribution_text": "Open-Meteo / Copernicus GLO-90 DEM",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Fallback elevation source (90m Copernicus DEM).",
    },
    {
        "provider_key": "openalex",
        "display_name": "OpenAlex Works API",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://api.openalex.org",
        "license": "CC0 1.0",
        "attribution_text": "OpenAlex (OurResearch)",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Peer-reviewed geological literature grounding.",
    },
    {
        "provider_key": "nominatim",
        "display_name": "OpenStreetMap Nominatim Geocoder",
        "jurisdiction": "INTL",
        "label_authority": "international_supplement",
        "base_url": "https://nominatim.openstreetmap.org",
        "license": "ODbL 1.0",
        "attribution_text": "OpenStreetMap contributors (ODbL 1.0)",
        "is_ml_training_allowed": True,
        "is_enabled": True,
        "notes": "Max 1 req/s with custom User-Agent.",
    },
    # --- Restricted Source (Explicitly Blocked From ML Training) ---
    {
        "provider_key": "mindat_v1",
        "display_name": "Mindat.org Mineralogy API v1",
        "jurisdiction": "INTL",
        "label_authority": "restricted",
        "base_url": "https://api.mindat.org/v1/",
        "license": "Hudson Institute of Mineralogy Terms (AI/ML Training Prohibited Without Written Permission)",
        "attribution_text": "Mindat.org / Hudson Institute of Mineralogy",
        "is_ml_training_allowed": False,
        "is_enabled": False,
        "notes": "Explicitly blocked from ML training pipelines unless written permission is recorded; also returned HTTP 504 during Phase 1 probe.",
    },
]


def seed_default_data_sources(db: Session) -> int:
    """Insert missing default data sources idempotently."""
    now = datetime.now(UTC)
    created = 0
    for entry in DEFAULT_DATA_SOURCES:
        existing = db.scalar(
            select(DataSource).where(DataSource.provider_key == entry["provider_key"])
        )
        if existing is None:
            db.add(DataSource(**entry, license_verified_at=now))
            created += 1
    if created:
        db.commit()
    return created
