import React, { useCallback, useEffect, useState } from 'react';
import { WorkbenchHeader } from './components/layout/WorkbenchHeader';
import { GISMapCanvas } from './components/map/GISMapCanvas';
import {
  geoJSONPolygonToVertices,
  verticesToGeoJSONPolygon,
} from './components/map/polygonGeometry';
import { LeftControlSidebar } from './components/panels/LeftControlSidebar';
import { RightInspectorDrawer } from './components/panels/RightInspectorDrawer';
import { apiClient } from './services/api';
import type {
  AOICoverageSummary,
  AOIItem,
  BasemapId,
  DatasetQualityReportItem,
  DataSourceItem,
  FeatureManifestItem,
  FeatureOverlayDescriptor,
  GeologicalUnitItem,
  GIBSLayerItem,
  GISLayerConfig,
  HealthStatus,
  InspectorSelection,
  LayerKey,
  MineralOccurrenceItem,
  MLDatasetVersionItem,
  ProcessingJobItem,
  RasterAssetItem,
} from './types/gis';

const DEFAULT_LAYERS: GISLayerConfig[] = [
  { key: 'mineral_occurrences', label: 'Mineral Occurrences (Authority)', visible: true, opacity: 1 },
  { key: 'aoi_boundary', label: 'AOI Boundaries', visible: true, opacity: 1 },
  { key: 'raster_footprints', label: 'STAC Footprints', visible: true, opacity: 0.85 },
  { key: 'feature_overlay', label: 'Feature Raster Overlay', visible: true, opacity: 0.8 },
  { key: 'geology_units', label: 'Bedrock Geology Units', visible: true, opacity: 0.7 },
];

export function App(): React.ReactElement {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sources, setSources] = useState<DataSourceItem[]>([]);
  const [aois, setAois] = useState<AOIItem[]>([]);
  const [activeAoi, setActiveAoi] = useState<AOIItem | null>(null);

  const [occurrences, setOccurrences] = useState<MineralOccurrenceItem[]>([]);
  const [geologyUnits, setGeologyUnits] = useState<GeologicalUnitItem[]>([]);
  const [rasters, setRasters] = useState<RasterAssetItem[]>([]);
  const [manifests, setManifests] = useState<FeatureManifestItem[]>([]);
  const [selectedManifestId, setSelectedManifestId] = useState<string | null>(null);
  const [selectedOverlayFeature, setSelectedOverlayFeature] = useState<string>('');
  const [overlay, setOverlay] = useState<FeatureOverlayDescriptor | null>(null);
  const [coverage, setCoverage] = useState<AOICoverageSummary | null>(null);
  const [qualityReports, setQualityReports] = useState<DatasetQualityReportItem[]>([]);
  const [mlDatasets, setMlDatasets] = useState<MLDatasetVersionItem[]>([]);
  const [mlUnavailableReason, setMlUnavailableReason] = useState<string | null>(null);

  const [gibsLayers, setGibsLayers] = useState<GIBSLayerItem[]>([]);
  const [basemap, setBasemap] = useState<BasemapId>('osm_standard');
  const [layers, setLayers] = useState<GISLayerConfig[]>(DEFAULT_LAYERS);
  const [rightOpen, setRightOpen] = useState(true);
  const [selection, setSelection] = useState<InspectorSelection>(null);
  const [interactionMode, setInteractionMode] = useState<'inspect' | 'draw' | 'edit'>('inspect');
  const [draftVertices, setDraftVertices] = useState<[number, number][]>([]);
  const [flyToTarget, setFlyToTarget] = useState<{
    lon: number;
    lat: number;
    zoom?: number;
    bbox?: number[];
  } | null>(null);

  const [initialLoading, setInitialLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<ProcessingJobItem | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollJobUntilTerminal = useCallback(
    async (initialJob: ProcessingJobItem, label: string): Promise<ProcessingJobItem> => {
      let current = initialJob;
      setActiveJob(current);
      while (current.status === 'pending' || current.status === 'running') {
        const lastBand =
          typeof current.result_summary_json?.last_band === 'string'
            ? ` · band ${current.result_summary_json.last_band}`
            : '';
        setStatusMessage(`${label} (${current.progress_pct}%${lastBand})...`);
        await new Promise((resolve) => setTimeout(resolve, 300));
        current = await apiClient.getJob(current.id);
        setActiveJob(current);
      }
      setActiveJob(null);
      if (current.status === 'failed') {
        throw new Error(current.error_message || `${label} failed`);
      }
      return current;
    },
    []
  );

  const handleCancelActiveJob = async () => {
    if (!activeJob) return;
    try {
      const updated = await apiClient.cancelJob(activeJob.id);
      setActiveJob(updated);
      setStatusMessage(`Cancelling job ${activeJob.id}...`);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to cancel job');
    }
  };

  const loadAoiContext = useCallback(async (aoi: AOIItem) => {
    setErrorMessage(null);
    const [occRes, geoRes, rasRes, manRes, covRes, qaRes] = await Promise.all([
      apiClient.listOccurrences(aoi.id),
      apiClient.listGeology(aoi.id),
      apiClient.listRasters(aoi.id),
      apiClient.listManifests(aoi.id),
      apiClient.getAoiCoverage(aoi.id),
      apiClient.listQualityReports(aoi.id),
    ]);
    setOccurrences(occRes);
    setGeologyUnits(geoRes);
    setRasters(rasRes);
    setManifests(manRes);
    setCoverage(covRes);
    setQualityReports(qaRes);

    if (manRes.length > 0) {
      const latest = manRes[0];
      setSelectedManifestId(latest.id);
      const preferred =
        latest.feature_names.find((f) => f === 'slope_deg') || latest.feature_names[0] || '';
      setSelectedOverlayFeature(preferred);
    } else {
      setSelectedManifestId(null);
      setSelectedOverlayFeature('');
      setOverlay(null);
    }

    try {
      const mlList = await apiClient.listMLDatasets(aoi.id);
      setMlDatasets(mlList);
      setMlUnavailableReason(null);
    } catch {
      setMlDatasets([]);
      setMlUnavailableReason(
        'ML dataset builder endpoint unavailable or not yet initialized for this workspace.'
      );
    }
  }, []);

  const bootstrap = useCallback(async () => {
    setInitialLoading(true);
    setErrorMessage(null);
    try {
      const [h, srcList, aoiList, gibs] = await Promise.all([
        apiClient.getHealth(),
        apiClient.listSources(),
        apiClient.listAois(),
        apiClient.listGibsLayers().catch(() => []),
      ]);
      setHealth(h);
      setSources(srcList);
      setAois(aoiList);
      setGibsLayers(gibs);
      if (aoiList.length > 0) {
        setActiveAoi(aoiList[0]);
        setFlyToTarget({
          lon: aoiList[0].centroid[0],
          lat: aoiList[0].centroid[1],
          bbox: aoiList[0].bbox,
        });
        await loadAoiContext(aoiList[0]);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to connect to backend API');
    } finally {
      setInitialLoading(false);
    }
  }, [loadAoiContext]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // Fetch feature overlay descriptor whenever manifest + band changes
  useEffect(() => {
    if (!selectedManifestId || !selectedOverlayFeature) {
      setOverlay(null);
      return;
    }
    let cancelled = false;
    apiClient
      .getFeatureOverlay(selectedManifestId, selectedOverlayFeature)
      .then((desc) => {
        if (!cancelled) setOverlay(desc);
      })
      .catch(() => {
        if (!cancelled) setOverlay(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedManifestId, selectedOverlayFeature]);

  const handleSelectAoi = async (aoi: AOIItem) => {
    setActiveAoi(aoi);
    setInteractionMode('inspect');
    setDraftVertices([]);
    setSelection({ kind: 'aoi', data: aoi });
    setFlyToTarget({ lon: aoi.centroid[0], lat: aoi.centroid[1], bbox: aoi.bbox });
    await loadAoiContext(aoi);
  };

  const withBusy = async (label: string, fn: () => Promise<void>) => {
    setBusyAction(label);
    setErrorMessage(null);
    setStatusMessage(`${label}...`);
    try {
      await fn();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : `${label} failed`);
      setStatusMessage(null);
    } finally {
      setBusyAction(null);
    }
  };

  const handleCreateKhetriPreset = async () => {
    await withBusy('Creating Khetri Copper Belt AOI', async () => {
      const created = await apiClient.createAoi({
        name: 'Khetri Copper Belt',
        description: 'Proterozoic Delhi Fold Belt copper-iron mineralization corridor',
        jurisdiction: 'IN',
        commodity_focus: ['Cu', 'Fe'],
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [75.77, 27.98],
              [75.82, 27.98],
              [75.82, 28.03],
              [75.77, 28.03],
              [75.77, 27.98],
            ],
          ],
        },
      });
      const updatedList = await apiClient.listAois();
      setAois(updatedList);
      await handleSelectAoi(created);
      setStatusMessage(`Created AOI '${created.name}' (EPSG:${created.processing_epsg}).`);
    });
  };

  const handleSaveDrawnAoi = async (name: string, commodities: string[]) => {
    await withBusy('Saving drawn AOI polygon', async () => {
      const created = await apiClient.createAoi({
        name,
        jurisdiction: 'IN',
        commodity_focus: commodities,
        geometry: verticesToGeoJSONPolygon(draftVertices),
      });
      const updatedList = await apiClient.listAois();
      setAois(updatedList);
      setInteractionMode('inspect');
      setDraftVertices([]);
      await handleSelectAoi(created);
      setStatusMessage(`Saved AOI '${created.name}' (${created.area_km2.toFixed(2)} km²).`);
    });
  };

  const handleSaveEditedAoi = async () => {
    if (!activeAoi) return;
    await withBusy('Updating AOI polygon geometry', async () => {
      const updated = await apiClient.updateAoi(activeAoi.id, {
        geometry: verticesToGeoJSONPolygon(draftVertices),
      });
      const updatedList = await apiClient.listAois();
      setAois(updatedList);
      setInteractionMode('inspect');
      setDraftVertices([]);
      await handleSelectAoi(updated);
      setStatusMessage(`Updated AOI geometry (${updated.area_km2.toFixed(2)} km²).`);
    });
  };

  const handleDeleteAoi = async (aoiId: string) => {
    await withBusy('Deleting AOI', async () => {
      await apiClient.deleteAoi(aoiId);
      const nextList = await apiClient.listAois();
      setAois(nextList);
      if (activeAoi?.id === aoiId) {
        const nextActive = nextList[0] || null;
        setActiveAoi(nextActive);
        if (nextActive) {
          await loadAoiContext(nextActive);
        } else {
          setOccurrences([]);
          setGeologyUnits([]);
          setRasters([]);
          setManifests([]);
          setCoverage(null);
          setOverlay(null);
        }
      }
      setStatusMessage('AOI deleted.');
    });
  };

  const handleToggleLayer = (key: LayerKey) => {
    setLayers((prev) => prev.map((l) => (l.key === key ? { ...l, visible: !l.visible } : l)));
  };

  const handleMoveLayer = (key: LayerKey, direction: 'up' | 'down') => {
    setLayers((prev) => {
      const idx = prev.findIndex((l) => l.key === key);
      if (idx === -1) return prev;
      const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= prev.length) return prev;
      const copy = [...prev];
      const [item] = copy.splice(idx, 1);
      copy.splice(swapIdx, 0, item);
      return copy;
    });
  };

  const handleChangeOpacity = (key: LayerKey, opacity: number) => {
    setLayers((prev) => prev.map((l) => (l.key === key ? { ...l, opacity } : l)));
  };

  return (
    <div className="workbench-shell">
      <WorkbenchHeader
        health={health}
        activeAoi={activeAoi}
        basemap={basemap}
        onBasemapChange={setBasemap}
        rightOpen={rightOpen}
        onToggleRight={() => setRightOpen((o) => !o)}
      />

      {(statusMessage || errorMessage || initialLoading) && (
        <div
          className={errorMessage ? 'toast-banner error' : 'toast-banner info'}
          role={errorMessage ? 'alert' : 'status'}
        >
          <span>
            {initialLoading
              ? 'Loading geospatial workspace...'
              : errorMessage || statusMessage}
          </span>
          {activeJob && (activeJob.status === 'pending' || activeJob.status === 'running') && (
            <button type="button" className="btn-xs" onClick={() => void handleCancelActiveJob()}>
              Cancel Job ({activeJob.progress_pct}%)
            </button>
          )}
          {errorMessage && (
            <button type="button" className="btn-xs" onClick={() => void bootstrap()}>
              Retry
            </button>
          )}
        </div>
      )}

      <main className={rightOpen ? 'workbench-main' : 'workbench-main right-collapsed'}>
        <LeftControlSidebar
          aois={aois}
          activeAoi={activeAoi}
          sources={sources}
          rasters={rasters}
          manifests={manifests}
          selectedManifestId={selectedManifestId}
          selectedOverlayFeature={selectedOverlayFeature}
          layers={layers}
          interactionMode={interactionMode}
          draftVertices={draftVertices}
          busyAction={busyAction}
          onSelectAoi={(a) => void handleSelectAoi(a)}
          onFlyTo={(t) => setFlyToTarget(t)}
          onGeocodeSearch={(q) => apiClient.geocodePlace(q)}
          onStartDraw={() => {
            setInteractionMode('draw');
            setDraftVertices([]);
          }}
          onStartEdit={() => {
            if (!activeAoi) return;
            setInteractionMode('edit');
            setDraftVertices(geoJSONPolygonToVertices(activeAoi.geometry));
          }}
          onCancelMode={() => {
            setInteractionMode('inspect');
            setDraftVertices([]);
          }}
          onUndoVertex={() => setDraftVertices((v) => v.slice(0, -1))}
          onSaveDrawnAoi={handleSaveDrawnAoi}
          onSaveEditedAoi={handleSaveEditedAoi}
          onDeleteAoi={handleDeleteAoi}
          onCreateKhetriPreset={handleCreateKhetriPreset}
          onRunIngestion={async () => {
            if (!activeAoi) return;
            await withBusy('Ingesting Macrostrat & USGS MRDS', async () => {
              const res = await apiClient.runIngestion(activeAoi.id);
              await loadAoiContext(activeAoi);
              const failed = (res.results || []).filter(
                (r) => Boolean(r.error) || r.status === 'failed'
              );
              const totalWritten = (res.results || []).reduce(
                (acc, r) => acc + (r.records_written || 0),
                0
              );
              if (failed.length > 0) {
                const msg = failed
                  .map((f) => `${f.provider_key}: ${f.error || f.status}`)
                  .join(' | ');
                setErrorMessage(`Partial/failed ingestion (${totalWritten} written) — ${msg}`);
                setStatusMessage(null);
              } else {
                const detail = (res.results || [])
                  .map((r) => `${r.provider_key}:${r.records_written}`)
                  .join(', ');
                setStatusMessage(`Ingestion completed (${detail}).`);
              }
            });
          }}
          onImportGeologicalFile={async (file, providerKey, inputEpsg) => {
            if (!activeAoi) return;
            await withBusy('Normalizing & importing geological dataset', async () => {
              const report = await apiClient.importGeologicalFile(
                activeAoi.id,
                file,
                providerKey,
                inputEpsg
              );
              await loadAoiContext(activeAoi);
              setStatusMessage(
                `Imported ${report.accepted_rows}/${report.total_rows} rows (${report.rejected_rows} quarantined).`
              );
            });
          }}
          onToggleLayer={handleToggleLayer}
          onMoveLayer={handleMoveLayer}
          onChangeLayerOpacity={handleChangeOpacity}
          onSelectManifest={(mid) => {
            setSelectedManifestId(mid);
            const found = manifests.find((m) => m.id === mid);
            if (found && found.feature_names.length > 0) {
              setSelectedOverlayFeature(found.feature_names[0]);
            }
          }}
          onSelectOverlayFeature={setSelectedOverlayFeature}
          onSearchSatellite={async (provider, collections) => {
            if (!activeAoi) return;
            await withBusy(`Searching ${provider}`, async () => {
              const res = await apiClient.searchSatellite({
                aoi_id: activeAoi.id,
                provider,
                collections,
                save_metadata: true,
              });
              await loadAoiContext(activeAoi);
              setStatusMessage(
                `Discovered ${res.scene_count} scenes (${res.saved_count} saved to catalog).`
              );
            });
          }}
          onDownloadAsset={async (assetId) => {
            if (!activeAoi) return;
            await withBusy('Downloading clipped AOI window', async () => {
              const job = await apiClient.downloadRasterAsset(assetId, 'auto');
              const finalJob = await pollJobUntilTerminal(job, 'Clipping & downloading AOI window');
              await loadAoiContext(activeAoi);
              if (finalJob.status === 'cancelled') {
                setStatusMessage('Raster download job was cancelled.');
                return;
              }
              const bandCount = finalJob.result_summary_json?.band_count_downloaded;
              setStatusMessage(
                bandCount
                  ? `Clipped COG downloaded & verified (${String(bandCount)} band groups).`
                  : 'Clipped COG downloaded and verified.'
              );
            });
          }}
          onExtractFeatures={async (resolutionM, includeGeology) => {
            if (!activeAoi) return;
            await withBusy(`Extracting ${resolutionM}m projected features`, async () => {
              const job = await apiClient.extractFeatures(activeAoi.id, {
                resolution_m: resolutionM,
                include_geology: includeGeology,
                include_sentinel2: true,
                include_aster: true,
                run_sync: false,
              });
              const finalJob = await pollJobUntilTerminal(
                job,
                `Extracting ${resolutionM}m projected features`
              );
              await loadAoiContext(activeAoi);
              if (finalJob.status === 'cancelled') {
                setStatusMessage('Feature extraction job was cancelled.');
                return;
              }
              const featCount = Array.isArray(finalJob.result_summary_json?.feature_names)
                ? finalJob.result_summary_json.feature_names.length
                : undefined;
              setStatusMessage(
                featCount
                  ? `Feature stack extracted (${featCount} layers) and manifest saved.`
                  : 'Feature stack extracted and manifest saved.'
              );
            });
          }}
        />

        <GISMapCanvas
          aois={aois}
          activeAoi={activeAoi}
          occurrences={occurrences}
          geologyUnits={geologyUnits}
          rasters={rasters}
          overlay={overlay}
          basemap={basemap}
          gibsLayer={gibsLayers[0] || null}
          layers={layers}
          interactionMode={interactionMode}
          draftVertices={draftVertices}
          onDraftVerticesChange={setDraftVertices}
          onSelectFeature={(sel) => {
            setSelection(sel);
            if (sel) setRightOpen(true);
          }}
          flyToTarget={flyToTarget}
        />

        <RightInspectorDrawer
          open={rightOpen}
          activeAoi={activeAoi}
          selection={selection}
          coverage={coverage}
          qualityReports={qualityReports}
          manifests={manifests}
          mlDatasets={mlDatasets}
          mlUnavailableReason={mlUnavailableReason}
          busyAction={busyAction}
          onBuildMLDataset={async () => {
            if (!activeAoi) return;
            await withBusy('Building spatial ML dataset', async () => {
              const ds = await apiClient.buildMLDataset(activeAoi.id, {
                manifest_id: selectedManifestId,
              });
              await loadAoiContext(activeAoi);
              setStatusMessage(`Built ML snapshot (${ds.readiness_status}).`);
            });
          }}
          onEvaluateMLBaseline={async (datasetId) => {
            if (!activeAoi) return;
            await withBusy('Evaluating spatial CV baseline', async () => {
              await apiClient.evaluateMLBaseline(datasetId);
              await loadAoiContext(activeAoi);
              setStatusMessage('Spatial CV baseline metrics updated.');
            });
          }}
        />
      </main>
    </div>
  );
}

export default App;
