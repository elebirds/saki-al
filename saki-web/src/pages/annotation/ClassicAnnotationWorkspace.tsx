import React, { useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { AnnotationWorkspaceLayout } from '../../components/annotation';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
  useDatasetLoader,
  useSampleNavigation,
  useWorkspaceCommon,
  useAnnotationSubmit,
  useClassicAnnotations,
} from '../../hooks';
import { Annotation } from '../../types';

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

  // 使用 Classic 标注处理 hook
  const {
    handleAnnotationCreate,
    handleUpdateAnnotation,
    handleDeleteAnnotation,
  } = useClassicAnnotations({
    currentSampleId: currentSample?.id,
    annotationState,
    sync,
    t,
  });

  // 使用样本导航 hook
  const { handleNext, handlePrev } = useSampleNavigation({
    currentIndex,
    totalSamples: samples.length,
    setCurrentIndex,
    onBeforeNext: () => annotationState.resetHistory(),
    onBeforePrev: () => annotationState.resetHistory(),
  });

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
