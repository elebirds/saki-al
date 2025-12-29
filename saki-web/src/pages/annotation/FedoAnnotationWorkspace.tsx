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
import { Layout, message, Spin, Empty, Tag } from 'antd';
import { useTranslation } from 'react-i18next';
import { DeleteOutlined, RotateRightOutlined, BorderOutlined } from '@ant-design/icons';
import { AnnotationToolbar, AnnotationSidebar, DualCanvasArea, DualCanvasAreaRef } from '../../components/annotation';
import { api } from '../../services/api';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
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

/** Convert backend generated annotations to MappedRegion[] */
function generatedToRegions(generated: Array<Record<string, any>>): MappedRegion[] {
  return generated
    .filter((gen) => gen.view === 'L-omegad')
    .map((gen, index) => {
      const data = gen.data || {};
      // 将 bbox 转换为 polygon points（简化处理，实际可能需要更复杂的转换）
      const bbox = {
        x: data.x || 0,
        y: data.y || 0,
        width: data.width || 0,
        height: data.height || 0,
        rotation: data.rotation || 0,
      };

      // 简化的转换：将 bbox 转换为矩形 polygon
      const polygonPoints: [number, number][] = [
        [bbox.x, bbox.y],
        [bbox.x + bbox.width, bbox.y],
        [bbox.x + bbox.width, bbox.y + bbox.height],
        [bbox.x, bbox.y + bbox.height],
      ];

      return {
        timeRange: [0, 0] as [number, number], // 后端应该提供这个信息
        polygonPoints,
        isPrimary: index === 0,
      };
    });
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

  // Dual Canvas Area Ref
  const dualCanvasAreaRef = useRef<DualCanvasAreaRef>(null);

  // Current sample
  const currentSample = samples[currentIndex];

  // 使用公共的状态管理 hook（适配 DualViewAnnotation）
  const annotationState = useAnnotationState<DualViewAnnotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook（调用后端 sync 接口）
  const { isSyncing, isSyncReady, sync: syncBackend } = useAnnotationSync({ enabled: true });

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

  // Load sample data
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
    }
  }, [currentSample?.id]);

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

      try {
        // 调用后端 sync
        const syncResponse = await syncBackend(currentSample.id, [syncAction]);
        
        // 处理后端返回的生成标注，转换为 regions
        let regions: MappedRegion[] = [];
        if (syncResponse.results[0]?.generated) {
          regions = generatedToRegions(syncResponse.results[0].generated);
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
    [currentSample, annotationState, syncBackend, t]
  );

  const handleUpdateAnnotation = useCallback(
    async (updatedAnn: Annotation) => {
      if (!currentSample) return;

      // 调用后端 sync
      const syncAction: SyncAction = {
        action: 'update',
        annotationId: updatedAnn.id,
        labelId: updatedAnn.labelId,
        type: updatedAnn.type,
        data: updatedAnn.data,
        extra: updatedAnn.extra || {},
      };

      try {
        const syncResponse = await syncBackend(currentSample.id, [syncAction]);
        
        // 处理后端返回的生成标注，转换为 regions
        let regions: MappedRegion[] = [];
        if (syncResponse.results[0]?.generated) {
          regions = generatedToRegions(syncResponse.results[0].generated);
        }

        const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, regions);
        annotationState.handleAnnotationUpdate(dualAnn);
      } catch (error) {
        console.error('Sync failed:', error);
        // 即使 sync 失败，也更新标注（使用现有的 regions）
        const existingDual = annotationState.annotations.find((a) => a.id === updatedAnn.id);
        const existingRegions = existingDual?.secondary?.regions || [];
        const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, existingRegions);
        annotationState.handleAnnotationUpdate(dualAnn);
      }
    },
    [currentSample, annotationState, syncBackend]
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
        <Spin size="large">
          <div style={{ minHeight: 200 }} />
        </Spin>
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
            dualCanvasAreaRef.current?.zoomIn();
          }}
          onZoomOut={() => {
            dualCanvasAreaRef.current?.zoomOut();
          }}
          onResetView={() => {
            dualCanvasAreaRef.current?.resetView();
          }}
          syncStatus={{
            isSyncing,
            isSyncReady,
          }}
        />

        {/* Dual Canvas Area */}
        <DualCanvasArea
          ref={dualCanvasAreaRef}
          timeEnergyImageUrl={timeEnergyImageUrl}
          lWdImageUrl={lWdImageUrl}
          annotations={canvasAnnotations}
          onAnnotationCreate={handleAnnotationCreate}
          onAnnotationUpdate={handleUpdateAnnotation}
          onAnnotationDelete={handleDeleteAnnotation}
          currentTool={annotationState.currentTool}
          labelColor={annotationState.selectedLabel?.color || '#ff0000'}
          selectedId={annotationState.selectedId}
          onSelect={annotationState.setSelectedId}
          isSyncing={isSyncing}
          currentMappedRegions={currentMappedRegions}
        />
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
