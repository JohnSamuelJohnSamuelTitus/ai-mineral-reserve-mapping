import type {
  AOICoverageSummary,
  AOIItem,
  DatasetQualityReportItem,
  DataSourceItem,
  FeatureManifestItem,
  FeatureOverlayDescriptor,
  GeoJSONPolygon,
  GeologicalUnitItem,
  GIBSLayerItem,
  HealthStatus,
  MineralOccurrenceItem,
  MLDatasetVersionItem,
  ProcessingJobItem,
  RasterAssetItem,
  STACSceneItem,
} from '../types/gis';

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') {
        detail = body.detail;
      } else if (Array.isArray(body?.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg || 'Validation error').join('; ');
      }
    } catch {
      // Fallback to HTTP status message
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const apiClient = {
  getHealth: () => apiJson<HealthStatus>('/api/v1/health'),
  listSources: () => apiJson<DataSourceItem[]>('/api/v1/sources'),
  listAois: () => apiJson<AOIItem[]>('/api/v1/aois'),
  createAoi: (payload: {
    name: string;
    description?: string;
    jurisdiction?: string;
    commodity_focus?: string[];
    geometry: GeoJSONPolygon;
  }) =>
    apiJson<AOIItem>('/api/v1/aois', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateAoi: (
    aoiId: string,
    payload: {
      name?: string;
      description?: string;
      commodity_focus?: string[];
      geometry?: GeoJSONPolygon;
    }
  ) =>
    apiJson<AOIItem>(`/api/v1/aois/${aoiId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  deleteAoi: (aoiId: string) =>
    apiJson<void>(`/api/v1/aois/${aoiId}`, { method: 'DELETE' }),

  listOccurrences: (aoiId: string) =>
    apiJson<MineralOccurrenceItem[]>(`/api/v1/aois/${aoiId}/occurrences`),
  listGeology: (aoiId: string) =>
    apiJson<GeologicalUnitItem[]>(`/api/v1/aois/${aoiId}/geology`),
  listRasters: (aoiId: string) =>
    apiJson<RasterAssetItem[]>(`/api/v1/aois/${aoiId}/rasters`),

  runIngestion: (
    aoiId: string,
    providers: ('usgs_mrds' | 'macrostrat_v2' | 'sentinel2_stac')[] = ['macrostrat_v2', 'usgs_mrds']
  ) =>
    apiJson<{ aoi_id: string; results: Record<string, unknown>[] }>(`/api/v1/aois/${aoiId}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ providers }),
    }),

  importGeologicalFile: (
    aoiId: string,
    file: File,
    sourceProviderKey: string,
    inputEpsg: number = 4326
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('source_provider_key', sourceProviderKey);
    form.append('data_origin', 'real');
    form.append('input_epsg', String(inputEpsg));
    form.append('clip_to_aoi', 'true');
    return apiJson<DatasetQualityReportItem>(`/api/v1/geology/aois/${aoiId}/import`, {
      method: 'POST',
      body: form,
    });
  },
  listQualityReports: (aoiId: string) =>
    apiJson<DatasetQualityReportItem[]>(`/api/v1/geology/aois/${aoiId}/quality-reports`),

  geocodePlace: (q: string) =>
    apiJson<{ display_name: string; lat: number; lon: number; bbox?: number[] }[]>(
      `/api/v1/search/geocode?q=${encodeURIComponent(q)}`
    ),

  listGibsLayers: () => apiJson<GIBSLayerItem[]>('/api/v1/satellite/gibs-layers'),
  searchSatellite: (payload: {
    aoi_id: string;
    provider: 'mpc_stac' | 'earth_search_stac' | 'nasa_cmr_stac';
    collections: string[];
    max_cloud_cover?: number | null;
    limit?: number;
    save_metadata?: boolean;
  }) =>
    apiJson<{
      aoi_id: string;
      provider: string;
      scene_count: number;
      saved_count: number;
      scenes: STACSceneItem[];
    }>('/api/v1/satellite/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  downloadRasterAsset: (assetId: string, aoiId: string, bandKey?: string) => {
    const params = new URLSearchParams({ aoi_id: aoiId, run_sync: 'true' });
    if (bandKey) params.set('band_key', bandKey);
    return apiJson<ProcessingJobItem>(`/api/v1/satellite/assets/${assetId}/download?${params.toString()}`, {
      method: 'POST',
    });
  },

  extractFeatures: (
    aoiId: string,
    payload: { resolution_m: number; dem_asset_id?: string | null; include_geology: boolean; run_sync: boolean }
  ) =>
    apiJson<ProcessingJobItem>(`/api/v1/features/aois/${aoiId}/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  listManifests: (aoiId: string) =>
    apiJson<FeatureManifestItem[]>(`/api/v1/features/aois/${aoiId}/manifests`),
  getFeatureOverlay: (manifestId: string, featureName: string) =>
    apiJson<FeatureOverlayDescriptor>(
      `/api/v1/features/manifests/${manifestId}/overlay.json?feature_name=${encodeURIComponent(featureName)}`
    ),
  getAoiCoverage: (aoiId: string) =>
    apiJson<AOICoverageSummary>(`/api/v1/features/aois/${aoiId}/coverage`),

  listMLDatasets: (aoiId: string) =>
    apiJson<MLDatasetVersionItem[]>(`/api/v1/ml/aois/${aoiId}/datasets`),
  buildMLDataset: (
    aoiId: string,
    payload: {
      manifest_id?: string | null;
      version_tag?: string;
      block_size_m?: number;
      seed?: number;
      include_dist_to_occurrence?: boolean;
    }
  ) =>
    apiJson<MLDatasetVersionItem>(`/api/v1/ml/aois/${aoiId}/datasets/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  evaluateMLBaseline: (datasetId: string) =>
    apiJson<MLDatasetVersionItem>(`/api/v1/ml/datasets/${datasetId}/evaluate`, {
      method: 'POST',
    }),
};

