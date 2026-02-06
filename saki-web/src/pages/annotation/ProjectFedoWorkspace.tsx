import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button, Select} from 'antd';
import {DeleteOutlined} from '@ant-design/icons';
import {useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {AnnotationWorkspaceLayout, DualCanvasArea, DualCanvasAreaRef} from '../../components/annotation';
import CommitModal from '../../components/project/CommitModal';
import {
    Annotation,
    AnnotationDraftItem,
    AnnotationDraftPayload,
    Dataset,
    DualViewAnnotation,
    ProjectBranch,
    ProjectLabel,
} from '../../types';
import {api} from '../../services/api';
import {useAuthStore} from '../../store/authStore';
import {useAnnotationShortcuts, useAnnotationState, useAnnotationSync, useWorkspaceCommon} from '../../hooks';
import {useProjectSampleList} from '../../hooks/project/useProjectSampleList';
import {useResourcePermission} from '../../hooks/permission/usePermission';
import {canModifyAnnotation} from '../../store/permissionStore';
import {generateUUID} from '../../utils/uuid';
import {useFedoAnnotations} from '../../hooks/annotation/useFedoAnnotations';

export interface ProjectFedoWorkspaceProps {
    dataset: Dataset;
}

const ProjectFedoWorkspace: React.FC<ProjectFedoWorkspaceProps> = ({dataset}) => {
    const {t} = useTranslation();
    const {projectId, datasetId} = useParams<{ projectId: string; datasetId: string }>();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const dualCanvasAreaRef = useRef<DualCanvasAreaRef>(null);
    const user = useAuthStore((state) => state.user);

    const [labels, setLabels] = useState<ProjectLabel[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [loadingMeta, setLoadingMeta] = useState(true);
    const [commitModalOpen, setCommitModalOpen] = useState(false);
    const [commitLoading, setCommitLoading] = useState(false);
    const [annotationsLoading, setAnnotationsLoading] = useState(false);
    const [pendingIndex, setPendingIndex] = useState<'first' | 'last' | null>(null);
    const [timeEnergyImageUrl, setTimeEnergyImageUrl] = useState('');
    const [lWdImageUrl, setLWdImageUrl] = useState('');

    const {can: canProject} = useResourcePermission('project', projectId);
    const canAnnotate = canProject('annotation:create:assigned');
    const canCommit = canProject('commit:create:assigned');

    const branchName = searchParams.get('branch') || 'master';
    const q = searchParams.get('q') || '';
    const status = (searchParams.get('status') || 'all') as 'all' | 'labeled' | 'unlabeled' | 'draft';
    const sortValue = searchParams.get('sort') || 'createdAt:desc';
    const page = Number(searchParams.get('page') || 1);
    const pageSize = Number(searchParams.get('pageSize') || 24);
    const sampleId = searchParams.get('sampleId') || '';
    const [sortBy, sortOrder] = sortValue.split(':');

    const updateParams = useCallback((updates: Record<string, string | null>) => {
        const next = new URLSearchParams(searchParams);
        Object.entries(updates).forEach(([key, value]) => {
            if (value === null) {
                next.delete(key);
            } else {
                next.set(key, value);
            }
        });
        setSearchParams(next);
    }, [searchParams, setSearchParams]);

    const {samples, meta, loading: samplesLoading, reload: reloadSamples} = useProjectSampleList({
        projectId,
        datasetId,
        filters: {
            q: q || undefined,
            status,
            branchName,
            sortBy,
            sortOrder: sortOrder as 'asc' | 'desc',
            page,
            limit: pageSize,
        },
        enabled: !!projectId && !!datasetId,
    });

    const currentIndex = useMemo(() => {
        const index = samples.findIndex((s) => s.id === sampleId);
        if (index >= 0) return index;
        return samples.length > 0 ? 0 : -1;
    }, [samples, sampleId]);

    const currentSample = currentIndex >= 0 ? samples[currentIndex] : undefined;

    const annotationState = useAnnotationState<DualViewAnnotation>({initialAnnotations: []});

    useWorkspaceCommon({labels, annotationState});

    const labelMap = useMemo(() => {
        return new Map(labels.map((label) => [label.id, label]));
    }, [labels]);

    const canEditAnnotation = useCallback((annotation: Annotation) => {
        return canModifyAnnotation('annotation:create:assigned', annotation.annotatorId, user?.id);
    }, [user?.id]);

    const {
        loadSnapshot,
        syncActions,
    } = useAnnotationSync({
        projectId,
        sampleId: currentSample?.id,
        branchName,
        enabled: !!projectId && !!currentSample?.id,
    });

    const flushDraft = useCallback(async () => {
        if (!projectId || !currentSample?.id) return;
        try {
            await api.syncWorkingToDraft(projectId, currentSample.id, branchName);
        } catch (error) {
            console.warn('Failed to flush draft', error);
        }
    }, [projectId, currentSample?.id, branchName]);

    const flushDraftRef = useRef(flushDraft);

    useEffect(() => {
        flushDraftRef.current = flushDraft;
    }, [flushDraft]);

    useEffect(() => {
        if (!projectId) return;
        setLoadingMeta(true);
        Promise.all([
            api.getProjectLabels(projectId),
            api.getProjectBranches(projectId),
        ])
            .then(([labelData, branchData]) => {
                setLabels(labelData || []);
                setBranches(branchData || []);
            })
            .finally(() => setLoadingMeta(false));
    }, [projectId]);

    useEffect(() => {
        if (branches.length === 0) return;
        const active = branches.find((b) => b.name === branchName) || branches[0];
        if (active.name !== branchName) {
            updateParams({branch: active.name, page: '1'});
        }
    }, [branches, branchName, updateParams]);

    useEffect(() => {
        if (!sampleId && samples.length > 0) {
            const next = new URLSearchParams(searchParams);
            next.set('sampleId', samples[0].id);
            setSearchParams(next, {replace: true});
        }
    }, [samples, sampleId, searchParams, setSearchParams]);

    useEffect(() => {
        if (!pendingIndex || samples.length === 0) return;
        const target = pendingIndex === 'first' ? samples[0] : samples[samples.length - 1];
        const next = new URLSearchParams(searchParams);
        next.set('sampleId', target.id);
        setSearchParams(next, {replace: true});
        setPendingIndex(null);
    }, [pendingIndex, samples, searchParams, setSearchParams]);

    const mapDraftPayloadToAnnotations = useCallback((payload: AnnotationDraftPayload | null) => {
        if (!payload || payload.annotations.length === 0) {
            return [];
        }
        return payload.annotations.map((item) => {
            const groupId = item.groupId || generateUUID();
            const lineageId = item.lineageId || generateUUID();
            const itemId = item.id || lineageId;
            const label = labelMap.get(item.labelId);
            return {
                id: itemId,
                groupId: groupId,
                lineageId: lineageId,
                parentId: item.parentId ?? null,
                projectId: projectId || undefined,
                sampleId: currentSample?.id,
                labelId: item.labelId,
                labelName: label?.name,
                labelColor: label?.color,
                viewRole: item.viewRole,
                type: item.type,
                source: item.source,
                data: item.data,
                extra: item.extra,
                confidence: item.confidence,
                annotatorId: item.annotatorId,
            } as Annotation;
        });
    }, [labelMap, projectId, currentSample?.id]);

    const handleSyncActions = useCallback(async (actions: {
        type: 'add' | 'update' | 'delete';
        groupId: string;
        data?: AnnotationDraftItem
    }[]) => {
        try {
            const payload = await syncActions(actions);
            if (!payload) return null;
            return mapDraftPayloadToAnnotations(payload);
        } catch (error) {
            console.warn('Failed to sync annotations', error);
            return null;
        }
    }, [syncActions, mapDraftPayloadToAnnotations]);

    const {
        selectedAnnotationIds,
        canvasAnnotations,
        handleAnnotationSelect,
        handleAnnotationCreate,
        handleUpdateAnnotation,
        handleDeleteAnnotation,
        applyBaseAnnotations,
        hasAnyEditPermission,
    } = useFedoAnnotations({
        projectId,
        currentSampleId: currentSample?.id,
        currentUserId: user?.id,
        annotationState,
        t,
        hasAnyEditPermission: canAnnotate,
        canEditAnnotation,
        onSyncActions: handleSyncActions,
    });

    const applyDraftPayload = useCallback((payload: AnnotationDraftPayload | null) => {
        const mapped = mapDraftPayloadToAnnotations(payload);
        applyBaseAnnotations(mapped);
    }, [applyBaseAnnotations, mapDraftPayloadToAnnotations]);

    const loadAnnotations = useCallback(async () => {
        if (!projectId || !currentSample?.id) return;
        setAnnotationsLoading(true);
        try {
            const payload = await loadSnapshot();
            applyDraftPayload(payload);
        } finally {
            setAnnotationsLoading(false);
        }
    }, [projectId, currentSample?.id, loadSnapshot, applyDraftPayload]);

    useEffect(() => {
        loadAnnotations();
    }, [loadAnnotations]);

    useEffect(() => {
        return () => {
            flushDraftRef.current();
        };
    }, []);

    const handleSampleSelect = useCallback(async (index: number) => {
        if (index < 0 || index >= samples.length) return;
        await flushDraft();
        updateParams({sampleId: samples[index].id});
    }, [samples, flushDraft, updateParams]);

    const handleNext = useCallback(async () => {
        if (currentIndex < 0) return;
        if (currentIndex < samples.length - 1) {
            await flushDraft();
            updateParams({sampleId: samples[currentIndex + 1].id});
            return;
        }
        const totalPages = Math.max(1, Math.ceil(meta.total / (meta.limit || 1)));
        if (page < totalPages) {
            await flushDraft();
            setPendingIndex('first');
            updateParams({page: String(page + 1)});
        }
    }, [currentIndex, samples, meta.total, meta.limit, page, flushDraft, updateParams]);

    const handlePrev = useCallback(async () => {
        if (currentIndex < 0) return;
        if (currentIndex > 0) {
            await flushDraft();
            updateParams({sampleId: samples[currentIndex - 1].id});
            return;
        }
        if (page > 1) {
            await flushDraft();
            setPendingIndex('last');
            updateParams({page: String(page - 1)});
        }
    }, [currentIndex, samples, page, flushDraft, updateParams]);

    const handleSubmitAndNext = useCallback(async () => {
        await flushDraft();
        handleNext();
    }, [flushDraft, handleNext]);

    const handleCommit = useCallback(async (messageText: string) => {
        if (!projectId) return;
        setCommitLoading(true);
        try {
            await flushDraft();
            await api.commitAnnotationDrafts(projectId, {
                branchName,
                commitMessage: messageText,
            });
            setCommitModalOpen(false);
            reloadSamples();
            if (currentSample?.id) {
                await loadAnnotations();
            }
        } finally {
            setCommitLoading(false);
        }
    }, [projectId, branchName, reloadSamples, currentSample?.id, loadAnnotations, flushDraft]);

    useAnnotationShortcuts({
        currentTool: annotationState.currentTool,
        onToolChange: annotationState.setCurrentTool,
        onNext: handleNext,
        onPrev: handlePrev,
        onSubmit: handleSubmitAndNext,
        onUndo: annotationState.undo,
        onRedo: annotationState.redo,
        disabled: annotationsLoading,
    });

    const backToSamples = useCallback(() => {
        if (!projectId || !datasetId) return;
        const next = new URLSearchParams(searchParams);
        next.set('datasetId', datasetId);
        next.delete('sampleId');
        navigate(`/projects/${projectId}/samples?${next.toString()}`);
    }, [projectId, datasetId, searchParams, navigate]);

    useEffect(() => {
        let cancelled = false;

        const resolveAssetUrl = async (assetId?: string) => {
            if (!assetId) return '';
            try {
                const response = await fetch(`/api/v1/assets/${assetId}/download-url`, {method: 'GET'});
                if (!response.ok) return '';
                const data = await response.json();
                return (data.download_url || data.downloadUrl || '') as string;
            } catch (error) {
                return '';
            }
        };

        const loadImages = async () => {
            if (!currentSample) {
                setTimeEnergyImageUrl('');
                setLWdImageUrl('');
                return;
            }

            const assetGroup = currentSample.assetGroup || {};
            const timeEnergyAssetId = assetGroup.timeEnergyImage || assetGroup.time_energy_image;
            const lOmegadAssetId =
                assetGroup.lOmegadImage ||
                assetGroup.l_omegad_image ||
                assetGroup.lWdImage ||
                assetGroup.l_wd_image;

            let timeEnergyUrl =
                currentSample.metaInfo?.timeEnergyImageUrl ||
                currentSample.primaryAssetUrl ||
                '';
            let lOmegadUrl =
                currentSample.metaInfo?.lOmegadImageUrl ||
                currentSample.metaInfo?.lWdImageUrl ||
                '';

            if (!timeEnergyUrl) {
                timeEnergyUrl = await resolveAssetUrl(timeEnergyAssetId);
            }
            if (!lOmegadUrl) {
                lOmegadUrl = await resolveAssetUrl(lOmegadAssetId);
            }

            if (cancelled) return;
            setTimeEnergyImageUrl(timeEnergyUrl);
            setLWdImageUrl(lOmegadUrl);
        };

        loadImages();

        return () => {
            cancelled = true;
        };
    }, [currentSample]);

    const selectedAnnotation = annotationState.annotations.find(
        (a) => a.id === annotationState.selectedId
    );
    const currentMappedRegions = selectedAnnotation?.secondary?.regions || [];

    return (
        <div className="flex h-full flex-col gap-4">
            <div className="flex items-center gap-3">
                <Select
                    value={branchName}
                    onChange={async (value) => {
                        await flushDraft();
                        updateParams({branch: value, page: '1'});
                    }}
                    className="min-w-[160px]"
                    loading={loadingMeta}
                >
                    {branches.map((branch) => (
                        <Select.Option key={branch.id} value={branch.name}>
                            {branch.name}
                        </Select.Option>
                    ))}
                </Select>
                <div className="flex-1"/>
                <Select
                    value={sortValue}
                    onChange={async (value) => {
                        await flushDraft();
                        updateParams({sort: value, page: '1'});
                    }}
                    className="min-w-[200px]"
                >
                    <Select.Option value="createdAt:desc">Created (Newest)</Select.Option>
                    <Select.Option value="createdAt:asc">Created (Oldest)</Select.Option>
                    <Select.Option value="updatedAt:desc">Updated (Newest)</Select.Option>
                    <Select.Option value="updatedAt:asc">Updated (Oldest)</Select.Option>
                    <Select.Option value="name:asc">Name (A-Z)</Select.Option>
                    <Select.Option value="name:desc">Name (Z-A)</Select.Option>
                </Select>
            </div>

            <AnnotationWorkspaceLayout
                loading={loadingMeta || samplesLoading || annotationsLoading}
                dataset={dataset}
                samples={samples}
                labels={labels}
                currentIndex={Math.max(0, currentIndex)}
                currentSample={currentSample}
                annotationState={annotationState}
                isSyncing={false}
                isSyncReady
                onBack={backToSamples}
                toolbarExtraActions={
                    <button
                        className="px-3 py-1 text-sm font-medium text-white bg-[#1677ff] rounded disabled:opacity-50"
                        onClick={() => setCommitModalOpen(true)}
                        disabled={!canCommit}
                        type="button"
                    >
                        Commit Drafts
                    </button>
                }
                onSampleSelect={handleSampleSelect}
                onPrev={handlePrev}
                onNext={handleNext}
                onSubmit={handleSubmitAndNext}
                onAnnotationSelect={(id) => {
                    handleAnnotationSelect(id);
                    annotationState.setCurrentTool('select');
                }}
                onAnnotationDelete={handleDeleteAnnotation}
                onZoomIn={() => dualCanvasAreaRef.current?.zoomIn()}
                onZoomOut={() => dualCanvasAreaRef.current?.zoomOut()}
                onResetView={() => dualCanvasAreaRef.current?.resetView()}
                currentUserId={user?.id}
                canEditAnnotation={canEditAnnotation}
                hasAnyEditPermission={canAnnotate}
                canvasArea={
                    <DualCanvasArea
                        ref={dualCanvasAreaRef}
                        timeEnergyImageUrl={timeEnergyImageUrl}
                        lWdImageUrl={lWdImageUrl}
                        annotations={canvasAnnotations}
                        onAnnotationCreate={hasAnyEditPermission ? handleAnnotationCreate : undefined}
                        onAnnotationUpdate={handleUpdateAnnotation}
                        onAnnotationDelete={handleDeleteAnnotation}
                        currentTool={hasAnyEditPermission ? annotationState.currentTool : 'select'}
                        labelColor={annotationState.selectedLabel?.color || '#ff0000'}
                        selectedId={annotationState.selectedId}
                        selectedAnnotationIds={selectedAnnotationIds}
                        onSelect={handleAnnotationSelect}
                        currentMappedRegions={currentMappedRegions}
                        canEditAnnotation={canEditAnnotation}
                    />
                }
                renderAnnotationItem={(item: Annotation, index: number) => {
                    const isSelected = selectedAnnotationIds.has(item.id);
                    const canEdit = canEditAnnotation(item);
                    const isAutoGenerated = false;
                    const isMine = item.annotatorId && item.annotatorId === user?.id;

                    return (
                        <div
                            className={`cursor-pointer border-l-[4px] px-4 py-2 ${
                                isSelected ? 'bg-[#e6f7ff]' : 'bg-transparent'
                            } ${canEdit ? 'opacity-100' : 'opacity-70'}`}
                            style={{
                                borderLeftColor: isSelected ? item.labelColor || '#1890ff' : 'transparent',
                            }}
                            onClick={() => {
                                handleAnnotationSelect(item.id);
                                annotationState.setCurrentTool('select');
                            }}
                        >
                            <div className="flex items-center justify-between gap-2">
                                <div className="flex-1">
                                    <div className="flex items-center gap-2">
                    <span
                        className="inline-flex h-2.5 w-2.5 rounded-full"
                        style={{backgroundColor: item.labelColor || '#1890ff'}}
                    />
                                        <span className="text-sm">{item.labelName || 'Label'}</span>
                                        <span className="text-xs text-gray-500">#{index + 1}</span>
                                    </div>
                                    <div className="mt-1 text-[11px] text-[#888]">
                                        {isAutoGenerated
                                            ? t('workspace.annotationSource.auto')
                                            : isMine
                                                ? t('workspace.annotationSource.mine')
                                                : t('workspace.annotationSource.others')}
                                    </div>
                                </div>
                                {canEdit && !isAutoGenerated ? (
                                    <Button
                                        type="text"
                                        danger
                                        size="small"
                                        icon={<DeleteOutlined/>}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDeleteAnnotation(item.id);
                                        }}
                                    />
                                ) : null}
                            </div>
                        </div>
                    );
                }}
            />

            <CommitModal
                open={commitModalOpen}
                onCancel={() => setCommitModalOpen(false)}
                onCommit={handleCommit}
                loading={commitLoading}
            />
        </div>
    );
};

export default ProjectFedoWorkspace;
