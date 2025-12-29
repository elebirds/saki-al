/**
 * FEDO Dual-View Annotation Workspace
 * 
 * Specialized annotation workspace for satellite FEDO data with:
 * - Left panel: Time-Energy view (ax1) for primary annotation
 * - Right panel: L-ωd view (ax3) showing mapped regions
 * - Real-time bidirectional synchronization
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { Layout, message, Spin, Empty } from 'antd';
import { useTranslation } from 'react-i18next';
import { DeleteOutlined, RotateRightOutlined, BorderOutlined } from '@ant-design/icons';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { AnnotationToolbar, AnnotationSidebar } from '../../components/annotation';
import { api } from '../../services/api';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
  useDualViewSync,
} from '../../hooks';
import {
  Sample,
  Annotation,
  Dataset,
  Label,
  DualViewAnnotation,
  MappedRegion,
  BoundingBox,
  AnnotationType,
  SyncAction,
} from '../../types';

const { Content } = Layout;

// ============================================================================
// Helper Functions
// ============================================================================

/** Convert DualViewAnnotation to Annotation for AnnotationCanvas */
function dualToAnnotation(dual: DualViewAnnotation): Annotation {
  return {
    id: dual.id,
    sampleId: dual.sampleId,
    labelId: dual.labelId,
    labelName: dual.labelName,
    labelColor: dual.labelColor,
    type: dual.primary.type as AnnotationType,
    source: 'manual',
    data: dual.primary.bbox,
    extra: {
      view: 'primary',
      secondary: dual.secondary,
    },
  };
}

/** Convert Annotation to DualViewAnnotation */
function annotationToDual(ann: Annotation, regions: MappedRegion[] = []): DualViewAnnotation {
  const bbox: BoundingBox = {
    x: ann.data.x || 0,
    y: ann.data.y || 0,
    width: ann.data.width || 0,
    height: ann.data.height || 0,
    rotation: ann.data.rotation,
  };

  const extraRegions = ann.extra?.secondary?.regions || regions;

  return {
    id: ann.id,
    sampleId: ann.sampleId || '',
    labelId: ann.labelId,
    labelName: ann.labelName || '',
    labelColor: ann.labelColor || '#ff0000',
    primary: {
      type: ann.type as 'rect' | 'obb',
      bbox,
    },
    secondary: {
      regions: extraRegions,
    },
  };
}

// ============================================================================
// Component
// ============================================================================

const FedoAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();

  // Dataset & Samples State
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [labels, setLabels] = useState<Label[]>([]);

  // Canvas Refs
  const timeEnergyCanvasRef = useRef<AnnotationCanvasRef>(null);
  const lWdCanvasRef = useRef<AnnotationCanvasRef>(null);

  // Current sample
  const currentSample = samples[currentIndex];

  // 使用公共的状态管理 hook（适配 DualViewAnnotation）
  const annotationState = useAnnotationState<DualViewAnnotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook（调用后端 sync 接口）
  const { isSyncing: isBackendSyncing, isSyncReady: isBackendSyncReady, sync: syncBackend } =
    useAnnotationSync({ enabled: true });

  // FEDO 专用的客户端 Worker sync（用于双视图映射）
  const {
    isReady: isWorkerReady,
    isMapping: isWorkerMapping,
    initializeWithLookupTable,
    mapBboxToLWd,
    dispose: disposeSyncWorker,
  } = useDualViewSync();

  // 合并同步状态：后端同步或 Worker 映射中时都显示为同步中
  const isSyncing = isBackendSyncing || isWorkerMapping;
  const isSyncReady = isBackendSyncReady && isWorkerReady;

  // ========================================================================
  // Memoized Conversions
  // ========================================================================

  // Convert DualViewAnnotation[] to Annotation[] for AnnotationCanvas
  const canvasAnnotations = useMemo(() => {
    return annotationState.annotations.map(dualToAnnotation);
  }, [annotationState.annotations]);

  // ========================================================================
  // Data Loading
  // ========================================================================

  useEffect(() => {
    if (datasetId) {
      setLoading(true);
      Promise.all([
        api.getDataset(datasetId),
        api.getLabels(datasetId),
        api.getSamples(datasetId),
      ])
        .then(([ds, loadedLabels, samps]) => {
          if (ds) setDataset(ds);
          setLabels(loadedLabels);
          if (loadedLabels.length > 0 && !annotationState.selectedLabel) {
            annotationState.setSelectedLabel(loadedLabels[0]);
          }
          setSamples(samps);
          setLoading(false);
        })
        .catch((err) => {
          console.error('Failed to load dataset:', err);
          message.error('Failed to load dataset');
          setLoading(false);
        });
    }
  }, [datasetId]);

  // Load sample data and initialize worker
  useEffect(() => {
    if (currentSample?.id) {
      // Load annotations for this sample
      api.getSampleAnnotations(currentSample.id).then((response) => {
        const dualAnns: DualViewAnnotation[] = response.annotations.map((ann) =>
          annotationToDual(ann, [])
        );
        // 重置历史记录
        annotationState.resetHistory();
        // 设置初始标注并添加到历史记录
        if (dualAnns.length > 0) {
          annotationState.addToHistory(dualAnns);
        } else {
          annotationState.setAnnotations([]);
        }
      });

      // Initialize worker with lookup table from sample metadata
      const lookupTableUrl = currentSample.metaData?.lookup_table_url;
      if (lookupTableUrl) {
        initializeWithLookupTable(lookupTableUrl);
      }
    }
  }, [currentSample?.id, currentSample?.metaData?.lookup_table_url, initializeWithLookupTable]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disposeSyncWorker();
    };
  }, [disposeSyncWorker]);

  // ========================================================================
  // Annotation Handlers
  // ========================================================================

  const handleAnnotationCreate = useCallback(
    async (event: {
      type: 'rect' | 'obb';
      bbox: { x: number; y: number; width: number; height: number; rotation?: number };
    }) => {
      if (!annotationState.selectedLabel) {
        message.warning(t('workspace.noLabelSelected'));
        return;
      }

      if (!currentSample) return;

      const newId = Date.now().toString();

      // 调用后端 sync 接口
      const syncAction: SyncAction = {
        action: 'create',
        annotationId: newId,
        labelId: annotationState.selectedLabel.id,
        type: event.type as AnnotationType,
        data: event.bbox,
        extra: { view: 'time-energy' },
      };

      let regions: MappedRegion[] = [];
      let generatedAnnotations: Annotation[] = [];

      try {
        // 先调用后端 sync
        const syncResponse = await syncBackend(currentSample.id, [syncAction]);
        
        // 处理后端返回的生成标注（如果有）
        if (syncResponse.results[0]?.generated) {
          generatedAnnotations = syncResponse.results[0].generated as Annotation[];
          // 提取生成的 regions（如果有）
          // 这里假设生成的标注包含 secondary view 的信息
        }

        // 同时使用 Worker 进行客户端映射（作为补充）
        if (isWorkerReady) {
          try {
            const result = await mapBboxToLWd(event.bbox as BoundingBox);
            regions = result.regions;
          } catch (err) {
            console.warn('Worker mapping failed:', err);
          }
        }

        // 创建 DualViewAnnotation
        const newAnn: DualViewAnnotation = {
          id: newId,
          sampleId: currentSample.id,
          labelId: annotationState.selectedLabel.id,
          labelName: annotationState.selectedLabel.name || 'unknown',
          labelColor: annotationState.selectedLabel.color || '#ff0000',
          primary: {
            type: event.type,
            bbox: event.bbox,
          },
          secondary: {
            regions,
          },
        };

        annotationState.handleAnnotationCreate(newAnn);
      } catch (error) {
        console.error('Sync failed:', error);
        // 即使 sync 失败，也创建标注（降级处理）
        const newAnn: DualViewAnnotation = {
          id: newId,
          sampleId: currentSample.id,
          labelId: annotationState.selectedLabel.id,
          labelName: annotationState.selectedLabel.name || 'unknown',
          labelColor: annotationState.selectedLabel.color || '#ff0000',
          primary: {
            type: event.type,
            bbox: event.bbox,
          },
          secondary: {
            regions: [],
          },
        };
        annotationState.handleAnnotationCreate(newAnn);
      }
    },
    [
      currentSample,
      annotationState,
      syncBackend,
      isWorkerReady,
      mapBboxToLWd,
      t,
    ]
  );

  const handleUpdateAnnotation = useCallback(
    async (updatedAnn: Annotation) => {
      if (!currentSample) return;

      const bboxData = updatedAnn.data || {};
      const bbox: BoundingBox = {
        x: bboxData.x || 0,
        y: bboxData.y || 0,
        width: bboxData.width || 0,
        height: bboxData.height || 0,
        rotation: bboxData.rotation,
      };

      // 调用后端 sync
      const syncAction: SyncAction = {
        action: 'update',
        annotationId: updatedAnn.id,
        labelId: updatedAnn.labelId,
        type: updatedAnn.type,
        data: updatedAnn.data,
        extra: updatedAnn.extra || {},
      };

      let regions: MappedRegion[] = [];

      try {
        await syncBackend(currentSample.id, [syncAction]);

        // 使用 Worker 重新映射
        if (isWorkerReady && bbox.width > 0 && bbox.height > 0) {
          try {
            const result = await mapBboxToLWd(bbox);
            regions = result.regions;
          } catch (err) {
            console.warn('Worker mapping failed:', err);
          }
        }

        const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, regions);
        annotationState.handleAnnotationUpdate(dualAnn);
      } catch (error) {
        console.error('Sync failed:', error);
        const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, regions);
        annotationState.handleAnnotationUpdate(dualAnn);
      }
    },
    [currentSample, annotationState, syncBackend, isWorkerReady, mapBboxToLWd]
  );

  const handleDeleteAnnotation = useCallback(
    async (id: string) => {
      if (!currentSample) return;

      const syncAction: SyncAction = {
        action: 'delete',
        annotationId: id,
        extra: {},
      };

      try {
        await syncBackend(currentSample.id, [syncAction]);
        annotationState.handleAnnotationDelete(id);
      } catch (error) {
        console.error('Sync failed:', error);
        annotationState.handleAnnotationDelete(id);
      }
    },
    [currentSample, annotationState, syncBackend]
  );

  // ========================================================================
  // Navigation
  // ========================================================================

  const handleNext = useCallback(() => {
    if (currentIndex < samples.length - 1) {
      setCurrentIndex((c) => c + 1);
      annotationState.resetHistory();
    }
  }, [currentIndex, samples.length, annotationState]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex((c) => c - 1);
      annotationState.resetHistory();
    }
  }, [currentIndex, annotationState]);

  const handleSubmit = useCallback(async () => {
    if (!currentSample) return;
    try {
      const annsToSave: Annotation[] = annotationState.annotations.map(dualToAnnotation);
      await api.saveAnnotations(currentSample.id, annsToSave, 'labeled');
      message.success(t('annotation.saved') || 'Saved');
      handleNext();
    } catch (error) {
      message.error('Failed to save annotations');
    }
  }, [currentSample, annotationState.annotations, handleNext, t]);

  // ========================================================================
  // Keyboard Shortcuts
  // ========================================================================

  useAnnotationShortcuts({
    currentTool: annotationState.currentTool,
    onToolChange: annotationState.setCurrentTool,
    onNext: handleNext,
    onPrev: handlePrev,
    onSubmit: handleSubmit,
    onUndo: annotationState.undo,
    onRedo: annotationState.redo,
    disabled: isSyncing, // 同步时禁用快捷键
  });

  // ========================================================================
  // Get Image URLs from sample metadata
  // ========================================================================

  const timeEnergyImageUrl: string =
    currentSample?.metaData?.timeEnergyImageUrl || currentSample?.url || '';

  const lWdImageUrl: string = currentSample?.metaData?.lWdImageUrl || '';

  // ========================================================================
  // Selected Annotation Info
  // ========================================================================

  const selectedAnnotation = annotationState.annotations.find(
    (a) => a.id === annotationState.selectedId
  );
  const currentMappedRegions = selectedAnnotation?.secondary?.regions || [];

  // ========================================================================
  // Render
  // ========================================================================

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Spin size="large" tip="Loading..." />
      </div>
    );
  }

  if (!dataset || samples.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Empty description="No samples found for this dataset" />
      </div>
    );
  }

  if (!currentSample) {
    return <div>{t('workspace.loading')}</div>;
  }

  // Check if labels are configured
  if (labels.length === 0) {
    return (
      <Layout
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Empty description={t('workspace.noLabelsConfigured')} />
      </Layout>
    );
  }

  return (
    <Layout style={{ height: '100%' }}>
      <Content style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Toolbar */}
        <AnnotationToolbar
          labels={labels}
          selectedLabel={annotationState.selectedLabel}
          onLabelChange={annotationState.setSelectedLabel}
          historyIndex={annotationState.historyIndex}
          historyLength={annotationState.history.length}
          onUndo={annotationState.undo}
          onRedo={annotationState.redo}
          currentTool={annotationState.currentTool}
          onToolChange={annotationState.setCurrentTool}
          onZoomIn={() => {
            timeEnergyCanvasRef.current?.zoomIn();
            lWdCanvasRef.current?.zoomIn();
          }}
          onZoomOut={() => {
            timeEnergyCanvasRef.current?.zoomOut();
            lWdCanvasRef.current?.zoomOut();
          }}
          onResetView={() => {
            timeEnergyCanvasRef.current?.resetView();
            lWdCanvasRef.current?.resetView();
          }}
          syncStatus={{
            isSyncing,
            isSyncReady,
          }}
        />

        {/* Dual Canvas Area */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            overflow: 'hidden',
            pointerEvents: isSyncing ? 'none' : 'auto', // 同步时禁用交互
            opacity: isSyncing ? 0.6 : 1,
          }}
        >
          {/* Left: Time-Energy View */}
          <div
            style={{
              flex: 1,
              position: 'relative',
              overflow: 'hidden',
              background: '#333',
              borderRight: '2px solid #666',
            }}
          >
            <div
              style={{
                position: 'absolute',
                top: 8,
                left: 8,
                zIndex: 10,
                background: 'rgba(0,0,0,0.6)',
                color: '#fff',
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              Time-Energy (Primary)
            </div>
            <AnnotationCanvas
              ref={timeEnergyCanvasRef}
              imageUrl={timeEnergyImageUrl}
              annotations={canvasAnnotations}
              onAnnotationCreate={handleAnnotationCreate}
              onAnnotationUpdate={handleUpdateAnnotation}
              onAnnotationDelete={handleDeleteAnnotation}
              currentTool={annotationState.currentTool}
              labelColor={annotationState.selectedLabel?.color || '#ff0000'}
              selectedId={annotationState.selectedId}
              onSelect={annotationState.setSelectedId}
            />
          </div>

          {/* Right: L-ωd View (Read-only mapped regions) */}
          <div
            style={{
              flex: 1,
              position: 'relative',
              overflow: 'hidden',
              background: '#333',
            }}
          >
            <div
              style={{
                position: 'absolute',
                top: 8,
                left: 8,
                zIndex: 10,
                background: 'rgba(0,0,0,0.6)',
                color: '#fff',
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              L-ωd (Mapped Regions)
            </div>
            <AnnotationCanvas
              ref={lWdCanvasRef}
              imageUrl={lWdImageUrl}
              annotations={[]} // TODO: Convert mappedRegions to polygon Annotation format
              currentTool="select" // Force select mode - L-ωd view is read-only
              selectedId={null}
              onSelect={() => {}}
            />
            {/* Mapped regions count indicator */}
            {currentMappedRegions.length > 0 && (
              <div
                style={{
                  position: 'absolute',
                  bottom: 8,
                  left: 8,
                  zIndex: 10,
                  background: 'rgba(0,0,0,0.6)',
                  color: '#fff',
                  padding: '4px 8px',
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {currentMappedRegions.length} mapped region
                {currentMappedRegions.length > 1 ? 's' : ''}
              </div>
            )}
          </div>
        </div>
      </Content>

      {/* Right Sidebar */}
      <AnnotationSidebar
        annotations={canvasAnnotations}
        selectedId={annotationState.selectedId}
        onAnnotationSelect={(id) => {
          annotationState.setSelectedId(id);
          annotationState.setCurrentTool('select');
        }}
        onAnnotationDelete={handleDeleteAnnotation}
        currentIndex={currentIndex}
        totalSamples={samples.length}
        onPrev={handlePrev}
        onNext={handleNext}
        onSubmit={handleSubmit}
        renderAnnotationItem={(item, index) => {
          const dualAnn = annotationState.annotations.find((a) => a.id === item.id);
          return (
            <div
              style={{
                padding: '8px 16px',
                background: annotationState.selectedId === item.id ? '#e6f7ff' : 'transparent',
                cursor: 'pointer',
                borderLeft:
                  annotationState.selectedId === item.id
                    ? `4px solid ${item.labelColor || '#1890ff'}`
                    : '4px solid transparent',
              }}
              onClick={() => {
                annotationState.setSelectedId(item.id);
                annotationState.setCurrentTool('select');
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {item.type === 'obb' ? (
                      <RotateRightOutlined />
                    ) : (
                      <BorderOutlined />
                    )}
                    <Tag color={item.labelColor}>{item.labelName}</Tag>
                    <span>#{index + 1}</span>
                  </div>
                  {dualAnn && dualAnn.secondary.regions.length > 0 && (
                    <div style={{ marginTop: 4, fontSize: 11, color: '#888' }}>
                      → {dualAnn.secondary.regions.length} L-ωd region
                      {dualAnn.secondary.regions.length > 1 ? 's' : ''}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={(e: React.MouseEvent) => {
                    e.stopPropagation();
                    handleDeleteAnnotation(item.id);
                  }}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    cursor: 'pointer',
                    color: '#ff4d4f',
                    padding: '4px 8px',
                  }}
                >
                  <DeleteOutlined />
                </button>
              </div>
            </div>
          );
        }}
      />
    </Layout>
  );
};

export default FedoAnnotationWorkspace;
