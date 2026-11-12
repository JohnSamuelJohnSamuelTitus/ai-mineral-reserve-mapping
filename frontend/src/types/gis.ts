export type GeoJSONPolygon = {
  type: 'Polygon';
  coordinates: number[][][];
};

export interface HealthStatus {
  status: string;
  app_name: string;
  database_backend: string;
  postgis_enabled: boolean;
  cache_stats: Record<string, number>;
  scientific_disclaimer: string;
}

export interface AOIItem {
  id: string;
  name: string;
  description: string | null;
  jurisdiction: string;
  commodity_focus: string[];
  deposit_model: string | null;
  geometry: GeoJSONPolygon;
  bbox: [number, number, number, number];
  centroid: [number, number];
  processing_epsg: number;
  area_km2: number;
  data_origin: string;
  created_at: string;
}

export interface DataSourceItem {
  id: string;
  provider_key: string;
  display_name: string;
  jurisdiction: string;
  label_authority: string;
  base_url: string;
  license: string;
  attribution_text: string;
  is_ml_training_allowed: boolean;
  is_enabled: boolean;
  last_health_status: string | null;
  notes: string | null;
}

export interface MineralOccurrenceItem {
  id: string;
  source_id: string;
  external_id: string;
  name: string;
  commodity_primary: string | null;
  commodities_all: string[];
  occurrence_type: string | null;
  deposit_type: string | null;
  jurisdiction: string;
  label_authority: string;
  data_origin: string;
  lon: number;
  lat: number;
  collected_at: string;
}

export interface GeologicalUnitItem {
  id: string;
  external_map_id: string;
  unit_name: string;
  strat_name: string | null;
  lithology_raw: string | null;
  lithology_class: string[];
  age_min_ma: number | null;
  age_max_ma: number | null;
  period_name: string | null;
  geometry: Record<string, unknown>;
  data_origin: string;
  collected_at: string;
}

export interface DownloadedBandInfo {
  local_path: string;
  checksum_sha256: string;
  crs_epsg: number | null;
  width: number;
  height: number;
  band_count?: number;
  size_mb: number;
  dtype?: string | null;
  native_resolution?: number[] | null;
  nodata?: number | null;
  band_descriptions?: string[];
  source_asset_key?: string;
}

export interface RasterAssetItem {
  id: string;
  stac_collection: string | null;
  stac_item_id: string;
  asset_type: string;
  platform: string | null;
  product_type: string | null;
  acquired_at: string | null;
  cloud_cover_pct: number | null;
  resolution_m: number | null;
  bbox: number[];
  storage_uri: string;
  local_path: string | null;
  download_status: string;
  requires_auth: boolean;
  estimated_size_mb: number | null;
  bands_available: string[];
  crs_epsg?: number | null;
  checksum_sha256?: string | null;
  source_provider?: string | null;
  downloaded_bands?: Record<string, DownloadedBandInfo>;
  band_metadata_summary?: {
    provider_key?: string | null;
    downloaded_band_keys?: string[];
    asset_info_keys?: string[];
    auth_note?: string | null;
  };
  data_origin: string;
  collected_at: string;
}

export interface IngestionProviderResultItem {
  provider_key: string;
  status: string;
  records_written: number;
  fetched_count: number;
  job_id: string | null;
  error: string | null;
}

export interface IngestionRunResult {
  aoi_id: string;
  results: IngestionProviderResultItem[];
}

export interface GIBSLayerItem {
  layer_id: string;
  title: string;
  tile_url_template: string;
  attribution: string;
  is_ml_training_allowed: boolean;
  usage_note: string;
}

export interface STACSceneItem {
  provider_key: string;
  collection: string;
  item_id: string;
  platform: string | null;
  product_type: string | null;
  acquired_at: string | null;
  cloud_cover_pct: number | null;
  resolution_m: number | null;
  requires_auth: boolean;
  auth_note: string | null;
  estimated_size_mb: number | null;
  bands_available: string[];
  bbox: number[];
  geometry: Record<string, unknown>;
  asset_hrefs: Record<string, string>;
}

export interface FeatureStatSummary {
  valid_pixels: number;
  total_pixels: number;
  valid_pct: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  std: number | null;
}

export interface FeatureManifestItem {
  id: string;
  aoi_id: string;
  target_crs_epsg: number;
  resolution_m: number;
  grid_rows: number;
  grid_cols: number;
  nodata_value: number;
  status: string;
  input_datasets_json: Record<string, unknown>[];
  input_scene_ids: string[];
  feature_names: string[];
  output_files_json: Record<string, string>;
  warnings_json: string[];
  manifest_json: {
    feature_stats?: Record<string, FeatureStatSummary>;
    feature_docs?: Record<string, unknown>[];
    dem_source_tile_ids?: string[];
    dem_coverage_pct?: number | null;
    dem_mosaic_crs?: string | null;
    spectral_sensors?: string[];
    aster_band_mapping?: Record<string, unknown>;
    [key: string]: unknown;
  };
  data_origin: string;
  created_at: string;
}

export interface FeatureOverlayDescriptor {
  manifest_id: string;
  feature_name: string;
  min: number | null;
  max: number | null;
  mean: number | null;
  valid_pct: number | null;
  nodata_value: number;
  wgs84_corners: [number, number][];
  image_url: string;
}

export interface AOICoverageSummary {
  aoi_id: string;
  aoi_name: string;
  processing_epsg: number;
  area_km2: number;
  occurrence_total: number;
  occurrence_ml_trainable: number;
  occurrence_reference_only: number;
  quarantined_count: number;
  quality_reports_count: number;
  geological_units_count: number;
  raster_scenes_discovered: number;
  raster_scenes_downloaded: number;
  feature_manifests_count: number;
  latest_manifest_id: string | null;
  missing_layers: string[];
  warnings: string[];
}

export interface DatasetQualityReportItem {
  id: string;
  aoi_id: string | null;
  source_provider_key: string;
  dataset_name: string;
  data_origin: string;
  total_rows: number;
  accepted_rows: number;
  rejected_rows: number;
  duplicate_rows: number;
  missing_coords_count: number;
  invalid_coords_count: number;
  missing_commodity_count: number;
  completeness_pct: number;
  commodity_distribution: Record<string, number>;
  warnings: string[];
  created_at: string;
}

export interface ProcessingJobItem {
  id: string;
  aoi_id: string | null;
  job_type: string;
  status: string;
  progress_pct: number;
  parameters_json: Record<string, unknown>;
  result_summary_json: Record<string, unknown>;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface MLDatasetVersionItem {
  id: string;
  aoi_id: string;
  manifest_id: string | null;
  version_tag: string;
  seed: number;
  positive_count: number;
  unlabeled_count: number;
  explicit_negative_count: number;
  spatial_block_count: number;
  feature_columns: string[];
  readiness_status: string;
  blocking_reasons: string[];
  leakage_checks: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  data_origin: string;
  created_at: string;
}

export type LayerKey =
  | 'feature_overlay'
  | 'geology_units'
  | 'raster_footprints'
  | 'aoi_boundary'
  | 'mineral_occurrences';

export interface GISLayerConfig {
  key: LayerKey;
  label: string;
  visible: boolean;
  opacity: number;
}

export type BasemapId = 'osm_standard' | 'esri_imagery' | 'opentopo' | 'nasa_gibs' | 'offline_grid';

export type InspectorSelection =
  | { kind: 'occurrence'; data: MineralOccurrenceItem }
  | { kind: 'geology'; data: GeologicalUnitItem }
  | { kind: 'aoi'; data: AOIItem }
  | null;

