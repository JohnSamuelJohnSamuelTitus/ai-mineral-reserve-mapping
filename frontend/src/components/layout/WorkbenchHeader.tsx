import React from 'react';
import type { AOIItem, BasemapId, HealthStatus } from '../../types/gis';

interface WorkbenchHeaderProps {
  health: HealthStatus | null;
  activeAoi: AOIItem | null;
  basemap: BasemapId;
  onBasemapChange: (next: BasemapId) => void;
  rightOpen: boolean;
  onToggleRight: () => void;
}

export const WorkbenchHeader: React.FC<WorkbenchHeaderProps> = ({
  health,
  activeAoi,
  basemap,
  onBasemapChange,
  rightOpen,
  onToggleRight,
}) => {
  return (
    <header className="workbench-header">
      <div className="header-brand">
        <span className="brand-dot" aria-hidden="true" />
        <div>
          <h1>AI Mineral Reserve Mapping Assistant</h1>
          <p className="header-subtitle">
            Geospatial Intelligence &amp; Scientific Prospectivity Workbench
          </p>
        </div>
      </div>

      <div className="header-meta">
        {health && (
          <span className="status-badge status-ok" title={health.scientific_disclaimer}>
            DB: {health.database_backend.toUpperCase()} {health.postgis_enabled ? '+ PostGIS' : '(Spatial Repo)'}
          </span>
        )}
        {activeAoi ? (
          <span className="status-badge status-aoi" data-testid="active-aoi-badge">
            AOI: {activeAoi.name} · {activeAoi.area_km2.toFixed(1)} km² · EPSG:{activeAoi.processing_epsg}
          </span>
        ) : (
          <span className="status-badge">No AOI Selected</span>
        )}

        <label className="basemap-select-wrap">
          <span>Basemap</span>
          <select
            aria-label="Basemap"
            value={basemap}
            onChange={(e) => onBasemapChange(e.target.value as BasemapId)}
          >
            <option value="osm_standard">OpenStreetMap</option>
            <option value="esri_imagery">Esri World Imagery</option>
            <option value="opentopo">OpenTopoMap Relief</option>
            <option value="nasa_gibs">NASA GIBS (Visual Only)</option>
            <option value="offline_grid">Offline Slate Grid</option>
          </select>
        </label>

        <button
          type="button"
          className="btn-secondary"
          onClick={onToggleRight}
          aria-expanded={rightOpen}
        >
          {rightOpen ? 'Hide Inspector' : 'Show Inspector'}
        </button>
      </div>
    </header>
  );
};

