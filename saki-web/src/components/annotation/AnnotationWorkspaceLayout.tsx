/**
 * AnnotationWorkspaceLayout Component
 * 
 * 标注工作空间的通用布局组件
 */

import { ReactNode } from 'react';
import { Layout } from 'antd';
import { useTranslation } from 'react-i18next';
import { LoadingState, EmptyState } from '../common';
import { SampleList, AnnotationToolbar, AnnotationSidebar } from './index';
import { Sample, Label, Annotation } from '../../types';
import { AnnotationLike, UseAnnotationStateReturn, AccessScope } from '../../hooks';

const { Content, Sider } = Layout;

export interface AnnotationWorkspaceLayoutProps<T extends AnnotationLike> {
  // 数据状态
  loading: boolean;
  dataset: any | null;
  samples: Sample[];
  labels: Label[];
  currentIndex: number;
  currentSample: Sample | undefined;
  
  // 标注状态
  annotationState: UseAnnotationStateReturn<T>;
  
  // 同步状态
  isSyncing: boolean;
  isSyncReady: boolean;
  
  // 回调函数
  onSampleSelect: (index: number) => void;
  onPrev: () => void;
  onNext: () => void;
  onSubmit: () => void;
  onAnnotationSelect: (id: string) => void;
  onAnnotationDelete: (id: string) => void;
  
  // 画布控制
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onResetView?: () => void;
  
  // 自定义内容
  canvasArea: ReactNode;
  sidebarExtra?: ReactNode;
  renderAnnotationItem?: (annotation: any, index: number) => ReactNode;
  
  // 权限控制
  currentUserId?: string;
  modifyScope?: AccessScope;
  canEditAnnotation?: (annotation: Annotation) => boolean;
  hasAnyEditPermission?: boolean;
}

export function AnnotationWorkspaceLayout<T extends AnnotationLike>({
  loading,
  dataset,
  samples,
  labels,
  currentIndex,
  currentSample,
  annotationState,
  isSyncing,
  isSyncReady,
  onSampleSelect,
  onPrev,
  onNext,
  onSubmit,
  onAnnotationSelect,
  onAnnotationDelete,
  onZoomIn,
  onZoomOut,
  onResetView,
  canvasArea,
  sidebarExtra,
  renderAnnotationItem,
  // 权限控制
  currentUserId,
  modifyScope = 'assigned',
  canEditAnnotation,
  hasAnyEditPermission = true,
}: AnnotationWorkspaceLayoutProps<T>) {
  const { t } = useTranslation();

  // 加载状态
  if (loading || !dataset) {
    return <LoadingState tip={t('workspace.loading')} />;
  }

  // 空状态检查
  if (!currentSample || samples.length === 0) {
    return <EmptyState description={t('workspace.noSamples')} />;
  }

  // 检查标签配置
  if (labels.length === 0) {
    return <EmptyState description={t('workspace.noLabelsConfigured')} />;
  }

  return (
    <Layout style={{ height: '100%' }}>
      {/* Left Sidebar - Sample List */}
      <Sider width={250} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
        <SampleList
          samples={samples}
          currentIndex={currentIndex}
          onSampleSelect={onSampleSelect}
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
          onZoomIn={onZoomIn}
          onZoomOut={onZoomOut}
          onResetView={onResetView}
          syncStatus={{
            isSyncing,
            isSyncReady,
          }}
          hasAnyEditPermission={hasAnyEditPermission}
        />

        {/* Canvas Area */}
        <div
          style={{
            flex: 1,
            position: 'relative',
            overflow: 'hidden',
            background: '#333',
            pointerEvents: isSyncing ? 'none' : 'auto',
            opacity: isSyncing ? 0.6 : 1,
          }}
        >
          {canvasArea}
        </div>
      </Content>

      {/* Right Sidebar */}
      <AnnotationSidebar
        annotations={annotationState.annotations as any[]}
        selectedId={annotationState.selectedId}
        onAnnotationSelect={onAnnotationSelect}
        onAnnotationDelete={onAnnotationDelete}
        currentIndex={currentIndex}
        totalSamples={samples.length}
        onPrev={onPrev}
        onNext={onNext}
        onSubmit={onSubmit}
        renderAnnotationItem={renderAnnotationItem}
        currentUserId={currentUserId}
        canEditAnnotation={canEditAnnotation}
        hasAnyEditPermission={hasAnyEditPermission}
      />
      {sidebarExtra}
    </Layout>
  );
}

