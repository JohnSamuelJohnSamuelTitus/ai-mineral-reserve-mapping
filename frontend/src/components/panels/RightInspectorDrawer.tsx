import React, { useState } from 'react';
import type {
  AOICoverageSummary,
  AOIItem,
  DatasetQualityReportItem,
  FeatureManifestItem,
  InspectorSelection,
  MLDatasetVersionItem,
} from '../../types/gis';

interface RightInspectorDrawerProps {
  open: boolean;
  activeAoi: AOIItem | null;
  selection: InspectorSelection;
  coverage: AOICoverageSummary | null;
  qualityReports: DatasetQualityReportItem[];
  manifests: FeatureManifestItem[];
  mlDatasets: MLDatasetVersionItem[];
  mlUnavailableReason: string | null;
  busyAction: string | null;
  onBuildMLDataset: () => Promise<void>;
  onEvaluateMLBaseline: (datasetId: string) => Promise<void>;
}

type RightTab = 'inspector' | 'dashboard' | 'features_ml';

export const RightInspectorDrawer: React.FC<RightInspectorDrawerProps> = ({
  open,
  activeAoi,
  selection,
  coverage,
  qualityReports,
  manifests,
  mlDatasets,
  mlUnavailableReason,
  busyAction,
  onBuildMLDataset,
  onEvaluateMLBaseline,
}) => {
  const [tab, setTab] = useState<RightTab>('dashboard');
  const latestManifest = manifests[0] || null;
  const featureStats = latestManifest?.manifest_json?.feature_stats || {};

  if (!open) return null;

  return (
    <aside className="right-drawer" aria-label="Inspector and Dashboard">
      <div className="panel-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'inspector'}
          className={tab === 'inspector' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('inspector')}
        >
          Inspector
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'dashboard'}
          className={tab === 'dashboard' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('dashboard')}
        >
          AOI Health
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'features_ml'}
          className={tab === 'features_ml' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('features_ml')}
        >
          Features &amp; ML
        </button>
      </div>

      <div className="sidebar-scroll">
        {tab === 'inspector' && (
          <div className="panel-section-group">
            {!selection ? (
              <section className="card">
                <h2>Feature Inspector</h2>
                <p className="empty-state">
                  Click any mineral occurrence marker, geological unit polygon, or AOI on the map
                  to inspect its scientific provenance and attributes.
                </p>
              </section>
            ) : selection.kind === 'occurrence' ? (
              <section className="card">
                <h2>Mineral Occurrence</h2>
                <p className="feature-headline">{selection.data.name}</p>
                <dl className="kv-grid">
                  <dt>Primary Commodity</dt>
                  <dd>{selection.data.commodity_primary || 'Unknown'}</dd>
                  <dt>All Commodities</dt>
                  <dd>{selection.data.commodities_all.join(', ') || 'None'}</dd>
                  <dt>Authority</dt>
                  <dd>{selection.data.label_authority}</dd>
                  <dt>Data Origin</dt>
                  <dd>{selection.data.data_origin}</dd>
                  <dt>Deposit Type</dt>
                  <dd>{selection.data.deposit_type || 'Unspecified'}</dd>
                  <dt>Coordinates</dt>
                  <dd>
                    {selection.data.lat.toFixed(5)}°, {selection.data.lon.toFixed(5)}°
                  </dd>
                </dl>
              </section>
            ) : selection.kind === 'geology' ? (
              <section className="card">
                <h2>Geological Bedrock Unit</h2>
                <p className="feature-headline">{selection.data.unit_name}</p>
                <dl className="kv-grid">
                  <dt>Stratigraphy</dt>
                  <dd>{selection.data.strat_name || 'N/A'}</dd>
                  <dt>Normalized Lithology</dt>
                  <dd>{selection.data.lithology_class.join(', ') || 'Other'}</dd>
                  <dt>Raw Lithology</dt>
                  <dd>{selection.data.lithology_raw || 'N/A'}</dd>
                  <dt>Age Range (Ma)</dt>
                  <dd>
                    {selection.data.age_min_ma ?? '?'} – {selection.data.age_max_ma ?? '?'} Ma
                  </dd>
                  <dt>Period</dt>
                  <dd>{selection.data.period_name || 'Unknown'}</dd>
                </dl>
              </section>
            ) : (
              <section className="card">
                <h2>Area of Interest</h2>
                <p className="feature-headline">{selection.data.name}</p>
                <dl className="kv-grid">
                  <dt>Area</dt>
                  <dd>{selection.data.area_km2.toFixed(2)} km²</dd>
                  <dt>Processing CRS</dt>
                  <dd>EPSG:{selection.data.processing_epsg}</dd>
                  <dt>Commodities</dt>
                  <dd>{selection.data.commodity_focus.join(', ') || 'Any'}</dd>
                  <dt>Data Origin</dt>
                  <dd>{selection.data.data_origin}</dd>
                </dl>
              </section>
            )}
          </div>
        )}

        {tab === 'dashboard' && (
          <div className="panel-section-group">
            {!activeAoi || !coverage ? (
              <section className="card">
                <h2>AOI Readiness Summary</h2>
                <p className="empty-state">Select an AOI to inspect layer coverage and QA reports.</p>
              </section>
            ) : (
              <>
                <section className="card">
                  <h2>Data Coverage Metrics</h2>
                  <div className="metric-grid" data-testid="coverage-metrics">
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.occurrence_ml_trainable}</span>
                      <span className="metric-lbl">ML-Trainable Occ</span>
                    </div>
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.occurrence_reference_only}</span>
                      <span className="metric-lbl">Ref-Only Excluded</span>
                    </div>
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.quarantined_count}</span>
                      <span className="metric-lbl">Quarantined Rows</span>
                    </div>
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.geological_units_count}</span>
                      <span className="metric-lbl">Geology Units</span>
                    </div>
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.raster_scenes_downloaded}</span>
                      <span className="metric-lbl">Local Rasters</span>
                    </div>
                    <div className="metric-cell">
                      <span className="metric-val">{coverage.feature_manifests_count}</span>
                      <span className="metric-lbl">Feature Stacks</span>
                    </div>
                  </div>
                </section>

                <section className="card">
                  <h2>Missing Layers &amp; Caveats</h2>
                  <ul className="warning-list">
                    {coverage.missing_layers.map((m, idx) => (
                      <li key={`miss-${idx}`} className="missing-item">
                        Missing: {m}
                      </li>
                    ))}
                    {coverage.warnings.map((w, idx) => (
                      <li key={`warn-${idx}`} className="warn-item">
                        {w}
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="card">
                  <h2>Geological QA Audits ({qualityReports.length})</h2>
                  {qualityReports.length === 0 ? (
                    <p className="empty-state">No file imports audited yet.</p>
                  ) : (
                    <ul className="compact-list">
                      {qualityReports.slice(0, 5).map((q) => (
                        <li key={q.id} className="qa-row">
                          <strong>{q.dataset_name}</strong> ({q.source_provider_key}) —{' '}
                          {q.accepted_rows}/{q.total_rows} accepted ({q.completeness_pct}% complete,{' '}
                          {q.rejected_rows} quarantined)
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </>
            )}
          </div>
        )}

        {tab === 'features_ml' && (
          <div className="panel-section-group">
            <section className="card">
              <h2>Spectral &amp; Terrain Stack Stats</h2>
              {!latestManifest ? (
                <p className="empty-state">
                  No feature manifest generated yet. Download a DEM or ingest geology and run Feature Engineering.
                </p>
              ) : (
                <>
                  <p className="small-note">
                    CRS: EPSG:{latestManifest.target_crs_epsg} · Grid {latestManifest.grid_rows}×
                    {latestManifest.grid_cols} @ {latestManifest.resolution_m}m
                  </p>
                  {Array.isArray(latestManifest.manifest_json?.dem_source_tile_ids) &&
                    latestManifest.manifest_json.dem_source_tile_ids.length > 0 && (
                      <p className="small-note" data-testid="dem-provenance">
                        DEM Tiles: {latestManifest.manifest_json.dem_source_tile_ids.join(', ')}
                        {typeof latestManifest.manifest_json.dem_coverage_pct === 'number'
                          ? ` (${latestManifest.manifest_json.dem_coverage_pct}% AOI coverage)`
                          : ''}
                      </p>
                    )}
                  {Array.isArray(latestManifest.manifest_json?.spectral_sensors) &&
                    latestManifest.manifest_json.spectral_sensors.length > 0 && (
                      <p className="small-note">
                        Spectral Sensors: {latestManifest.manifest_json.spectral_sensors.join(', ')}
                      </p>
                    )}
                  {latestManifest.manifest_json?.aster_band_mapping &&
                    Object.keys(latestManifest.manifest_json.aster_band_mapping).length > 0 && (
                      <p className="small-note" data-testid="aster-mapping-provenance">
                        ASTER Bands Mapped:{' '}
                        {Object.keys(latestManifest.manifest_json.aster_band_mapping).join(', ')}
                      </p>
                    )}
                  {latestManifest.warnings_json && latestManifest.warnings_json.length > 0 && (
                    <ul className="warning-list">
                      {latestManifest.warnings_json.slice(0, 4).map((w, idx) => (
                        <li key={idx} className="warn-item">
                          {w}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="table-scroll">
                    <table className="stats-table">
                      <thead>
                        <tr>
                          <th>Feature</th>
                          <th>Valid%</th>
                          <th>Min</th>
                          <th>Mean</th>
                          <th>Max</th>
                        </tr>
                      </thead>
                      <tbody>
                        {latestManifest.feature_names.map((fname) => {
                          const st = featureStats[fname];
                          return (
                            <tr key={fname}>
                              <td>{fname}</td>
                              <td>{st ? `${st.valid_pct}%` : '—'}</td>
                              <td>{st?.min !== null && st?.min !== undefined ? st.min.toFixed(2) : '—'}</td>
                              <td>{st?.mean !== null && st?.mean !== undefined ? st.mean.toFixed(2) : '—'}</td>
                              <td>{st?.max !== null && st?.max !== undefined ? st.max.toFixed(2) : '—'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>

            <section className="card">
              <h2>Spatial ML Dataset Readiness</h2>
              {!activeAoi ? (
                <p className="empty-state">Select an AOI to inspect ML dataset readiness.</p>
              ) : mlUnavailableReason ? (
                <p className="empty-state" data-testid="ml-unavailable">
                  {mlUnavailableReason}
                </p>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-primary full-width"
                    disabled={!latestManifest || Boolean(busyAction)}
                    onClick={onBuildMLDataset}
                  >
                    Build Spatial ML Snapshot
                  </button>
                  {mlDatasets.length === 0 ? (
                    <p className="empty-state">No ML dataset snapshots built for this AOI yet.</p>
                  ) : (
                    <ul className="compact-list">
                      {mlDatasets.map((ds) => (
                        <li key={ds.id} className="ml-card">
                          <div className="raster-title">
                            <strong>{ds.version_tag}</strong>
                            <span
                              className={
                                ds.readiness_status === 'ready' ? 'pill ok' : 'pill blocked'
                              }
                            >
                              {ds.readiness_status}
                            </span>
                          </div>
                          <p className="small-note">
                            Positives: {ds.positive_count} · Explicit Neg: {ds.explicit_negative_count} ·
                            Unlabeled BG: {ds.unlabeled_count} · Blocks: {ds.spatial_block_count}
                          </p>
                          {ds.blocking_reasons.length > 0 && (
                            <ul className="warning-list">
                              {ds.blocking_reasons.map((reason, idx) => (
                                <li key={idx} className="warn-item">
                                  {reason}
                                </li>
                              ))}
                            </ul>
                          )}
                          {typeof ds.metrics_json?.evaluation_scheme === 'string' && (
                            <div className="small-note" data-testid="ml-baseline-metrics">
                              <strong>{ds.metrics_json.evaluation_scheme}</strong>
                              <br />
                              LogReg PU-PR-AUC:{' '}
                              {String((ds.metrics_json.logistic_regression as Record<string, unknown>)?.pu_pr_auc ?? '—')}
                              {' · '}RF PU-PR-AUC:{' '}
                              {String((ds.metrics_json.random_forest as Record<string, unknown>)?.pu_pr_auc ?? '—')}
                            </div>
                          )}
                          <button
                            type="button"
                            className="btn-secondary full-width"
                            disabled={ds.readiness_status !== 'ready' || Boolean(busyAction)}
                            onClick={() => onEvaluateMLBaseline(ds.id)}
                          >
                            {ds.readiness_status === 'ready'
                              ? 'Run Spatial CV Baseline'
                              : 'Baseline Blocked (Low Readiness)'}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </div>
    </aside>
  );
};

