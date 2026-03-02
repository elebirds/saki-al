import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button, message} from 'antd';
import {useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {AnnotationWorkspaceLayout, DualCanvasArea, DualCanvasAreaRef} from '../../components/annotation';
import CommitModal from '../../components/project/CommitModal';
import {
    Annotation,
    AnnotationDraftItem,
    AnnotationDraftPayload,
    Dataset,
    DetectionAnnotationType,
    DualViewAnnotation,
    ProjectLabel,
} from '../../types';
import {api} from '../../services/api';
import {useAuthStore} from '../../store/authStore';
import {useAnnotationShortcuts, useAnnotationState, useAnnotationSync, useWorkspaceCommon} from '../../hooks';
import {useProjectSampleList} from '../../hooks/project/useProjectSampleList';
import {useResourcePermission} from '../../hooks/permission/usePermission';
import {canModifyAnnotation} from '../../store/permissionStore';
import {attrsFromAnnotationLike, hydrateDraftPayload} from '../../utils/annotationGeometry';
import {generateUUID} from '../../utils/uuid';
import {useFedoAnnotations} from '../../hooks/annotation/useFedoAnnotations';
import {parseProjectSampleSort} from '../../utils/projectSampleSort';

export interface ProjectFedoWorkspaceProps {
    dataset: Dataset;
    enabledAnnotationTypes: DetectionAnnotationType[];
}

const ProjectFedoWorkspace: React.FC<ProjectFedoWorkspaceProps> = ({dataset, enabledAnnotationTypes}) => {
    const {t} = useTranslation();
    const {projectId, datasetId} = useParams<{ projectId: string; datasetId: string }>();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const dualCanvasAreaRef = useRef<DualCanvasAreaRef>(null);
    const user = useAuthStore((state) => state.user);

    const [labels, setLabels] = useState<ProjectLabel[]>([]);
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
    const page = Number(searchParams.get('page') || 1);
    const pageSize = Number(searchParams.get('pageSize') || 24);
    const sampleId = searchParams.get('sampleId') || '';
    const parsedSort = parseProjectSampleSort(searchParams.get('sort'));
    const sortBy = parsedSort.sortBy;
    const sortOrder = parsedSort.sortOrder;
    const runtimeScope = (searchParams.get('runtimeScope') || '') as '' | 'round_missing_labels';
    const runtimeLoopId = searchParams.get('runtimeLoopId') || '';
    const runtimeRoundId = searchParams.get('runtimeRoundId') || '';

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
            runtimeScope: runtimeScope || undefined,
            runtimeLoopId: runtimeLoopId || undefined,
            runtimeRoundId: runtimeRoundId || undefined,
        },
        enabled: !!projectId && !!datasetId,
    });

    const currentIndex = useMemo(() => {
        const index = samples.findIndex((s) => s.id === sampleId);
        if (index >= 0) return index;
        return samples.length > 0 ? 0 : -1;
    }, [samples, sampleId]);

    const currentSample = currentIndex >= 0 ? samples[currentIndex] : undefined;

    const annotationState = useAnnotationState<DualViewAnnotation>({
        initialAnnotations: [],
        enabledTools: enabledAnnotationTypes,
    });

    useWorkspaceCommon({labels, annotationState});

    const labelMap = useMemo(() => {
        return new Map(labels.map((label) => [label.id, label]));
    }, [labels]);

    const canEditAnnotation = useCallback((_annotation: Annotation) => {
        return canModifyAnnotation('annotation:create:assigned', 'project', projectId);
    }, [projectId]);

    const {
        loadSnapshot,
        syncActions,
    } = useAnnotationSync({
        projectId,
        sampleId: currentSample?.id,
        branchName,
        enabled: !!projectId && !!currentSample?.id,
    });

    const flushDraft = useCallback(async (options?: { reviewEmpty?: boolean }) => {
        if (!projectId || !currentSample?.id) return;
        try {
            await api.syncWorkingToDraft(
                projectId,
                currentSample.id,
                branchName,
                options?.reviewEmpty === true
            );
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
        api.getProjectLabels(projectId)
            .then((labelData) => {
                setLabels(labelData || []);
            })
            .finally(() => setLoadingMeta(false));
    }, [projectId]);

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
        const normalized = hydrateDraftPayload(payload);
        if (!normalized || normalized.annotations.length === 0) {
            return [];
        }
        return normalized.annotations.map((item) => {
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
                geometry: item.geometry,
                attrs: item.attrs || {},
                confidence: item.confidence,
                annotatorId: item.annotatorId,
            } as Annotation;
        });
    }, [labelMap, projectId, currentSample?.id]);

    const buildDraftItem = useCallback((annotation: Annotation): AnnotationDraftItem => ({
        id: annotation.id,
        projectId: projectId || undefined,
        sampleId: currentSample?.id,
        labelId: annotation.labelId,
        groupId: annotation.groupId || annotation.id,
        lineageId: annotation.lineageId || annotation.id,
        parentId: annotation.parentId ?? null,
        viewRole: annotation.viewRole || 'main',
        type: annotation.type,
        source: annotation.source || 'manual',
        geometry: annotation.geometry,
        attrs: attrsFromAnnotationLike(annotation),
        confidence: annotation.confidence ?? 1,
        annotatorId: annotation.annotatorId ?? user?.id ?? null,
    }), [projectId, currentSample?.id, user?.id]);

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
        enabledAnnotationTypes,
        canEditAnnotation,
        onSyncActions: handleSyncActions,
    });

    const applyDraftPayload = useCallback((payload: AnnotationDraftPayload | null) => {
        const mapped = mapDraftPayloadToAnnotations(payload);
        applyBaseAnnotations(mapped);
    }, [applyBaseAnnotations, mapDraftPayloadToAnnotations]);

    const syncAndApplyWorkspace = useCallback(async (actions: {
        type: 'add' | 'update' | 'delete';
        groupId: string;
        data?: AnnotationDraftItem;
    }[]) => {
        const updated = await handleSyncActions(actions);
        if (updated) {
            applyBaseAnnotations(updated);
        }
    }, [handleSyncActions, applyBaseAnnotations]);

    const pendingModelGroups = useMemo(() => {
        const map = new Map<string, Annotation>();
        canvasAnnotations.forEach((ann) => {
            if (String(ann.source || '').toLowerCase() !== 'model') return;
            const groupId = ann.groupId || ann.id;
            if (!groupId || map.has(groupId)) return;
            map.set(groupId, ann);
        });
        return map;
    }, [canvasAnnotations]);

    const selectedModelAnnotation = useMemo(() => {
        if (!annotationState.selectedId) return null;
        const row = canvasAnnotations.find((ann) => ann.id === annotationState.selectedId);
        if (!row) return null;
        return String(row.source || '').toLowerCase() === 'model' ? row : null;
    }, [annotationState.selectedId, canvasAnnotations]);

    const handleConfirmSelectedModel = useCallback(async () => {
        if (!selectedModelAnnotation) {
            message.warning(t('annotation.workspace.noPendingModelSelected'));
            return;
        }
        const groupId = selectedModelAnnotation.groupId || selectedModelAnnotation.id;
        await syncAndApplyWorkspace([{
            type: 'update',
            groupId,
            data: buildDraftItem({
                ...selectedModelAnnotation,
                groupId,
                source: 'confirmed_model',
            }),
        }]);
        message.success(t('annotation.workspace.confirmSelectedDone'));
    }, [selectedModelAnnotation, syncAndApplyWorkspace, buildDraftItem, t]);

    const handleConfirmAllModel = useCallback(async () => {
        if (pendingModelGroups.size === 0) {
            message.warning(t('annotation.workspace.noPendingModelAnnotations'));
            return;
        }
        const actions = Array.from(pendingModelGroups.entries()).map(([groupId, ann]) => ({
            type: 'update' as const,
            groupId,
            data: buildDraftItem({
                ...ann,
                groupId,
                source: 'confirmed_model',
            }),
        }));
        await syncAndApplyWorkspace(actions);
        message.success(t('annotation.workspace.confirmAllDone', {count: actions.length}));
    }, [pendingModelGroups, syncAndApplyWorkspace, buildDraftItem, t]);

    const handleClearUnconfirmedModel = useCallback(async () => {
        if (pendingModelGroups.size === 0) {
            message.warning(t('annotation.workspace.noPendingModelAnnotations'));
            return;
        }
        const actions = Array.from(pendingModelGroups.keys()).map((groupId) => ({
            type: 'delete' as const,
            groupId,
        }));
        await syncAndApplyWorkspace(actions);
        message.success(t('annotation.workspace.clearUnconfirmedDone', {count: actions.length}));
    }, [pendingModelGroups, syncAndApplyWorkspace, t]);

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

    const handleSamplePageChange = useCallback(async (nextPage: number) => {
        if (nextPage === page) return;
        await flushDraft();
        setPendingIndex('first');
        updateParams({
            page: String(nextPage),
            sampleId: null,
        });
    }, [page, flushDraft, updateParams]);

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
        const shouldReviewEmpty = annotationState.annotations.length === 0;
        await flushDraft({reviewEmpty: shouldReviewEmpty});
        handleNext();
    }, [annotationState.annotations.length, flushDraft, handleNext]);

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
        enabledTools: enabledAnnotationTypes,
        onNext: handleNext,
        onPrev: handlePrev,
        onSubmit: handleSubmitAndNext,
        onUndo: annotationState.undo,
        onRedo: annotationState.redo,
        disabled: annotationsLoading,
    });

    const backToSamples = useCallback(async () => {
        if (!projectId || !datasetId) return;
        await flushDraft();
        const next = new URLSearchParams(searchParams);
        next.set('datasetId', datasetId);
        next.delete('sampleId');
        navigate(`/projects/${projectId}/samples?${next.toString()}`);
    }, [projectId, datasetId, searchParams, navigate, flushDraft]);

    useEffect(() => {
        let cancelled = false;

        const resolveAssetUrl = async (assetId?: string) => {
            if (!assetId) return '';
            try {
                const data = await api.getAssetDownloadUrl(assetId, 1, datasetId);
                return (data.downloadUrl || '') as string;
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
            <AnnotationWorkspaceLayout
                loading={loadingMeta || samplesLoading || annotationsLoading}
                dataset={dataset}
                samples={samples}
                labels={labels}
                currentIndex={Math.max(0, currentIndex)}
                currentSample={currentSample}
                samplePage={page}
                samplePageSize={meta.limit || pageSize}
                sampleTotal={meta.total}
                sampleOffset={meta.offset}
                annotationState={annotationState}
                selectedIds={selectedAnnotationIds}
                enabledAnnotationTypes={enabledAnnotationTypes}
                isSyncing={false}
                isSyncReady
                onBack={backToSamples}
                toolbarExtraActions={
                    <>
                        <Button
                            onClick={() => void handleConfirmSelectedModel()}
                            disabled={!canAnnotate || !selectedModelAnnotation}
                        >
                            {t('annotation.workspace.confirmSelected')}
                        </Button>
                        <Button
                            onClick={() => void handleConfirmAllModel()}
                            disabled={!canAnnotate || pendingModelGroups.size === 0}
                        >
                            {t('annotation.workspace.confirmAll')}
                        </Button>
                        <Button
                            danger
                            onClick={() => void handleClearUnconfirmedModel()}
                            disabled={!canAnnotate || pendingModelGroups.size === 0}
                        >
                            {t('annotation.workspace.clearUnconfirmed')}
                        </Button>
                        <Button
                            type="primary"
                            onClick={() => setCommitModalOpen(true)}
                            disabled={!canCommit}
                        >
                            {t('annotation.workspace.commitDrafts')}
                        </Button>
                    </>
                }
                onSampleSelect={handleSampleSelect}
                onSamplePageChange={handleSamplePageChange}
                onPrev={handlePrev}
                onNext={handleNext}
                onSubmit={handleSubmitAndNext}
                submitLabel={
                    annotationState.annotations.length === 0
                        ? t('annotation.workspace.submitNextEmpty')
                        : t('annotation.workspace.submitNext')
                }
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
