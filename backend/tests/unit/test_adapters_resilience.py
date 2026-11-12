"""Resilience, error-handling, fallback, and parser tests for external API adapters."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.cache import InMemoryTTLCache
from app.integrations.base import (
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.integrations.elevation import (
    ElevationService,
    OpenMeteoElevationAdapter,
    OpenTopoDataAdapter,
)
from app.integrations.india_sources import (
    DataGovInAdapter,
    load_indian_official_csv,
    parse_indian_official_geojson,
)
from app.integrations.literature import OpenAlexAdapter
from app.integrations.macrostrat import MacrostratAdapter
from app.integrations.stac import SentinelSTACWithFallback, STACSearchAdapter
from app.integrations.usgs_mrds import USGSMRDSAdapter


@pytest.mark.asyncio
async def test_macrostrat_success_and_cache() -> None:
    calls = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "success": {
                    "v": 2,
                    "data": [
                        {
                            "map_id": 934954,
                            "name": "Delhi Supergroup Quartzite",
                            "strat_name": "Alwar Group",
                            "lith": "quartzite, schist",
                            "t_age": 1600.0,
                            "b_age": 1800.0,
                            "best_int_name": "Paleoproterozoic",
                        }
                    ],
                }
            },
        )

    adapter = MacrostratAdapter(
        cache=InMemoryTTLCache(),
        transport=httpx.MockTransport(handler),
    )
    units1 = await adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)
    units2 = await adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)
    assert len(units1) == 1
    assert units1[0].map_id == 934954
    assert units2[0].name == "Delhi Supergroup Quartzite"
    assert calls == 1  # Second call served from cache


@pytest.mark.asyncio
async def test_macrostrat_retries_429_then_succeeds() -> None:
    attempts = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(200, json={"success": {"data": []}})

    adapter = MacrostratAdapter(
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    adapter.backoff_base_seconds = 0.01
    units = await adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)
    assert units == []
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_exc"),
    [
        (429, ProviderRateLimitError),
        (503, ProviderUnavailableError),
        (504, ProviderUnavailableError),
    ],
)
async def test_adapter_http_429_503_504_exhaustion(
    status_code: int, expected_exc: type[Exception]
) -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    adapter = MacrostratAdapter(
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )
    adapter.backoff_base_seconds = 0.005
    with pytest.raises(expected_exc):
        await adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)


@pytest.mark.asyncio
async def test_adapter_timeout_and_invalid_json() -> None:
    def timeout_handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout")

    t_adapter = MacrostratAdapter(max_retries=1, transport=httpx.MockTransport(timeout_handler))
    t_adapter.backoff_base_seconds = 0.005
    with pytest.raises(ProviderTimeoutError):
        await t_adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)

    def bad_json_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Not JSON</html>")

    j_adapter = MacrostratAdapter(max_retries=0, transport=httpx.MockTransport(bad_json_handler))
    with pytest.raises(ProviderResponseError):
        await j_adapter.get_geologic_units_at_point(lat=28.0, lon=75.8)


@pytest.mark.asyncio
async def test_usgs_mrds_gml2_parsing_and_service_exception() -> None:
    sample_gml = """<?xml version="1.0" encoding="UTF-8"?>
    <wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"
        xmlns:gml="http://www.opengis.net/gml"
        xmlns:ms="http://mapserver.gis.umn.edu/mapserver">
      <gml:featureMember>
        <ms:mrds-low fid="mrds-low.1">
          <ms:dep_id>10012345</ms:dep_id>
          <ms:site_name>Khetri Copper Prospect</ms:site_name>
          <ms:commod1>Copper</ms:commod1>
          <ms:commod2>Gold</ms:commod2>
          <ms:dev_stat>Producer</ms:dev_stat>
          <gml:Point><gml:coordinates>75.79,28.01</gml:coordinates></gml:Point>
        </ms:mrds-low>
      </gml:featureMember>
    </wfs:FeatureCollection>"""

    adapter = USGSMRDSAdapter(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=sample_gml))
    )
    records = await adapter.fetch_occurrences_bbox(
        min_lon=75.5, min_lat=27.8, max_lon=76.0, max_lat=28.2
    )
    assert len(records) == 1
    assert records[0].external_id == "10012345"
    assert records[0].commodities_all == ["Copper", "Gold"]
    assert records[0].lon == pytest.approx(75.79)

    service_exc = """<?xml version="1.0" encoding="UTF-8"?>
    <ServiceExceptionReport version="1.2.0"><ServiceException>Unsupported outputFormat</ServiceException></ServiceExceptionReport>"""
    err_adapter = USGSMRDSAdapter(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=service_exc))
    )
    with pytest.raises(ProviderResponseError, match="ServiceException"):
        await err_adapter.fetch_occurrences_bbox(
            min_lon=75.5, min_lat=27.8, max_lon=76.0, max_lat=28.2
        )


@pytest.mark.asyncio
async def test_stac_graceful_fallback_on_503() -> None:
    def failing_mpc(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def working_earth_search(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "id": "S2A_43REK_20261010_0_L2A",
                        "collection": "sentinel-2-l2a",
                        "bbox": [75.5, 27.8, 76.0, 28.2],
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[75.5, 27.8], [76.0, 27.8], [76.0, 28.2], [75.5, 28.2], [75.5, 27.8]]],
                        },
                        "properties": {"datetime": "2026-10-10T05:30:00Z", "eo:cloud_cover": 4.2},
                        "assets": {"red": {"href": "https://example.org/B04.tif"}},
                    }
                ],
            },
        )

    mpc = STACSearchAdapter(
        provider_key="mpc_stac",
        base_url="https://mpc.test/v1",
        max_retries=0,
        transport=httpx.MockTransport(failing_mpc),
    )
    es = STACSearchAdapter(
        provider_key="earth_search_stac",
        base_url="https://es.test/v1",
        max_retries=0,
        transport=httpx.MockTransport(working_earth_search),
    )
    service = SentinelSTACWithFallback(primary=mpc, fallback=es)
    used_provider, scenes = await service.search_sentinel2(bbox=(75.5, 27.8, 76.0, 28.2))
    assert used_provider == "earth_search_stac"
    assert len(scenes) == 1
    assert scenes[0].cloud_cover_pct == pytest.approx(4.2)


@pytest.mark.asyncio
async def test_elevation_fallback_to_openmeteo() -> None:
    primary = OpenTopoDataAdapter(
        max_retries=0,
        transport=httpx.MockTransport(lambda _r: httpx.Response(504)),
    )
    fallback = OpenMeteoElevationAdapter(
        max_retries=0,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"elevation": [384.5]})),
    )
    svc = ElevationService(primary=primary, fallback=fallback)
    pts = await svc.get_points([(28.0, 75.8)])
    assert len(pts) == 1
    assert pts[0].provider_key == "openmeteo_elevation"
    assert pts[0].elevation_m == pytest.approx(384.5)


@pytest.mark.asyncio
async def test_india_sources_reject_html_and_parse_official_files(tmp_path: Path) -> None:
    # HTML 200 homepage must NOT be accepted as usable JSON API
    adapter = DataGovInAdapter(
        api_key="dummy-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Portal</html>")
        ),
    )
    with pytest.raises(ProviderResponseError, match="HTML instead of JSON"):
        await adapter.fetch_resource("some-resource-id")

    # Missing API key raises explicit error
    unkeyed = DataGovInAdapter(api_key=None)
    with pytest.raises(ProviderResponseError, match="DATA_GOV_IN_API_KEY"):
        await unkeyed.fetch_resource("some-resource-id")

    # Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_indian_official_csv(tmp_path / "missing.csv")

    # Valid Indian GeoJSON fixture
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [75.79, 28.01]},
                "properties": {
                    "ngdr_id": "GSI-RJ-001",
                    "name": "Kolihan Copper Deposit",
                    "commodity": "Copper, Gold",
                    "state": "Rajasthan",
                },
            }
        ],
    }
    parsed = parse_indian_official_geojson(fc, source_provider_key="ngdr_geodataindia")
    assert len(parsed) == 1
    assert parsed[0].external_id == "GSI-RJ-001"
    assert parsed[0].commodities_all == ["Copper", "Gold"]


@pytest.mark.asyncio
async def test_openalex_search_works() -> None:
    adapter = OpenAlexAdapter(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W123",
                            "title": "Copper Prospectivity in the Khetri Belt",
                            "publication_year": 2024,
                            "doi": "https://doi.org/10.1000/test",
                            "cited_by_count": 12,
                            "concepts": [{"display_name": "Geology"}],
                        }
                    ]
                },
            )
        )
    )
    works = await adapter.search_works("Khetri copper")
    assert len(works) == 1
    assert works[0].publication_year == 2024

