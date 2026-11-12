import React, { useState } from 'react';
import type {
  AOIItem,
  DataSourceItem,
  FeatureManifestItem,
  GISLayerConfig,
  LayerKey,
  RasterAssetItem,
} from '../../types/gis';
import { validateOpenPolygonVertices } from '../map/polygonGeometry';

interface LeftControlSidebarProps {
  aois: AOIItem[];
  activeAoi: AOIItem | null;
  sources: DataSourceItem[];
  rasters: RasterAssetItem[];
  manifests: FeatureManifestItem[];
  selectedManifestId: string | null;
  selectedOverlayFeature: string;
  layers: GISLayerConfig[];
  interactionMode: 'inspect' | 'draw' | 'edit';
  draftVertices: [number, number][];
  busyAction: string | null;
  onSelectAoi: (aoi: AOIItem) => void;
  onFlyTo: (target: { lon: number; lat: number; zoom?: number; bbox?: number[] }) => void;
  onGeocodeSearch: (query: string) => Promise<{ display_name: string; lat: number; lon: number; bbox?: number[] }[]>;
  onStartDraw: () => void;
  onStartEdit: () => void;
  onCancelMode: () => void;
  onUndoVertex: () => void;
  onSaveDrawnAoi: (name: string, commodities: string[]) => Promise<void>;
  onSaveEditedAoi: () => Promise<void>;
  onDeleteAoi: (aoiId: string) => Promise<void>;
  onCreateKhetriPreset: () => Promise<void>;
  onRunIngestion: () => Promise<void>;
  onImportGeologicalFile: (file: File, providerKey: string, inputEpsg: number) => Promise<void>;
  onToggleLayer: (key: LayerKey) => void;
  onMoveLayer: (key: LayerKey, direction: 'up' | 'down') => void;
  onChangeLayerOpacity: (key: LayerKey, opacity: number) => void;
  onSelectManifest: (manifestId: string) => void;
  onSelectOverlayFeature: (featureName: string) => void;
  onSearchSatellite: (provider: 'mpc_stac' | 'earth_search_stac' | 'nasa_cmr_stac', collections: string[]) => Promise<void>;
  onDownloadAsset: (assetId: string) => Promise<void>;
  onExtractFeatures: (resolutionM: number, includeGeology: boolean) => Promise<void>;
}

type LeftTab = 'aoi' | 'layers' | 'satellite';

export const LeftControlSidebar: React.FC<LeftControlSidebarProps> = ({
  aois,
  activeAoi,
  sources,
  rasters,
  manifests,
  selectedManifestId,
  selectedOverlayFeature,
  layers,
  interactionMode,
  draftVertices,
  busyAction,
  onSelectAoi,
  onFlyTo,
  onGeocodeSearch,
  onStartDraw,
  onStartEdit,
  onCancelMode,
  onUndoVertex,
  onSaveDrawnAoi,
  onSaveEditedAoi,
  onDeleteAoi,
  onCreateKhetriPreset,
  onRunIngestion,
  onImportGeologicalFile,
  onToggleLayer,
  onMoveLayer,
  onChangeLayerOpacity,
  onSelectManifest,
  onSelectOverlayFeature,
  onSearchSatellite,
  onDownloadAsset,
  onExtractFeatures,
}) => {
  const [tab, setTab] = useState<LeftTab>('aoi');
  const [geoQuery, setGeoQuery] = useState('');
  const [geoResults, setGeoResults] = useState<{ display_name: string; lat: number; lon: number; bbox?: number[] }[]>([]);
  const [drawName, setDrawName] = useState('');
  const [drawCommodity, setDrawCommodity] = useState('Cu');
  const [uploadProvider, setUploadProvider] = useState('ngdr_geodataindia');
  const [uploadEpsg, setUploadEpsg] = useState(4326);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [stacProvider, setStacProvider] = useState<'earth_search_stac' | 'mpc_stac' | 'nasa_cmr_stac'>(
    'earth_search_stac'
  );
  const [stacCollections, setStacCollections] = useState<string[]>(['cop-dem-glo-30', 'sentinel-2-l2a']);
  const [resolutionM, setResolutionM] = useState(100);
  const [includeGeology, setIncludeGeology] = useState(true);

  const activeManifest = manifests.find((m) => m.id === selectedManifestId) || manifests[0] || null;
  const draftValidation = validateOpenPolygonVertices(draftVertices);

  const handleGeocode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (geoQuery.trim().length < 2) return;
    const res = await onGeocodeSearch(geoQuery.trim());
    setGeoResults(res);
  };

  const toggleCollection = (col: string) => {
    setStacCollections((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    );
  };

  return (
    <aside className="left-sidebar" aria-label="GIS Controls">
      <div className="panel-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'aoi'}
          className={tab === 'aoi' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('aoi')}
        >
          AOI &amp; Data
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'layers'}
          className={tab === 'layers' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('layers')}
        >
          Layers
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'satellite'}
          className={tab === 'satellite' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('satellite')}
        >
          Satellite &amp; Features
        </button>
      </div>

      <div className="sidebar-scroll">
        {tab === 'aoi' && (
          <div className="panel-section-group">
            {/* Geocode Place Search */}
            <section className="card">
              <h2>Place Search (Nominatim)</h2>
              <form onSubmit={handleGeocode} className="inline-form">
                <input
                  type="text"
                  value={geoQuery}
                  onChange={(e) => setGeoQuery(e.target.value)}
                  placeholder="e.g. Khetri, Rajasthan"
                  aria-label="Search place"
                />
                <button type="submit" className="btn-secondary" disabled={Boolean(busyAction)}>
                  Go
                </button>
              </form>
              {geoResults.length > 0 && (
                <ul className="compact-list">
                  {geoResults.slice(0, 4).map((item, idx) => (
                    <li key={`${item.lon}-${idx}`}>
                      <button
                        type="button"
                        className="link-btn"
                        onClick={() => onFlyTo({ lon: item.lon, lat: item.lat, zoom: 11, bbox: item.bbox })}
                      >
                        {item.display_name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* AOI Drawing & Selection */}
            <section className="card">
              <div className="card-header-row">
                <h2>Areas of Interest ({aois.length})</h2>
                <button
                  type="button"
                  className="btn-xs"
                  onClick={onCreateKhetriPreset}
                  disabled={Boolean(busyAction)}
                >
                  + Khetri Preset
                </button>
              </div>

              <div className="button-row">
                {interactionMode === 'inspect' ? (
                  <>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={onStartDraw}
                      data-testid="draw-aoi-btn"
                    >
                      Draw Polygon
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={onStartEdit}
                      disabled={!activeAoi}
                    >
                      Edit Vertices
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="btn-secondary" onClick={onUndoVertex} disabled={draftVertices.length === 0}>
                      Undo Vertex
                    </button>
                    <button type="button" className="btn-secondary" onClick={onCancelMode}>
                      Cancel
                    </button>
                  </>
                )}
              </div>

              {interactionMode === 'draw' && (
                <div className="draw-box">
                  <p className="small-note">
                    Vertices: <strong>{draftVertices.length}</strong>{' '}
                    {draftValidation.valid
                      ? `· Est. Area ${draftValidation.estimatedAreaKm2} km²`
                      : `· ${draftValidation.reason}`}
                  </p>
                  <input
                    type="text"
                    value={drawName}
                    onChange={(e) => setDrawName(e.target.value)}
                    placeholder="New AOI Name (min 2 chars)"
                    aria-label="New AOI Name"
                  />
                  <input
                    type="text"
                    value={drawCommodity}
                    onChange={(e) => setDrawCommodity(e.target.value)}
                    placeholder="Commodities (comma-sep, e.g. Cu,Au)"
                    aria-label="AOI Commodities"
                  />
                  <button
                    type="button"
                    className="btn-primary full-width"
                    disabled={!draftValidation.valid || drawName.trim().length < 2 || Boolean(busyAction)}
                    onClick={async () => {
                      await onSaveDrawnAoi(
                        drawName.trim(),
                        drawCommodity
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean)
                      );
                      setDrawName('');
                    }}
                  >
                    Save Drawn AOI
                  </button>
                </div>
              )}

              {interactionMode === 'edit' && (
                <div className="draw-box">
                  <p className="small-note">
                    Vertices: <strong>{draftVertices.length}</strong>{' '}
                    {draftValidation.valid
                      ? `· Est. Area ${draftValidation.estimatedAreaKm2} km²`
                      : `· ${draftValidation.reason}`}
                  </p>
                  <button
                    type="button"
                    className="btn-primary full-width"
                    disabled={!draftValidation.valid || Boolean(busyAction)}
                    onClick={onSaveEditedAoi}
                  >
                    Save Edited Geometry
                  </button>
                </div>
              )}

              {aois.length === 0 ? (
                <p className="empty-state">No AOIs yet. Draw a polygon on the map or add the Khetri preset.</p>
              ) : (
                <ul className="aoi-list">
                  {aois.map((aoi) => (
                    <li
                      key={aoi.id}
                      className={activeAoi?.id === aoi.id ? 'aoi-row selected' : 'aoi-row'}
                    >
                      <button
                        type="button"
                        className="aoi-select-btn"
                        onClick={() => onSelectAoi(aoi)}
                      >
                        <strong>{aoi.name}</strong>
                        <span>
                          {aoi.area_km2.toFixed(1)} km² · EPSG:{aoi.processing_epsg}
                        </span>
                      </button>
                      <button
                        type="button"
                        className="btn-danger-xs"
                        onClick={() => onDeleteAoi(aoi.id)}
                        title="Delete AOI"
                        disabled={Boolean(busyAction)}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Real Geological Ingestion & File Import */}
            {activeAoi && (
              <section className="card">
                <h2>Geological Ingestion &amp; Import</h2>
                <button
                  type="button"
                  className="btn-secondary full-width"
                  onClick={onRunIngestion}
                  disabled={Boolean(busyAction)}
                >
                  Ingest Live Macrostrat &amp; USGS MRDS
                </button>
                <div className="divider-label">Or Import Local Dataset (GSI/NGDR/CSV/GPKG)</div>
                <label className="field-label">
                  Source Provenance
                  <select value={uploadProvider} onChange={(e) => setUploadProvider(e.target.value)}>
                    {sources.map((src) => (
                      <option key={src.provider_key} value={src.provider_key}>
                        {src.display_name} ({src.is_ml_training_allowed ? 'ML OK' : 'No ML'})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-label">
                  Input CRS EPSG
                  <input
                    type="number"
                    value={uploadEpsg}
                    onChange={(e) => setUploadEpsg(Number(e.target.value) || 4326)}
                  />
                </label>
                <input
                  type="file"
                  accept=".csv,.geojson,.json,.gpkg,.zip"
                  aria-label="Geological dataset file"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                />
                <button
                  type="button"
                  className="btn-primary full-width"
                  disabled={!selectedFile || Boolean(busyAction)}
                  onClick={async () => {
                    if (selectedFile) {
                      await onImportGeologicalFile(selectedFile, uploadProvider, uploadEpsg);
                      setSelectedFile(null);
                    }
                  }}
                >
                  Normalize, Quarantine &amp; Import
                </button>
              </section>
            )}
          </div>
        )}

        {tab === 'layers' && (
          <div className="panel-section-group">
            <section className="card">
              <h2>Layer Stack &amp; Z-Order</h2>
              <ul className="layer-stack-list">
                {layers.map((layer, idx) => (
                  <li key={layer.key} className="layer-item">
                    <div className="layer-row-top">
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={layer.visible}
                          onChange={() => onToggleLayer(layer.key)}
                        />
                        <span>{layer.label}</span>
                      </label>
                      <div className="layer-order-btns">
                        <button
                          type="button"
                          className="btn-xs"
                          disabled={idx === 0}
                          onClick={() => onMoveLayer(layer.key, 'up')}
                          title="Move Up"
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="btn-xs"
                          disabled={idx === layers.length - 1}
                          onClick={() => onMoveLayer(layer.key, 'down')}
                          title="Move Down"
                        >
                          ↓
                        </button>
                      </div>
                    </div>
                    {(layer.key === 'feature_overlay' || layer.key === 'geology_units') && (
                      <label className="opacity-slider-row">
                        <span>Opacity {Math.round(layer.opacity * 100)}%</span>
                        <input
                          type="range"
                          min={0.1}
                          max={1}
                          step={0.05}
                          value={layer.opacity}
                          onChange={(e) => onChangeLayerOpacity(layer.key, Number(e.target.value))}
                        />
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            {/* Feature Overlay Band Selector */}
            <section className="card">
              <h2>Feature Raster Overlay</h2>
              {manifests.length === 0 ? (
                <p className="empty-state">Run Feature Extraction first to render terrain/spectral overlays.</p>
              ) : (
                <>
                  <label className="field-label">
                    Manifest Run
                    <select
                      value={activeManifest?.id || ''}
                      onChange={(e) => onSelectManifest(e.target.value)}
                    >
                      {manifests.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.resolution_m}m · {m.feature_names.length} bands ({m.grid_rows}x{m.grid_cols})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field-label">
                    Displayed Layer Band
                    <select
                      value={selectedOverlayFeature}
                      onChange={(e) => onSelectOverlayFeature(e.target.value)}
                    >
                      {(activeManifest?.feature_names || []).map((fname) => (
                        <option key={fname} value={fname}>
                          {fname}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
            </section>

            {/* Authority & Lithology Legend */}
            <section className="card">
              <h2>Scientific Legend</h2>
              <ul className="legend-list">
                <li>
                  <span className="swatch" style={{ background: '#10b981' }} />
                  National Authority (GSI/NGDR — ML OK)
                </li>
                <li>
                  <span className="swatch" style={{ background: '#f59e0b' }} />
                  International Supplement (USGS MRDS)
                </li>
                <li>
                  <span className="swatch" style={{ background: '#ef4444' }} />
                  Reference-Only (Mindat — ML Blocked)
                </li>
                <li>
                  <span className="swatch" style={{ background: '#fbbf24' }} />
                  Active AOI Boundary
                </li>
                <li>
                  <span className="swatch" style={{ background: '#22d3ee' }} />
                  STAC Scene Footprint
                </li>
              </ul>
            </section>
          </div>
        )}

        {tab === 'satellite' && (
          <div className="panel-section-group">
            {!activeAoi ? (
              <p className="empty-state card">Select or draw an AOI first to search satellite scenes.</p>
            ) : (
              <>
                <section className="card">
                  <h2>STAC Discovery</h2>
                  <label className="field-label">
                    STAC Catalog
                    <select
                      value={stacProvider}
                      onChange={(e) =>
                        setStacProvider(
                          e.target.value as 'earth_search_stac' | 'mpc_stac' | 'nasa_cmr_stac'
                        )
                      }
                    >
                      <option value="earth_search_stac">Element 84 Earth Search</option>
                      <option value="mpc_stac">Microsoft Planetary Computer</option>
                      <option value="nasa_cmr_stac">NASA CMR LPCLOUD (EMIT/ASTER)</option>
                    </select>
                  </label>

                  <div className="collection-checks">
                    {[
                      'cop-dem-glo-30',
                      'sentinel-2-l2a',
                      'landsat-c2-l2',
                      'aster-l1t',
                      'EMITL2BMIN_001',
                    ].map((col) => (
                      <label key={col} className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={stacCollections.includes(col)}
                          onChange={() => toggleCollection(col)}
                        />
                        <span>{col}</span>
                      </label>
                    ))}
                  </div>

                  <button
                    type="button"
                    className="btn-primary full-width"
                    disabled={stacCollections.length === 0 || Boolean(busyAction)}
                    onClick={() => onSearchSatellite(stacProvider, stacCollections)}
                  >
                    Search Catalog Metadata
                  </button>
                </section>

                <section className="card">
                  <h2>Discovered Rasters ({rasters.length})</h2>
                  {rasters.length === 0 ? (
                    <p className="empty-state">No STAC scenes stored for this AOI yet.</p>
                  ) : (
                    <ul className="raster-list">
                      {rasters.slice(0, 8).map((r) => (
                        <li key={r.id} className="raster-row">
                          <div className="raster-title">
                            <strong>{r.stac_item_id}</strong>
                            <span className="pill">{r.stac_collection || r.asset_type}</span>
                          </div>
                          <div className="raster-meta">
                            <span>Status: {r.download_status}</span>
                            <span>
                              Est: {r.estimated_size_mb !== null ? `${r.estimated_size_mb} MB` : 'N/A'}
                            </span>
                            {r.requires_auth && <span className="warn-tag">Auth Required</span>}
                          </div>
                          {r.download_status !== 'downloaded' && (
                            <button
                              type="button"
                              className="btn-xs"
                              disabled={Boolean(busyAction)}
                              onClick={() => onDownloadAsset(r.id)}
                            >
                              Clip &amp; Download Window
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="card">
                  <h2>Feature Stack Pipeline</h2>
                  <label className="field-label">
                    Target UTM Resolution (m)
                    <select
                      value={resolutionM}
                      onChange={(e) => setResolutionM(Number(e.target.value))}
                    >
                      <option value={30}>30 m (High Detail — small AOI)</option>
                      <option value={100}>100 m (Balanced Default)</option>
                      <option value={250}>250 m (Fast Regional)</option>
                    </select>
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={includeGeology}
                      onChange={(e) => setIncludeGeology(e.target.checked)}
                    />
                    <span>Include Geological Proximity &amp; Units</span>
                  </label>
                  <button
                    type="button"
                    className="btn-primary full-width"
                    disabled={Boolean(busyAction)}
                    onClick={() => onExtractFeatures(resolutionM, includeGeology)}
                  >
                    Run Feature Engineering
                  </button>
                </section>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};

