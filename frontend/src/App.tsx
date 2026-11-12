import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";

interface HealthStatus {
  status: string;
  app_name: string;
  database_backend: string;
  postgis_enabled: boolean;
  cache_stats: Record<string, number>;
  scientific_disclaimer: string;
}

interface DataSourceInfo {
  id: string;
  provider_key: string;
  display_name: string;
  jurisdiction: string;
  label_authority: string;
  license: string;
  is_ml_training_allowed: boolean;
  last_health_status: string | null;
}

interface AOISummary {
  id: string;
  name: string;
  jurisdiction: string;
  processing_epsg: number;
  area_km2: number;
  data_origin: string;
  geometry: GeoJSON.Geometry;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export default function App() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sources, setSources] = useState<DataSourceInfo[]>([]);
  const [aois, setAois] = useState<AOISummary[]>([]);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadBackendState() {
      try {
        const [hRes, sRes, aRes] = await Promise.all([
          fetch(`${API_BASE}/health`, { signal: controller.signal }),
          fetch(`${API_BASE}/sources`, { signal: controller.signal }),
          fetch(`${API_BASE}/aois`, { signal: controller.signal }),
        ]);
        if (!hRes.ok || !sRes.ok || !aRes.ok) {
          throw new Error("Backend returned non-OK status");
        }
        const [hJson, sJson, aJson] = await Promise.all([
          hRes.json() as Promise<HealthStatus>,
          sRes.json() as Promise<DataSourceInfo[]>,
          aRes.json() as Promise<AOISummary[]>,
        ]);
        setHealth(hJson);
        setSources(sJson);
        setAois(aJson);
        setApiError(null);
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setApiError("FastAPI backend offline or unreachable on /api/v1.");
        }
      }
    }
    void loadBackendState();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm-basemap",
            type: "raster",
            source: "osm",
          },
        ],
      },
      center: [78.9629, 21.5937], // India-first default center
      zoom: 4.5,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("load", () => {
      if (aois.length === 0) return;
      map.addSource("aois", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: aois.map((aoi) => ({
            type: "Feature",
            geometry: aoi.geometry,
            properties: {
              id: aoi.id,
              name: aoi.name,
              jurisdiction: aoi.jurisdiction,
              area_km2: aoi.area_km2,
            },
          })),
        },
      });
      map.addLayer({
        id: "aois-fill",
        type: "fill",
        source: "aois",
        paint: {
          "fill-color": "#38bdf8",
          "fill-opacity": 0.22,
        },
      });
      map.addLayer({
        id: "aois-outline",
        type: "line",
        source: "aois",
        paint: {
          "line-color": "#38bdf8",
          "line-width": 2,
        },
      });
    });

    return () => {
      map.remove();
    };
  }, [aois]);

  return (
    <div className="layout">
      <header className="disclaimer-bar">
        <div>
          <strong>Scientific Notice:</strong>{" "}
          {health?.scientific_disclaimer ??
            "Phase 2 Geospatial Data Infrastructure. Prospectivity proxies do NOT establish proven mineral reserves."}
        </div>
        <span className="badge badge-warn">Phase 2 · SQLite Dev Mode</span>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <section className="card">
            <h2>Backend Infrastructure</h2>
            {apiError ? (
              <div className="meta-row">
                <span className="badge badge-danger">{apiError}</span>
              </div>
            ) : health ? (
              <>
                <div className="meta-row">
                  <span>API Status</span>
                  <span className="badge badge-ok">{health.status.toUpperCase()}</span>
                </div>
                <div className="meta-row">
                  <span>Database Backend</span>
                  <span>{health.database_backend}</span>
                </div>
                <div className="meta-row">
                  <span>PostGIS Active</span>
                  <span>{health.postgis_enabled ? "Yes" : "No (Deferred)"}</span>
                </div>
                <div className="meta-row">
                  <span>In-Memory Cache Entries</span>
                  <span>{health.cache_stats.entries ?? 0}</span>
                </div>
              </>
            ) : (
              <div className="meta-row">Checking FastAPI status...</div>
            )}
          </section>

          <section className="card">
            <h2>Configured AOIs ({aois.length})</h2>
            {aois.length === 0 ? (
              <div className="meta-row">
                No AOIs stored yet. Create one via POST /api/v1/aois.
              </div>
            ) : (
              aois.map((aoi) => (
                <div key={aoi.id} className="source-item">
                  <div className="source-title">{aoi.name}</div>
                  <div className="meta-row">
                    <span>
                      {aoi.jurisdiction} · EPSG:{aoi.processing_epsg}
                    </span>
                    <span>{aoi.area_km2.toFixed(1)} km²</span>
                  </div>
                </div>
              ))
            )}
          </section>

          <section className="card">
            <h2>Data Sources &amp; ML Licensing ({sources.length})</h2>
            {sources.map((src) => (
              <div key={src.id} className="source-item">
                <div className="source-title">{src.display_name}</div>
                <div className="meta-row">
                  <span>Authority: {src.label_authority}</span>
                  <span
                    className={`badge ${
                      src.is_ml_training_allowed ? "badge-ok" : "badge-danger"
                    }`}
                  >
                    {src.is_ml_training_allowed ? "ML Allowed" : "ML Blocked"}
                  </span>
                </div>
                <div className="meta-row">
                  <span>{src.license}</span>
                </div>
              </div>
            ))}
          </section>
        </aside>

        <section className="map-container" aria-label="Geospatial Map Workspace">
          <div ref={mapContainerRef} className="map-canvas" />
        </section>
      </main>
    </div>
  );
}

