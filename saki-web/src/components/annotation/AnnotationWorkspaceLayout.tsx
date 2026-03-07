/**
 * AnnotationWorkspaceLayout Component
 *
 * 标注工作空间的通用布局组件
 */

import {ReactNode} from 'react';
import {useTranslation} from 'react-i18next';
import {EmptyState, LoadingState} from '../common';
import {AnnotationSidebar, AnnotationToolbar, SampleList} from './index';
import {Annotation, DEFAULT_DETECTION_ANNOTATION_TYPES, DetectionAnnotationType, ProjectLabel, Sample} from '../../types';
import {AccessScope, AnnotationLike, UseAnnotationStateReturn} from '../../hooks';

export interface AnnotationWorkspaceLayoutProps<T extends AnnotationLike> {
    // 数据状态
    loading: boolean;
    dataset: any | null;
    samples: Sample[];
    labels: ProjectLabel[];
    currentIndex: number;
    currentSample: Sample | undefined;
    samplePage: number;
    samplePageSize: number;
    sampleTotal: number;
    sampleOffset: number;

    // 标注状态
    annotationState: UseAnnotationStateReturn<T>;
    selectedIds?: Set<string>;
    enabledAnnotationTypes?: DetectionAnnotationType[];

    // 同步状态
    isSyncing: boolean;
    isSyncReady: boolean;

    // 回调函数
    onSampleSelect: (index: number) => void;
    onSamplePageChange: (page: number) => void;
    onPrev: () => void;
    onNext: () => void;
    onSubmit: () => void;
    submitLabel?: string;
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
    onBack?: () => void;
    backLabel?: string;
    toolbarExtraActions?: ReactNode;
}

export function AnnotationWorkspaceLayout<T extends AnnotationLike>({
                                                                        loading,
                                                                        dataset,
                                                                        samples,
                                                                        labels,
                                                                        currentIndex,
                                                                        currentSample,
                                                                        samplePage,
                                                                        samplePageSize,
                                                                        sampleTotal,
                                                                        sampleOffset,
                                                                        annotationState,
                                                                        selectedIds,
                                                                        enabledAnnotationTypes = DEFAULT_DETECTION_ANNOTATION_TYPES,
                                                                        isSyncing,
                                                                        isSyncReady,
                                                                        onSampleSelect,
                                                                        onSamplePageChange,
                                                                        onPrev,
                                                                        onNext,
                                                                        onSubmit,
                                                                        submitLabel,
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
                                                                        canEditAnnotation,
                                                                        hasAnyEditPermission = true,
                                                                        onBack,
                                                                        backLabel,
                                                                        toolbarExtraActions,
                                                                    }: AnnotationWorkspaceLayoutProps<T>) {
    const {t} = useTranslation();

    // 加载状态
    if (loading || !dataset) {
        return <LoadingState tip={t('annotation.workspace.loading')}/>;
    }

    // 空状态检查
    if (!currentSample || samples.length === 0) {
        return <EmptyState description={t('annotation.workspace.noSamples')}/>;
    }

    // 检查标签配置
    if (labels.length === 0) {
        return <EmptyState description={t('annotation.workspace.noLabelsConfigured')}/>;
    }

    return (
        <div className="flex h-full bg-github-base text-github-text py-4">
            {/* Left Sidebar - Sample List */}
            <aside className="w-[250px] shrink-0">
                <SampleList
                    samples={samples}
                    currentIndex={currentIndex}
                    onSampleSelect={onSampleSelect}
                    total={sampleTotal}
                    offset={sampleOffset}
                    page={samplePage}
                    pageSize={samplePageSize}
                    onPageChange={onSamplePageChange}
                />
            </aside>

            <main className="px-2 flex h-full min-w-0 flex-1 flex-col">
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
                    enabledTools={enabledAnnotationTypes}
                    onZoomIn={onZoomIn}
                    onZoomOut={onZoomOut}
                    onResetView={onResetView}
                    syncStatus={{
                        isSyncing,
                        isSyncReady,
                    }}
                    onBack={onBack}
                    backLabel={backLabel}
                    extraActions={toolbarExtraActions}
                    hasAnyEditPermission={hasAnyEditPermission}
                />

                {/* Canvas Area */}
                <div
                    className="relative flex-1 overflow-hidden bg-[#333]"
                    style={{
                        pointerEvents: isSyncing ? 'none' : 'auto',
                        opacity: isSyncing ? 0.6 : 1,
                    }}
                >
                    {canvasArea}
                </div>
            </main>

            {/* Right Sidebar */}
            <AnnotationSidebar
                annotations={annotationState.annotations as any[]}
                selectedId={annotationState.selectedId}
                selectedIds={selectedIds}
                onAnnotationSelect={onAnnotationSelect}
                onAnnotationDelete={onAnnotationDelete}
                currentIndex={Math.max(0, sampleOffset + currentIndex)}
                totalSamples={sampleTotal}
                onPrev={onPrev}
                onNext={onNext}
                onSubmit={onSubmit}
                submitLabel={submitLabel}
                renderAnnotationItem={renderAnnotationItem}
                currentUserId={currentUserId}
                canEditAnnotation={canEditAnnotation}
                hasAnyEditPermission={hasAnyEditPermission}
            />
            {sidebarExtra}
        </div>
    );
}
