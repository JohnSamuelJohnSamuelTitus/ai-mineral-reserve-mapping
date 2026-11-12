"""NASA GIBS WMTS/XYZ visualization overlay catalog (strictly visualization-only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def get_nasa_gibs_overlay_layers(base_url: str = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best") -> list[dict[str, Any]]:
    """Return visualization tile layers clearly flagged as non-quantitative overlays."""
    # Use a date 2 days prior to ensure global daily composite completeness
    recent_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
    clean_base = base_url.rstrip("/")
    return [
        {
            "layer_id": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
            "title": "NASA GIBS VIIRS True Color (Visualization Only)",
            "provider_key": "nasa_gibs",
            "tile_url_template": (
                f"{clean_base}/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/"
                f"{recent_date}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpg"
            ),
            "max_zoom": 9,
            "is_quantitative_science_product": False,
            "attribution": "NASA EOSDIS GIBS",
            "note": "Daily RGB browse imagery only; NOT suitable for spectral band ratios or ML features.",
        },
        {
            "layer_id": "ASTER_GDEM_Color_Shaded_Relief",
            "title": "NASA GIBS ASTER GDEM Shaded Relief (Visualization Only)",
            "provider_key": "nasa_gibs",
            "tile_url_template": (
                f"{clean_base}/ASTER_GDEM_Color_Shaded_Relief/default/"
                "default/GoogleMapsCompatible_Level12/{z}/{y}/{x}.jpg"
            ),
            "max_zoom": 12,
            "is_quantitative_science_product": False,
            "attribution": "NASA / METI ASTER GDEM via GIBS",
            "note": "Pre-rendered hillshade visualization ONLY; use Copernicus DEM / SRTM COGs for slope/aspect.",
        },
    ]
