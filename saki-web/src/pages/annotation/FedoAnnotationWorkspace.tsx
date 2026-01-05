/**
 * FEDO Dual-View Annotation Workspace
 * 
 * Specialized annotation workspace for satellite FEDO data with:
 * - Left panel: Time-Energy view (ax1) for primary annotation
 * - Right panel: L-ωd view (ax3) showing mapped regions
 * - Real-time bidirectional synchronization
 */

import React, { useRef, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { Tag } from 'antd';
import { useTranslation } from 'react-i18next';
import { DeleteOutlined, RotateRightOutlined, BorderOutlined } from '@ant-design/icons';
import { AnnotationWorkspaceLayout, DualCanvasArea, DualCanvasAreaRef } from '../../components/annotation';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
  useDatasetLoader,
  useSampleNavigation,
  useWorkspaceCommon,
  useFedoAnnotations,
  useFedoSubmit,
} from '../../hooks';
import { DualViewAnnotation, Annotation } from '../../types';
import { VIEW_TIME_ENERGY, VIEW_L_OMEGAD } from '../../components/annotation/DualCanvasArea';

// ============================================================================
// Component
// ============================================================================

const FedoAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();

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

  // Dual Canvas Area Ref
  const dualCanvasAreaRef = useRef<DualCanvasAreaRef>(null);

  // 使用公共的状态管理 hook（适配 DualViewAnnotation）
  const annotationState = useAnnotationState<DualViewAnnotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook（调用后端 sync 接口）
  const { isSyncing, isSyncReady, sync: syncBackend } = useAnnotationSync({ enabled: true });

  // 使用通用工作空间逻辑
  useWorkspaceCommon({ labels, annotationState });

  // 使用 FEDO 标注处理 hook
  const {
    generatedAnnotations,
    annotationViews,
    selectedAnnotationIds,
    canvasAnnotations,
    handleAnnotationSelect,
    handleAnnotationCreate,
    handleUpdateAnnotation,
    handleDeleteAnnotation,
  } = useFedoAnnotations({
    currentSampleId: currentSample?.id,
    annotationState,
    sync: syncBackend,
    t,
  });

  // ========================================================================
  // Navigation
  // ========================================================================

  // 使用样本导航 hook
  const { handleNext, handlePrev } = useSampleNavigation({
    currentIndex,
    totalSamples: samples.length,
    setCurrentIndex,
    onBeforeNext: () => annotationState.resetHistory(),
    onBeforePrev: () => annotationState.resetHistory(),
  });

  // 使用 FEDO 标注提交 hook
  const { handleSubmit } = useFedoSubmit({
    currentSampleId: currentSample?.id,
    annotations: annotationState.annotations,
    generatedAnnotations,
    annotationViews,
    updateSampleStatus,
    onNext: handleNext,
    t,
  });

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

  const handleSampleSelect = useCallback((index: number) => {
    setCurrentIndex(index);
    annotationState.resetHistory();
  }, [annotationState, setCurrentIndex]);

  // Get Image URLs from sample metadata
  const timeEnergyImageUrl: string =
    currentSample?.metaData?.timeEnergyImageUrl || currentSample?.url || '';

  const lWdImageUrl: string = currentSample?.metaData?.lWdImageUrl || '';

  // Selected Annotation Info
  const selectedAnnotation = annotationState.annotations.find(
    (a) => a.id === annotationState.selectedId
  );
  const currentMappedRegions = selectedAnnotation?.secondary?.regions || [];

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
        handleAnnotationSelect(id);
        annotationState.setCurrentTool('select');
      }}
      onAnnotationDelete={handleDeleteAnnotation}
      onZoomIn={() => dualCanvasAreaRef.current?.zoomIn()}
      onZoomOut={() => dualCanvasAreaRef.current?.zoomOut()}
      onResetView={() => dualCanvasAreaRef.current?.resetView()}
      canvasArea={
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
          selectedAnnotationIds={selectedAnnotationIds}
          onSelect={handleAnnotationSelect}
          currentMappedRegions={currentMappedRegions}
        />
      }
      renderAnnotationItem={(item: Annotation, index: number) => {
        // 检查该标注是否被选中（包括通过关联标注选中）
        const isSelected = selectedAnnotationIds.has(item.id);
        
        return (
          <div
            style={{
              padding: '8px 16px',
              background: isSelected ? '#e6f7ff' : 'transparent',
              cursor: 'pointer',
              borderLeft:
                isSelected
                  ? `4px solid ${item.labelColor || '#1890ff'}`
                  : '4px solid transparent',
            }}
            onClick={() => {
              handleAnnotationSelect(item.id);
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
                {/* 显示关联的生成标注数量 */}
                {(() => {
                  // 找到所有关联的生成标注
                  const relatedGenerated = canvasAnnotations.filter((ann: Annotation) => {
                    const parentId = ann.extra?.parent_id || ann.extra?.parentId;
                    return parentId === item.id;
                  });
                  
                  if (relatedGenerated.length > 0) {
                    // 获取主标注的 view
                    const mainView = item.extra?.view || annotationViews.get(item.id) || VIEW_TIME_ENERGY;
                    
                    // 获取生成标注的 view（通常是另一个画板）
                    // 如果生成标注有多个，取第一个的 view
                    const generatedView = relatedGenerated[0]?.extra?.view;
                    
                    // 如果生成标注没有 view，根据主标注的 view 推断
                    // 主标注在 Time-Energy，生成标注应该在 L-omegad
                    // 主标注在 L-omegad，生成标注应该在 Time-Energy
                    const inferredGeneratedView = generatedView || 
                      (mainView === VIEW_TIME_ENERGY ? VIEW_L_OMEGAD : VIEW_TIME_ENERGY);
                    
                    // 格式化显示：主标注画板 → 生成标注数量 生成标注画板
                    const mainViewLabel = mainView === VIEW_TIME_ENERGY ? 'T-E' : 'L-omegad';
                    const generatedViewLabel = inferredGeneratedView === VIEW_TIME_ENERGY ? 'T-E' : 'L-omegad';
                    
                    return (
                      <div style={{ marginTop: 4, fontSize: 11, color: '#888' }}>
                        {mainViewLabel} → {relatedGenerated.length} {generatedViewLabel} mapped annotation{relatedGenerated.length > 1 ? 's' : ''}
                      </div>
                    );
                  }
                  return null;
                })()}
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
  );
};

export default FedoAnnotationWorkspace;
