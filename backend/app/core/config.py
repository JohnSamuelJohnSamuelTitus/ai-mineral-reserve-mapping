"""Application settings with secure secret masking and validation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed environment configuration loaded from `.env` or environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="development")
    app_name: str = Field(default="ai-mineral-prospectivity-assistant")
    log_level: str = Field(default="INFO")
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = Field(default="http://localhost:5173")

    # Phase 2 default: SQLite for local Windows development; swap to PostgreSQL+PostGIS later.
    database_url: str = Field(default="sqlite:///./data/mineral_dev.db")
    data_dir: Path = Field(default=PROJECT_ROOT / "data")

    # Cache configuration (abstracted for future Redis swap)
    cache_default_ttl_seconds: int = Field(default=900, ge=1)
    cache_max_entries: int = Field(default=1024, ge=16)

    # HTTP & External Provider Guardrails
    http_timeout_seconds: float = Field(default=15.0, gt=0.5, le=120.0)
    http_max_retries: int = Field(default=3, ge=0, le=6)
    max_aoi_area_km2: float = Field(default=250_000.0, gt=0.0)

    # Provider endpoints (non-secret public URLs)
    macrostrat_base_url: str = Field(default="https://macrostrat.org/api/v2")
    usgs_mrds_wfs_url: str = Field(default="https://mrdata.usgs.gov/services/mrds")
    mpc_stac_url: str = Field(default="https://planetarycomputer.microsoft.com/api/stac/v1")
    earth_search_stac_url: str = Field(default="https://earth-search.aws.element84.com/v1")
    nasa_cmr_stac_url: str = Field(default="https://cmr.earthdata.nasa.gov/stac/LPCLOUD")
    opentopodata_url: str = Field(default="https://api.opentopodata.org/v1")
    openmeteo_elevation_url: str = Field(default="https://api.open-meteo.com/v1/elevation")
    openalex_base_url: str = Field(default="https://api.openalex.org")
    nominatim_base_url: str = Field(default="https://nominatim.openstreetmap.org")
    data_gov_in_base_url: str = Field(default="https://api.data.gov.in/resource")

    # Optional credentials (SecretStr prevents accidental serialization or logging)
    cdse_client_id: SecretStr | None = Field(default=None)
    cdse_client_secret: SecretStr | None = Field(default=None)
    nasa_earthdata_token: SecretStr | None = Field(default=None)
    opentopography_api_key: SecretStr | None = Field(default=None)
    mindat_api_key: SecretStr | None = Field(default=None)
    openalex_api_key: SecretStr | None = Field(default=None)
    data_gov_in_api_key: SecretStr | None = Field(default=None)
    nominatim_user_agent: str = Field(
        default="AIMineralProspectivityAssistant/0.2 (research-dev)"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        allowed_prefixes = ("sqlite:///", "postgresql://", "postgresql+psycopg://")
        if not value.startswith(allowed_prefixes):
            raise ValueError(
                f"Unsupported database_url scheme; expected one of {allowed_prefixes}"
            )
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:///")

    def resolved_database_url(self) -> str:
        """Resolve relative SQLite paths against the repository root consistently."""
        if self.database_url.startswith("sqlite:///./"):
            rel = self.database_url.removeprefix("sqlite:///./")
            target = (PROJECT_ROOT / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{target.as_posix()}"
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
