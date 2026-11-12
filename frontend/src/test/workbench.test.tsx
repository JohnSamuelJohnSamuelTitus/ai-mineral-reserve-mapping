import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  geoJSONPolygonToVertices,
  validateOpenPolygonVertices,
  verticesToGeoJSONPolygon,
} from '../components/map/polygonGeometry';
import { App } from '../App';

vi.mock('maplibre-gl', () => {
  class MockMap {
    on = vi.fn();
    addControl = vi.fn();
    remove = vi.fn();
    setStyle = vi.fn();
    isStyleLoaded = vi.fn(() => true);
    getSource = vi.fn(() => undefined);
    addSource = vi.fn();
    getLayer = vi.fn(() => undefined);
    addLayer = vi.fn();
    removeLayer = vi.fn();
    removeSource = vi.fn();
    setLayoutProperty = vi.fn();
    setPaintProperty = vi.fn();
    moveLayer = vi.fn();
    getCanvas = vi.fn(() => ({ style: { cursor: '' } }));
    fitBounds = vi.fn();
    flyTo = vi.fn();
    getZoom = vi.fn(() => 10.5);
    dragPan = { disable: vi.fn(), enable: vi.fn() };
  }
  return {
    default: {
      Map: MockMap,
      NavigationControl: vi.fn(),
      ScaleControl: vi.fn(),
    },
  };
});

describe('polygonGeometry utilities', () => {
  it('validates rectangles and rejects self-intersecting bowties', () => {
    const validRect: [number, number][] = [
      [75.77, 27.98],
      [75.81, 27.98],
      [75.81, 28.02],
      [75.77, 28.02],
    ];
    const ok = validateOpenPolygonVertices(validRect);
    expect(ok.valid).toBe(true);
    expect(ok.estimatedAreaKm2).toBeGreaterThan(10);

    const closed = verticesToGeoJSONPolygon(validRect);
    expect(closed.coordinates[0]).toHaveLength(5);
    expect(geoJSONPolygonToVertices(closed)).toHaveLength(4);

    const bowtie: [number, number][] = [
      [75.77, 27.98],
      [75.81, 28.02],
      [75.81, 27.98],
      [75.77, 28.02],
    ];
    const bad = validateOpenPolygonVertices(bowtie);
    expect(bad.valid).toBe(false);
    expect(bad.reason).toMatch(/self-intersect/i);
  });
});

function mockWorkbenchFetch() {
  const sampleAoi = {
    id: 'aoi-khetri-1',
    name: 'Khetri Test AOI',
    description: 'Copper belt',
    jurisdiction: 'IN',
    commodity_focus: ['Cu'],
    deposit_model: null,
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [75.77, 27.98],
          [75.81, 27.98],
          [75.81, 28.02],
          [75.77, 28.02],
          [75.77, 27.98],
        ],
      ],
    },
    bbox: [75.77, 27.98, 75.81, 28.02],
    centroid: [75.79, 28.0],
    processing_epsg: 32643,
    area_km2: 17.4,
    data_origin: 'real',
    created_at: '2026-01-01T00:00:00Z',
  };

  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const ok = (data: unknown) =>
      new Response(JSON.stringify(data), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });

    if (url.endsWith('/api/v1/health')) {
      return ok({
        status: 'ok',
        app_name: 'ai-mineral-prospectivity-assistant',
        database_backend: 'sqlite',
        postgis_enabled: false,
        cache_stats: { entries: 0 },
        scientific_disclaimer: 'Prospectivity != reserves',
      });
    }
    if (url.endsWith('/api/v1/sources')) {
      return ok([
        {
          id: 'src-1',
          provider_key: 'ngdr_geodataindia',
          display_name: 'GSI NGDR',
          jurisdiction: 'IN',
          label_authority: 'national_gsi_ngdr',
          base_url: 'https://ngdr.gsi.gov.in',
          license: 'Govt Open Data',
          attribution_text: 'GSI',
          is_ml_training_allowed: true,
          is_enabled: true,
          last_health_status: 'ok',
          notes: null,
        },
      ]);
    }
    if (url.endsWith('/api/v1/aois')) {
      return ok([sampleAoi]);
    }
    if (url.includes('/gibs-layers')) return ok([]);
    if (url.includes('/occurrences')) return ok([]);
    if (url.includes('/geology') && !url.includes('/quality-reports')) return ok([]);
    if (url.includes('/rasters')) return ok([]);
    if (url.includes('/quality-reports')) return ok([]);
    if (url.includes('/manifests') && !url.includes('/overlay.json')) {
      return ok([
        {
          id: 'man-1',
          aoi_id: 'aoi-khetri-1',
          target_crs_epsg: 32643,
          resolution_m: 100,
          grid_rows: 45,
          grid_cols: 40,
          nodata_value: -9999,
          status: 'completed',
          input_datasets_json: [],
          input_scene_ids: [],
          feature_names: ['elevation_m', 'slope_deg'],
          output_files_json: {},
          warnings_json: ['Missing structural fault layer'],
          manifest_json: {
            feature_stats: {
              elevation_m: { valid_pixels: 858, total_pixels: 1800, valid_pct: 47.67, min: 378.7, max: 546.8, mean: 426.9, std: 29.5 },
              slope_deg: { valid_pixels: 858, total_pixels: 1800, valid_pct: 47.67, min: 0.16, max: 24.39, mean: 5.89, std: 4.15 },
            },
          },
          data_origin: 'real',
          created_at: '2026-01-01T00:00:00Z',
        },
      ]);
    }
    if (url.includes('/overlay.json')) {
      return ok({
        manifest_id: 'man-1',
        feature_name: 'slope_deg',
        min: 0.16,
        max: 24.39,
        mean: 5.89,
        valid_pct: 47.67,
        nodata_value: -9999,
        wgs84_corners: [[75.77, 28.02], [75.81, 28.02], [75.81, 27.98], [75.77, 27.98]],
        image_url: '/api/v1/features/manifests/man-1/overlay.png?feature_name=slope_deg',
      });
    }
    if (url.includes('/coverage')) {
      return ok({
        aoi_id: 'aoi-khetri-1',
        aoi_name: 'Khetri Test AOI',
        processing_epsg: 32643,
        area_km2: 17.4,
        occurrence_total: 4,
        occurrence_ml_trainable: 3,
        occurrence_reference_only: 1,
        quarantined_count: 2,
        quality_reports_count: 1,
        geological_units_count: 5,
        raster_scenes_discovered: 2,
        raster_scenes_downloaded: 1,
        feature_manifests_count: 1,
        latest_manifest_id: 'man-1',
        missing_layers: ['Verified structural fault lines'],
        warnings: ['Absence of recorded mineral occurrences does NOT prove an area is mineral-free.'],
      });
    }
    if (url.includes('/ml/aois/')) {
      return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 });
    }
    return ok({});
  });
}

describe('GIS Workbench App', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders active AOI, coverage metrics, layers, and feature stats table', async () => {
    vi.stubGlobal('fetch', mockWorkbenchFetch());
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('active-aoi-badge')).toHaveTextContent('Khetri Test AOI');
    });

    const metrics = screen.getByTestId('coverage-metrics');
    expect(metrics).toHaveTextContent('3');
    expect(metrics).toHaveTextContent('ML-Trainable Occ');
    expect(screen.getByText(/Missing: Verified structural fault lines/i)).toBeInTheDocument();

    // Switch right tab to Features & ML
    fireEvent.click(screen.getByRole('tab', { name: /Features & ML/i }));
    expect(await screen.findByText('slope_deg')).toBeInTheDocument();
    expect(screen.getByTestId('ml-unavailable')).toBeInTheDocument();

    // Switch left tab to Layers and enter Draw mode on AOI tab
    fireEvent.click(screen.getByRole('tab', { name: /Layers/i }));
    expect(screen.getByText('Mineral Occurrences (Authority)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /AOI & Data/i }));
    fireEvent.click(screen.getByTestId('draw-aoi-btn'));
    expect(screen.getByText(/Draw AOI Mode/i)).toBeInTheDocument();
  });

  it('displays error banner with retry when backend is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('Backend offline');
      })
    );
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Backend offline');
    expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
  });
});

