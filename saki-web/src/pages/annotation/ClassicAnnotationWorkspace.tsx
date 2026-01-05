import React, { useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { message } from 'antd';
import { useTranslation } from 'react-i18next';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { AnnotationWorkspaceLayout } from '../../components/annotation';
import { api } from '../../services/api';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
  useDatasetLoader,
  useSampleNavigation,
  useWorkspaceCommon,
  useAnnotationSubmit,
} from '../../hooks';
import { Annotation, AnnotationType, SyncAction } from '../../types';
import { generateUUID } from '../../utils/uuid';

const ClassicAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();
  const canvasRef = useRef<AnnotationCanvasRef>(null);

  // 使用数据集加载器 hook
  const {
    dataset,
    labels,
    samples,
    loading,
    currentIndex,
    setCurrentIndex,
    currentSample,
    updateSampleStatus,
  } = useDatasetLoader({ datasetId });

  // 使用公共的状态管理 hook
  const annotationState = useAnnotationState<Annotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook
  const { isSyncing, isSyncReady, sync } = useAnnotationSync({ enabled: true });

  // 使用通用工作空间逻辑
  useWorkspaceCommon({ labels, annotationState });


  // 加载当前样本的标注
  useEffect(() => {
    if (currentSample) {
      api.getSampleAnnotations(currentSample.id).then((response) => {
        // 后端已经转换为左上角坐标，直接使用
        // 重置历史记录
        annotationState.resetHistory();
        // 设置初始标注并添加到历史记录
        if (response.annotations.length > 0) {
          annotationState.addToHistory(response.annotations);
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

    // 使用UUID格式生成ID，与后端生成的ID格式保持一致
    const newId = generateUUID();
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

    // 直接使用前端坐标（左上角），后端会自动转换
    const syncAction: SyncAction = {
      action: 'create',
      annotationId: newId,
      labelId: annotationState.selectedLabel.id,
      type: event.type as AnnotationType,
      data: newAnn.data,
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

    // 直接使用前端坐标（左上角），后端会自动转换
    const syncAction: SyncAction = {
      action: 'update',
      annotationId: updatedAnn.id,
      labelId: updatedAnn.labelId,
      type: updatedAnn.type,
      data: updatedAnn.data,
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

  // 使用样本导航 hook
  const { handleNext: navigateNext, handlePrev: navigatePrev } = useSampleNavigation({
    currentIndex,
    totalSamples: samples.length,
    setCurrentIndex,
    onBeforeNext: () => annotationState.resetHistory(),
    onBeforePrev: () => annotationState.resetHistory(),
  });

  const handleNext = useCallback(() => {
    navigateNext();
  }, [navigateNext]);

  const handlePrev = useCallback(() => {
    navigatePrev();
  }, [navigatePrev]);

  // 使用标注提交 hook
  const { handleSubmit } = useAnnotationSubmit({
    currentSampleId: currentSample?.id,
    annotations: annotationState.annotations,
    updateSampleStatus,
    onNext: handleNext,
    t,
  });

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
  }, [annotationState, setCurrentIndex]);

  return (
    <AnnotationWorkspaceLayout
      loading={loading}
      dataset={dataset}
      samples={samples}
      labels={labels}
      currentIndex={currentIndex}
      currentSample={currentSample}
      annotationState={annotationState}
      isSyncing={isSyncing}
      isSyncReady={isSyncReady}
      onSampleSelect={handleSampleSelect}
      onPrev={handlePrev}
      onNext={handleNext}
      onSubmit={handleSubmit}
      onAnnotationSelect={(id) => {
        annotationState.setSelectedId(id);
        annotationState.setCurrentTool('select');
      }}
      onAnnotationDelete={handleDeleteAnnotation}
      onZoomIn={() => canvasRef.current?.zoomIn()}
      onZoomOut={() => canvasRef.current?.zoomOut()}
      onResetView={() => canvasRef.current?.resetView()}
      canvasArea={
        <AnnotationCanvas
          ref={canvasRef}
          imageUrl={currentSample?.url || ''}
          annotations={annotationState.annotations}
          onAnnotationCreate={handleAnnotationCreate}
          onAnnotationUpdate={handleUpdateAnnotation}
          onAnnotationDelete={handleDeleteAnnotation}
          currentTool={annotationState.currentTool}
          labelColor={annotationState.selectedLabel?.color || '#ff0000'}
          selectedId={annotationState.selectedId}
          onSelect={annotationState.setSelectedId}
        />
      }
    />
  );
};

export default ClassicAnnotationWorkspace;
