"""FastAPI endpoint integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import routes
from app.integrations.base import ProviderTimeoutError
from app.integrations.macrostrat import MacrostratMapUnit


def test_health_and_sources_and_license_endpoints(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database_backend"] == "sqlite"
    assert body["postgis_enabled"] is False
    assert "do NOT establish proven or probable mineral reserves" in body["scientific_disclaimer"]

    sources_resp = client.get("/api/v1/sources")
    assert sources_resp.status_code == 200
    keys = {s["provider_key"]: s for s in sources_resp.json()}
    assert "ngdr_geodataindia" in keys
    assert keys["ngdr_geodataindia"]["label_authority"] == "indian_official"
    assert keys["mindat_v1"]["is_ml_training_allowed"] is False

    # Mindat ML training check must return HTTP 403
    mindat_check = client.get("/api/v1/sources/mindat_v1/ml-check")
    assert mindat_check.status_code == 403

    ngdr_check = client.get("/api/v1/sources/ngdr_geodataindia/ml-check")
    assert ngdr_check.status_code == 200


def test_aoi_crud_and_malformed_rejection(client: TestClient) -> None:
    bad = client.post(
        "/api/v1/aois",
        json={
            "name": "Broken Polygon",
            "geometry": {"type": "Point", "coordinates": [75.8, 28.0]},
        },
    )
    assert bad.status_code == 422

    created = client.post(
        "/api/v1/aois",
        json={
            "name": "Singhbhum Copper Belt Test",
            "jurisdiction": "IN",
            "commodity_focus": ["Cu", "U"],
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[86.3, 22.5], [86.5, 22.5], [86.5, 22.7], [86.3, 22.7], [86.3, 22.5]]],
            },
            "data_origin": "synthetic",
        },
    )
    assert created.status_code == 201
    aoi = created.json()
    assert aoi["processing_epsg"] == 32645
    assert 400.0 < aoi["area_km2"] < 550.0

    listed = client.get("/api/v1/aois")
    assert listed.status_code == 200
    assert any(item["id"] == aoi["id"] for item in listed.json())

    fetched = client.get(f"/api/v1/aois/{aoi['id']}")
    assert fetched.status_code == 200

    missing = client.get("/api/v1/aois/nonexistent-id")
    assert missing.status_code == 404

    deleted = client.delete(f"/api/v1/aois/{aoi['id']}")
    assert deleted.status_code == 204


def test_ingestion_endpoint_isolates_provider_timeout(client: TestClient, monkeypatch) -> None:
    created = client.post(
        "/api/v1/aois",
        json={
            "name": "Khetri Test AOI",
            "jurisdiction": "IN",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[75.7, 27.9], [75.9, 27.9], [75.9, 28.1], [75.7, 28.1], [75.7, 27.9]]],
            },
            "data_origin": "synthetic",
        },
    )
    aoi_id = created.json()["id"]

    class _FakeMacrostrat:
        async def get_geologic_units_at_point(self, **_kwargs):
            return [
                MacrostratMapUnit(
                    map_id=999001,
                    name="Alwar Quartzite",
                    lith="quartzite",
                    t_age=1600.0,
                    b_age=1800.0,
                )
            ]

    class _TimeoutMRDS:
        fetch_occurrences_bbox = AsyncMock(
            side_effect=ProviderTimeoutError("usgs_mrds", "Simulated timeout")
        )

    from app.ingestion.pipeline import IngestionPipeline

    def _mock_pipeline(db, _settings, _cache):
        return IngestionPipeline(
            db,
            macrostrat_adapter=_FakeMacrostrat(),  # type: ignore[arg-type]
            mrds_adapter=_TimeoutMRDS(),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(routes, "_build_ingestion_pipeline", _mock_pipeline)

    ingest_resp = client.post(
        f"/api/v1/ingestion/aois/{aoi_id}/run",
        json={"providers": ["macrostrat_v2", "usgs_mrds"]},
    )
    assert ingest_resp.status_code == 200
    results = {r["provider_key"]: r for r in ingest_resp.json()["results"]}
    assert results["macrostrat_v2"]["status"] == "completed"
    assert results["macrostrat_v2"]["records_written"] == 1
    assert results["usgs_mrds"]["status"] == "failed"
    assert "timeout" in results["usgs_mrds"]["error"].lower()

    geology = client.get(f"/api/v1/aois/{aoi_id}/geology")
    assert geology.status_code == 200
    assert geology.json()[0]["unit_name"] == "Alwar Quartzite"

    jobs = client.get("/api/v1/ingestion/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) >= 2

