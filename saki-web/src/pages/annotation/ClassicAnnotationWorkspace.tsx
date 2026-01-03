import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Layout, message, Empty } from 'antd';
import { useTranslation } from 'react-i18next';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { AnnotationToolbar, AnnotationSidebar, SampleList } from '../../components/annotation';
import { api } from '../../services/api';
import { useAnnotationState, useAnnotationSync, useAnnotationShortcuts } from '../../hooks';
import { Sample, Annotation, Dataset, Label, AnnotationType, SyncAction } from '../../types';
import { originToCenter, centerToOrigin } from '../../utils/canvasUtils';

const { Content, Sider } = Layout;

const ClassicAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();
  const [searchParams] = useSearchParams();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const canvasRef = useRef<AnnotationCanvasRef>(null);

  // 使用公共的状态管理 hook
  const annotationState = useAnnotationState<Annotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook
  const { isSyncing, isSyncReady, sync } = useAnnotationSync({ enabled: true });

  const currentSample = samples[currentIndex];

  // 加载数据集、标签和样本
  useEffect(() => {
    if (datasetId) {
      // Load dataset
      api.getDataset(datasetId).then((d) => {
        if (d) setDataset(d);
      });
      // Load labels for this dataset
      api.getLabels(datasetId).then((loadedLabels) => {
        setLabels(loadedLabels);
        // Set default selected label
        if (loadedLabels.length > 0 && !annotationState.selectedLabel) {
          annotationState.setSelectedLabel(loadedLabels[0]);
        }
      });
      // Load samples with sort settings from localStorage
      const sortSettingsStr = localStorage.getItem(`dataset_${datasetId}_sort`);
      let sortOptions: {
        sortBy?: 'name' | 'status' | 'created_at' | 'updated_at' | 'remark';
        sortOrder?: 'asc' | 'desc';
      } = {};
      
      if (sortSettingsStr) {
        try {
          const sortSettings = JSON.parse(sortSettingsStr);
          sortOptions = {
            sortBy: sortSettings.sortBy,
            sortOrder: sortSettings.sortOrder,
          };
        } catch (e) {
          console.error('Failed to parse sort settings:', e);
        }
      }
      
      api.getSamples(datasetId, sortOptions).then((loadedSamples) => {
        setSamples(loadedSamples);
        // 如果URL中有sampleId参数，跳转到对应的sample
        const sampleId = searchParams.get('sampleId');
        if (sampleId && loadedSamples.length > 0) {
          const index = loadedSamples.findIndex(s => s.id === sampleId);
          if (index !== -1) {
            setCurrentIndex(index);
          }
        }
      });
    }
  }, [datasetId, searchParams]);

  // 加载当前样本的标注
  useEffect(() => {
    if (currentSample) {
      api.getSampleAnnotations(currentSample.id).then((response) => {
        // 后端返回的是中心点坐标，需要转换为起始点坐标用于前端显示
        // 对于 OBB 类型，将中心点转换为起始点
        const convertedAnnotations = response.annotations.map(ann => {
          if (ann.type === 'obb' && ann.data) {
            const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
            return {
              ...ann,
              data: centerToOrigin(bboxData)
            };
          }
          return ann;
        });
        
        // 重置历史记录
        annotationState.resetHistory();
        // 设置初始标注并添加到历史记录
        if (convertedAnnotations.length > 0) {
          annotationState.addToHistory(convertedAnnotations);
        } else {
          annotationState.setAnnotations([]);
        }
      });
    }
  }, [currentSample]);

  // 创建标注时调用 sync
  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    if (!annotationState.selectedLabel) {
      message.warning(t('workspace.noLabelSelected'));
      return;
    }

    if (!currentSample) return;

    const newId = Date.now().toString();
    const newAnn: Annotation = {
      id: newId,
      sampleId: currentSample.id,
      labelId: annotationState.selectedLabel.id,
      labelName: annotationState.selectedLabel.name,
      labelColor: annotationState.selectedLabel.color,
      type: event.type as AnnotationType,
      source: 'manual',
      data: {
        x: event.bbox.x,
        y: event.bbox.y,
        width: event.bbox.width,
        height: event.bbox.height,
        rotation: event.bbox.rotation,
      },
      extra: {},
    };

    // 对于 OBB 类型，将起始点转换为中心点再发送给后端
    let bboxData = newAnn.data;
    if (event.type === 'obb') {
      const bboxDataTyped = newAnn.data as { x: number; y: number; width: number; height: number; rotation?: number };
      bboxData = originToCenter(bboxDataTyped);
    }
    
    // 调用 sync 接口
    const syncAction: SyncAction = {
      action: 'create',
      annotationId: newId,
      labelId: annotationState.selectedLabel.id,
      type: event.type as AnnotationType,
      data: bboxData,
      extra: {},
    };

    try {
      await sync(currentSample.id, [syncAction]);
      // Classic 模式下，sync 不返回生成的标注，直接使用创建的标注
      annotationState.handleAnnotationCreate(newAnn);
    } catch (error) {
      console.error('Sync failed:', error);
      // 即使 sync 失败，也创建标注（降级处理）
      annotationState.handleAnnotationCreate(newAnn);
    }
  }, [currentSample, annotationState, sync, t]);

  // 更新标注时调用 sync
  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSample) return;

    // 对于 OBB 类型，将起始点转换为中心点再发送给后端
    let bboxData = updatedAnn.data;
    if (updatedAnn.type === 'obb' && bboxData) {
      const bboxDataTyped = bboxData as { x: number; y: number; width: number; height: number; rotation?: number };
      bboxData = originToCenter(bboxDataTyped);
    }

    const syncAction: SyncAction = {
      action: 'update',
      annotationId: updatedAnn.id,
      labelId: updatedAnn.labelId,
      type: updatedAnn.type,
      data: bboxData,
      extra: updatedAnn.extra || {},
    };

    try {
      await sync(currentSample.id, [syncAction]);
      annotationState.handleAnnotationUpdate(updatedAnn);
    } catch (error) {
      console.error('Sync failed:', error);
      annotationState.handleAnnotationUpdate(updatedAnn);
    }
  }, [currentSample, annotationState, sync]);

  // 删除标注时调用 sync
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSample) return;

    const syncAction: SyncAction = {
      action: 'delete',
      annotationId: id,
      extra: {},
    };

    try {
      await sync(currentSample.id, [syncAction]);
      annotationState.handleAnnotationDelete(id);
    } catch (error) {
      console.error('Sync failed:', error);
      annotationState.handleAnnotationDelete(id);
    }
  }, [currentSample, annotationState, sync]);

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
      // 对于 OBB 类型，将起始点转换为中心点（后端期望中心点坐标）
      const annsToSave = annotationState.annotations.map(ann => {
        if (ann.type === 'obb' && ann.data) {
          const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
          return {
            ...ann,
            data: originToCenter(bboxData)
          };
        }
        return ann;
      });
      
      await api.saveAnnotations(
        currentSample.id,
        annsToSave,
        'labeled'
      );
      message.success(t('annotation.saved') || 'Saved');
      handleNext();
    } catch (error) {
      message.error('Failed to save annotations');
    }
  }, [currentSample, annotationState.annotations, handleNext, t]);

  // 使用快捷键 hook
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

  const handleSampleSelect = useCallback((index: number) => {
    setCurrentIndex(index);
    annotationState.resetHistory();
  }, [annotationState]);

  if (!currentSample || !dataset) {
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
      {/* Left Sidebar - Sample List */}
      <Sider width={250} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
        <SampleList
          samples={samples}
          currentIndex={currentIndex}
          onSampleSelect={handleSampleSelect}
        />
      </Sider>

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
          onZoomIn={() => canvasRef.current?.zoomIn()}
          onZoomOut={() => canvasRef.current?.zoomOut()}
          onResetView={() => canvasRef.current?.resetView()}
          syncStatus={{
            isSyncing,
            isSyncReady,
          }}
        />

        {/* Canvas Area */}
        <div
          style={{
            flex: 1,
            position: 'relative',
            overflow: 'hidden',
            background: '#333',
            pointerEvents: isSyncing ? 'none' : 'auto', // 同步时禁用交互
            opacity: isSyncing ? 0.6 : 1,
          }}
        >
          <AnnotationCanvas
            ref={canvasRef}
            imageUrl={currentSample.url}
            annotations={annotationState.annotations}
            onAnnotationCreate={handleAnnotationCreate}
            onAnnotationUpdate={handleUpdateAnnotation}
            onAnnotationDelete={handleDeleteAnnotation}
            currentTool={annotationState.currentTool}
            labelColor={annotationState.selectedLabel?.color || '#ff0000'}
            selectedId={annotationState.selectedId}
            onSelect={annotationState.setSelectedId}
          />
        </div>
      </Content>

      {/* Sidebar */}
      <AnnotationSidebar
        annotations={annotationState.annotations}
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
      />
    </Layout>
  );
};

export default ClassicAnnotationWorkspace;
