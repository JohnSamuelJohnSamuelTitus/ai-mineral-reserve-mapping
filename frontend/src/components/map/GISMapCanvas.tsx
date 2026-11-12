import React, { useEffect, useRef, useState } from 'react';
import maplibregl, {
  type GeoJSONSource,
  type ImageSource,
  type Map as MapLibreMap,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type {
  AOIItem,
  BasemapId,
  FeatureOverlayDescriptor,
  GeologicalUnitItem,
  GIBSLayerItem,
  GISLayerConfig,
  InspectorSelection,
  LayerKey,
  MineralOccurrenceItem,
  RasterAssetItem,
} from '../../types/gis';
import { verticesToGeoJSONPolygon } from './polygonGeometry';

interface GISMapCanvasProps {
  aois: AOIItem[];
  activeAoi: AOIItem | null;
  occurrences: MineralOccurrenceItem[];
  geologyUnits: GeologicalUnitItem[];
  rasters: RasterAssetItem[];
  overlay: FeatureOverlayDescriptor | null;
  basemap: BasemapId;
  gibsLayer: GIBSLayerItem | null;
  layers: GISLayerConfig[];
  interactionMode: 'inspect' | 'draw' | 'edit';
  draftVertices: [number, number][];
  onDraftVerticesChange: (next: [number, number][]) => void;
  onSelectFeature: (sel: InspectorSelection) => void;
  flyToTarget: { lon: number; lat: number; zoom?: number; bbox?: number[] } | null;
}

const DEFAULT_GIBS_TEMPLATE =
  'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/2024-01-15/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg';

function buildBasemapStyle(basemap: BasemapId, gibsLayer: GIBSLayerItem | null): StyleSpecification {
  if (basemap === 'offline_grid') {
    return {
      version: 8,
      name: 'Offline Slate Grid',
      sources: {},
      layers: [
        {
          id: 'bg',
          type: 'background',
          paint: { 'background-color': '#0b1220' },
        },
      ],
    };
  }

  let tiles: string[];
  let attribution: string;
  let maxzoom = 19;

  if (basemap === 'esri_imagery') {
    tiles = ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'];
    attribution = 'Tiles © Esri — World Imagery';
    maxzoom = 18;
  } else if (basemap === 'opentopo') {
    tiles = ['https://tile.opentopomap.org/{z}/{x}/{y}.png'];
    attribution = '© OpenStreetMap contributors, SRTM © OpenTopoMap';
    maxzoom = 17;
  } else if (basemap === 'nasa_gibs') {
    tiles = [gibsLayer?.tile_url_template || DEFAULT_GIBS_TEMPLATE];
    attribution = gibsLayer?.attribution || 'NASA EOSDIS GIBS (Visualization Only)';
    maxzoom = 9;
  } else {
    tiles = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'];
    attribution = '© OpenStreetMap contributors';
  }

  return {
    version: 8,
    name: basemap,
    sources: {
      basemap_raster: {
        type: 'raster',
        tiles,
        tileSize: 256,
        maxzoom,
        attribution,
      },
    },
    layers: [
      {
        id: 'basemap_layer',
        type: 'raster',
        source: 'basemap_raster',
      },
    ],
  };
}

const LAYER_MAPLIBRE_IDS: Record<LayerKey, string[]> = {
  geology_units: ['geology-fill', 'geology-line'],
  feature_overlay: ['feature-overlay-layer'],
  raster_footprints: ['rasters-line'],
  aoi_boundary: ['aois-all-fill', 'aois-all-line', 'aoi-active-fill', 'aoi-active-line'],
  mineral_occurrences: ['occurrences-circle'],
};

export const GISMapCanvas: React.FC<GISMapCanvasProps> = ({
  aois,
  activeAoi,
  occurrences,
  geologyUnits,
  rasters,
  overlay,
  basemap,
  gibsLayer,
  layers,
  interactionMode,
  draftVertices,
  onDraftVerticesChange,
  onSelectFeature,
  flyToTarget,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [webglError, setWebglError] = useState<string | null>(null);
  const [cursorCoords, setCursorCoords] = useState<{ lon: number; lat: number; zoom: number }>({
    lon: 75.79,
    lat: 28.0,
    zoom: 11,
  });

  // Mutable refs for event handlers so listeners never read stale state
  const modeRef = useRef(interactionMode);
  modeRef.current = interactionMode;
  const draftRef = useRef(draftVertices);
  draftRef.current = draftVertices;
  const onDraftChangeRef = useRef(onDraftVerticesChange);
  onDraftChangeRef.current = onDraftVerticesChange;
  const onSelectRef = useRef(onSelectFeature);
  onSelectRef.current = onSelectFeature;
  const dataRef = useRef({
    aois,
    activeAoi,
    occurrences,
    geologyUnits,
    rasters,
    overlay,
    layers,
    draftVertices,
    interactionMode,
  });
  dataRef.current = {
    aois,
    activeAoi,
    occurrences,
    geologyUnits,
    rasters,
    overlay,
    layers,
    draftVertices,
    interactionMode,
  };
  const draggingIdxRef = useRef<number | null>(null);

  const syncMapSourcesAndLayers = (map: MapLibreMap) => {
    const state = dataRef.current;

    const ensureGeoJson = (id: string, data: GeoJSON.GeoJSON) => {
      const existing = map.getSource(id) as GeoJSONSource | undefined;
      if (existing) {
        existing.setData(data);
      } else {
        map.addSource(id, { type: 'geojson', data });
      }
    };

    // 1. Geological Units
    const geoFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: state.geologyUnits
        .filter((u) => u.geometry && Object.keys(u.geometry).length > 0)
        .map((u) => ({
          type: 'Feature',
          properties: {
            id: u.id,
            unit_name: u.unit_name,
            lithology_primary: (u.lithology_class[0] || 'other').toLowerCase(),
          },
          geometry: u.geometry as unknown as GeoJSON.Geometry,
        })),
    };
    ensureGeoJson('geology-src', geoFc);
    if (!map.getLayer('geology-fill')) {
      map.addLayer({
        id: 'geology-fill',
        type: 'fill',
        source: 'geology-src',
        paint: {
          'fill-color': [
            'match',
            ['get', 'lithology_primary'],
            'granitoid',
            '#e11d48',
            'mafic',
            '#0284c7',
            'ultramafic',
            '#7c3aed',
            'carbonate',
            '#eab308',
            'metasediment',
            '#14b8a6',
            '#64748b',
          ],
          'fill-opacity': 0.35,
        },
      });
      map.addLayer({
        id: 'geology-line',
        type: 'line',
        source: 'geology-src',
        paint: { 'line-color': '#cbd5e1', 'line-width': 1, 'line-opacity': 0.7 },
      });
    }

    // 2. Raster Image Overlay
    const prevOverlaySrc = map.getSource('feature-overlay-src') as ImageSource | undefined;
    if (state.overlay && state.overlay.wgs84_corners.length === 4) {
      const corners = state.overlay.wgs84_corners as [
        [number, number],
        [number, number],
        [number, number],
        [number, number],
      ];
      if (prevOverlaySrc) {
        prevOverlaySrc.updateImage({ url: state.overlay.image_url, coordinates: corners });
      } else {
        map.addSource('feature-overlay-src', {
          type: 'image',
          url: state.overlay.image_url,
          coordinates: corners,
        });
      }
      if (!map.getLayer('feature-overlay-layer')) {
        map.addLayer({
          id: 'feature-overlay-layer',
          type: 'raster',
          source: 'feature-overlay-src',
          paint: { 'raster-opacity': 0.8, 'raster-fade-duration': 0 },
        });
      }
    } else {
      if (map.getLayer('feature-overlay-layer')) map.removeLayer('feature-overlay-layer');
      if (prevOverlaySrc) map.removeSource('feature-overlay-src');
    }

    // 3. Satellite Footprints
    const rasterFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: state.rasters
        .filter((r) => r.bbox && r.bbox.length === 4)
        .map((r) => {
          const [minLon, minLat, maxLon, maxLat] = r.bbox;
          return {
            type: 'Feature',
            properties: { id: r.id, item_id: r.stac_item_id, status: r.download_status },
            geometry: {
              type: 'Polygon',
              coordinates: [
                [
                  [minLon, minLat],
                  [maxLon, minLat],
                  [maxLon, maxLat],
                  [minLon, maxLat],
                  [minLon, minLat],
                ],
              ],
            },
          };
        }),
    };
    ensureGeoJson('rasters-src', rasterFc);
    if (!map.getLayer('rasters-line')) {
      map.addLayer({
        id: 'rasters-line',
        type: 'line',
        source: 'rasters-src',
        paint: {
          'line-color': '#22d3ee',
          'line-width': 1.5,
          'line-dasharray': [3, 2],
        },
      });
    }

    // 4. Saved AOIs & Active AOI
    const allAoisFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: state.aois.map((a) => ({
        type: 'Feature',
        properties: { id: a.id, name: a.name },
        geometry: a.geometry,
      })),
    };
    ensureGeoJson('aois-all-src', allAoisFc);
    if (!map.getLayer('aois-all-fill')) {
      map.addLayer({
        id: 'aois-all-fill',
        type: 'fill',
        source: 'aois-all-src',
        paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.08 },
      });
      map.addLayer({
        id: 'aois-all-line',
        type: 'line',
        source: 'aois-all-src',
        paint: { 'line-color': '#7dd3fc', 'line-width': 1.4, 'line-opacity': 0.7 },
      });
    }

    const activeFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: state.activeAoi
        ? [
            {
              type: 'Feature',
              properties: { id: state.activeAoi.id, name: state.activeAoi.name },
              geometry: state.activeAoi.geometry,
            },
          ]
        : [],
    };
    ensureGeoJson('aoi-active-src', activeFc);
    if (!map.getLayer('aoi-active-fill')) {
      map.addLayer({
        id: 'aoi-active-fill',
        type: 'fill',
        source: 'aoi-active-src',
        paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.09 },
      });
      map.addLayer({
        id: 'aoi-active-line',
        type: 'line',
        source: 'aoi-active-src',
        paint: { 'line-color': '#fbbf24', 'line-width': 2.5 },
      });
    }

    // 5. Mineral Occurrences (Authority color-coded)
    const occFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: state.occurrences.map((o) => ({
        type: 'Feature',
        properties: {
          id: o.id,
          name: o.name,
          commodity: o.commodity_primary || 'N/A',
          authority: o.label_authority,
        },
        geometry: { type: 'Point', coordinates: [o.lon, o.lat] },
      })),
    };
    ensureGeoJson('occurrences-src', occFc);
    if (!map.getLayer('occurrences-circle')) {
      map.addLayer({
        id: 'occurrences-circle',
        type: 'circle',
        source: 'occurrences-src',
        paint: {
          'circle-radius': 6,
          'circle-stroke-width': 1.6,
          'circle-stroke-color': '#0f172a',
          'circle-color': [
            'match',
            ['get', 'authority'],
            'national_gsi_ngdr',
            '#10b981',
            'international_supplement',
            '#f59e0b',
            'reference_only',
            '#ef4444',
            '#38bdf8',
          ],
        },
      });
    }

    // 6. Interactive Draw / Edit Draft Overlay (always topmost)
    const activeDraft = state.interactionMode !== 'inspect' ? state.draftVertices : [];
    const draftPolyFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features:
        activeDraft.length >= 3
          ? [
              {
                type: 'Feature',
                properties: {},
                geometry: verticesToGeoJSONPolygon(activeDraft),
              },
            ]
          : activeDraft.length === 2
            ? [
                {
                  type: 'Feature',
                  properties: {},
                  geometry: { type: 'LineString', coordinates: activeDraft },
                },
              ]
            : [],
    };
    ensureGeoJson('draft-poly-src', draftPolyFc);
    if (!map.getLayer('draft-poly-fill')) {
      map.addLayer({
        id: 'draft-poly-fill',
        type: 'fill',
        source: 'draft-poly-src',
        paint: { 'fill-color': '#34d399', 'fill-opacity': 0.2 },
      });
      map.addLayer({
        id: 'draft-poly-line',
        type: 'line',
        source: 'draft-poly-src',
        paint: { 'line-color': '#34d399', 'line-width': 2.2, 'line-dasharray': [2, 2] },
      });
    }

    const draftVertsFc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: activeDraft.map(([lon, lat], idx) => ({
        type: 'Feature',
        properties: { index: idx },
        geometry: { type: 'Point', coordinates: [lon, lat] },
      })),
    };
    ensureGeoJson('draft-verts-src', draftVertsFc);
    if (!map.getLayer('draft-verts-circle')) {
      map.addLayer({
        id: 'draft-verts-circle',
        type: 'circle',
        source: 'draft-verts-src',
        paint: {
          'circle-radius': 6.5,
          'circle-color': '#10b981',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      });
    }

    // Apply layer visibility, opacity, and z-order (layers[0] = top-most in UI)
    const bottomToTop = [...state.layers].reverse();
    for (const cfg of bottomToTop) {
      const ids = LAYER_MAPLIBRE_IDS[cfg.key] || [];
      for (const lid of ids) {
        if (!map.getLayer(lid)) continue;
        map.setLayoutProperty(lid, 'visibility', cfg.visible ? 'visible' : 'none');
        if (lid === 'feature-overlay-layer') {
          map.setPaintProperty(lid, 'raster-opacity', cfg.opacity);
        } else if (lid === 'geology-fill') {
          map.setPaintProperty(lid, 'fill-opacity', Math.min(0.85, cfg.opacity * 0.55));
        }
        map.moveLayer(lid);
      }
    }
    for (const draftLid of ['draft-poly-fill', 'draft-poly-line', 'draft-verts-circle']) {
      if (map.getLayer(draftLid)) map.moveLayer(draftLid);
    }
  };

  // Initialize MapLibre once
  useEffect(() => {
    const el = containerRef.current;
    if (!el || mapRef.current) return;

    try {
      const map = new maplibregl.Map({
        container: el,
        style: buildBasemapStyle(basemap, gibsLayer),
        center: [75.79, 28.0],
        zoom: 10.5,
        attributionControl: { compact: true },
      });

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');

      map.on('style.load', () => {
        setMapReady(true);
        syncMapSourcesAndLayers(map);
      });

      map.on('mousemove', (e: MapLayerMouseEvent) => {
        setCursorCoords({
          lon: Number(e.lngLat.lng.toFixed(5)),
          lat: Number(e.lngLat.lat.toFixed(5)),
          zoom: Number(map.getZoom().toFixed(2)),
        });
        if (modeRef.current === 'edit' && draggingIdxRef.current !== null) {
          const next = [...draftRef.current];
          next[draggingIdxRef.current] = [e.lngLat.lng, e.lngLat.lat];
          onDraftChangeRef.current(next);
        }
      });

      map.on('mousedown', 'draft-verts-circle', (e: MapLayerMouseEvent) => {
        if (modeRef.current !== 'edit') return;
        const feat = e.features?.[0];
        const idx = feat?.properties?.index;
        if (typeof idx === 'number') {
          e.preventDefault();
          draggingIdxRef.current = idx;
          map.dragPan.disable();
        }
      });

      map.on('mouseup', () => {
        if (draggingIdxRef.current !== null) {
          draggingIdxRef.current = null;
          map.dragPan.enable();
        }
      });

      map.on('contextmenu', 'draft-verts-circle', (e: MapLayerMouseEvent) => {
        if (modeRef.current !== 'edit' && modeRef.current !== 'draw') return;
        const idx = e.features?.[0]?.properties?.index;
        if (typeof idx === 'number' && draftRef.current.length > 3) {
          e.preventDefault();
          const next = draftRef.current.filter((_, i) => i !== idx);
          onDraftChangeRef.current(next);
        }
      });

      map.on('click', (e: MapLayerMouseEvent) => {
        if (modeRef.current === 'draw') {
          onDraftChangeRef.current([...draftRef.current, [e.lngLat.lng, e.lngLat.lat]]);
          return;
        }
        if (modeRef.current === 'edit') {
          return;
        }
        const state = dataRef.current;
        const inspectLayers = ['occurrences-circle', 'geology-fill', 'aois-all-fill'].filter((lid) =>
          Boolean(map.getLayer(lid))
        );
        if (inspectLayers.length === 0) return;
        const hits = map.queryRenderedFeatures(e.point, { layers: inspectLayers });
        const top = hits[0];
        if (!top) {
          onSelectRef.current(null);
          return;
        }
        const hitId = String(top.properties?.id || '');
        if (top.layer.id === 'occurrences-circle') {
          const found = state.occurrences.find((o) => o.id === hitId);
          if (found) onSelectRef.current({ kind: 'occurrence', data: found });
        } else if (top.layer.id === 'geology-fill') {
          const found = state.geologyUnits.find((g) => g.id === hitId);
          if (found) onSelectRef.current({ kind: 'geology', data: found });
        } else if (top.layer.id === 'aois-all-fill') {
          const found = state.aois.find((a) => a.id === hitId);
          if (found) onSelectRef.current({ kind: 'aoi', data: found });
        }
      });

      mapRef.current = map;
      return () => {
        map.remove();
        mapRef.current = null;
      };
    } catch (err) {
      setWebglError(err instanceof Error ? err.message : 'MapLibre WebGL context unavailable');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-apply style when basemap switches
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(buildBasemapStyle(basemap, gibsLayer));
  }, [basemap, gibsLayer]);

  // Sync dynamic vector/raster sources & z-order whenever data changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.isStyleLoaded()) return;
    syncMapSourcesAndLayers(map);
  }, [mapReady, aois, activeAoi, occurrences, geologyUnits, rasters, overlay, layers, draftVertices, interactionMode]);

  // Cursor hint per mode
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor =
      interactionMode === 'draw' ? 'crosshair' : interactionMode === 'edit' ? 'grab' : '';
  }, [interactionMode]);

  // Fly to AOI or search target
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyToTarget) return;
    if (flyToTarget.bbox && flyToTarget.bbox.length === 4) {
      map.fitBounds(
        [
          [flyToTarget.bbox[0], flyToTarget.bbox[1]],
          [flyToTarget.bbox[2], flyToTarget.bbox[3]],
        ],
        { padding: 56, duration: 750, maxZoom: 13 }
      );
    } else {
      map.flyTo({
        center: [flyToTarget.lon, flyToTarget.lat],
        zoom: flyToTarget.zoom ?? 11,
        duration: 750,
      });
    }
  }, [flyToTarget]);

  const handleFitActive = () => {
    if (!mapRef.current || !activeAoi) return;
    mapRef.current.fitBounds(
      [
        [activeAoi.bbox[0], activeAoi.bbox[1]],
        [activeAoi.bbox[2], activeAoi.bbox[3]],
      ],
      { padding: 56, duration: 500, maxZoom: 13 }
    );
  };

  return (
    <div className="gis-map-wrapper" data-testid="gis-map-wrapper">
      {webglError ? (
        <div className="map-fallback-banner" role="status">
          <strong>2D Map Fallback Active</strong>
          <p>{webglError}</p>
          <p className="muted-text">
            Active AOIs: {aois.length} | Occurrences: {occurrences.length} | Geology Units: {geologyUnits.length}
          </p>
        </div>
      ) : (
        <div ref={containerRef} className="gis-map-container" data-testid="gis-map-canvas" />
      )}

      {/* Interactive Mode Floating Prompt */}
      {interactionMode !== 'inspect' && (
        <div className="map-mode-banner" role="status">
          {interactionMode === 'draw'
            ? `Draw AOI Mode (${draftVertices.length} vertices): click map to place vertices, right-click vertex to remove.`
            : `Edit AOI Mode (${draftVertices.length} vertices): drag white/green vertices to reshape, right-click vertex to delete.`}
        </div>
      )}

      {/* NASA GIBS Visual Caution Badge */}
      {basemap === 'nasa_gibs' && (
        <div className="gibs-warning-pill" role="note">
          NASA GIBS RGB Visualization Only — NOT quantitative surface reflectance or ML training input
        </div>
      )}

      {/* Coordinate & CRS Status Pill */}
      <div className="map-hud-bottom-right">
        {activeAoi && (
          <button type="button" className="btn-xs" onClick={handleFitActive} title="Zoom map to active AOI">
            Fit AOI Extent
          </button>
        )}
        <span className="coord-pill" data-testid="cursor-readout">
          Lon {cursorCoords.lon.toFixed(5)}° · Lat {cursorCoords.lat.toFixed(5)}° · Z {cursorCoords.zoom}
          {activeAoi ? ` · EPSG:${activeAoi.processing_epsg}` : ' · EPSG:4326'}
        </span>
      </div>
    </div>
  );
};

