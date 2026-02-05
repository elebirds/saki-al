import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { message, Select } from 'antd';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { AnnotationWorkspaceLayout } from '../../components/annotation';
import CommitModal from '../../components/project/CommitModal';
import {
  Annotation,
  AnnotationDraftItem,
  AnnotationDraftPayload,
  AnnotationRead,
  Dataset,
  ProjectBranch,
  ProjectLabel,
} from '../../types';
import { api } from '../../services/api';
import { useAuthStore } from '../../store/authStore';
import { useAnnotationState, useAnnotationShortcuts, useWorkspaceCommon } from '../../hooks';
import { useWorkingDraftPipeline } from '../../hooks/annotation/useWorkingDraftPipeline';
import { useProjectSampleList } from '../../hooks/project/useProjectSampleList';
import { useResourcePermission } from '../../hooks/permission/usePermission';
import { canModifyAnnotation } from '../../store/permissionStore';
import { generateUUID } from '../../utils/uuid';

export interface ProjectClassicWorkspaceProps {
  dataset: Dataset;
}

const ProjectClassicWorkspace: React.FC<ProjectClassicWorkspaceProps> = ({ dataset }) => {
  const { t } = useTranslation();
  const { projectId, datasetId } = useParams<{ projectId: string; datasetId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canvasRef = useRef<AnnotationCanvasRef>(null);
  const user = useAuthStore((state) => state.user);

  const [labels, setLabels] = useState<ProjectLabel[]>([]);
  const [branches, setBranches] = useState<ProjectBranch[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [headCommitId, setHeadCommitId] = useState<string | null>(null);
  const [commitModalOpen, setCommitModalOpen] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);
  const [annotationsLoading, setAnnotationsLoading] = useState(false);
  const [pendingIndex, setPendingIndex] = useState<'first' | 'last' | null>(null);

  const { can: canProject } = useResourcePermission('project', projectId);
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

  const { samples, meta, loading: samplesLoading, reload: reloadSamples } = useProjectSampleList({
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

  const annotationState = useAnnotationState<Annotation>({ initialAnnotations: [] });
  const {
    setAnnotations,
    setHistory,
    setHistoryIndex,
    setSelectedId,
  } = annotationState;

  useWorkspaceCommon({ labels, annotationState });

  const labelMap = useMemo(() => {
    return new Map(labels.map((label) => [label.id, label]));
  }, [labels]);

  const buildDraftPayload = useCallback((annotations: Annotation[]): AnnotationDraftPayload => {
    const items: AnnotationDraftItem[] = annotations.map((ann) => ({
      projectId: projectId || undefined,
      sampleId: currentSample?.id,
      labelId: ann.labelId,
      syncId: ann.syncId || ann.id,
      parentId: ann.parentId ?? null,
      viewRole: ann.viewRole || 'main',
      type: ann.type,
      source: ann.source || 'manual',
      data: ann.data,
      extra: ann.extra || {},
      confidence: ann.confidence ?? 1,
      annotatorId: ann.annotatorId ?? user?.id ?? null,
    }));
    return {
      annotations: items,
      meta: {},
    };
  }, [projectId, currentSample?.id, user?.id]);

  const { syncDraft } = useWorkingDraftPipeline({
    projectId,
    sampleId: currentSample?.id,
    branchName,
    annotations: annotationState.annotations,
    buildPayload: buildDraftPayload,
    enabled: !!projectId && !!currentSample?.id,
  });
  const syncDraftRef = useRef(syncDraft);

  useEffect(() => {
    syncDraftRef.current = syncDraft;
  }, [syncDraft]);

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
      updateParams({ branch: active.name, page: '1' });
    }
    setHeadCommitId(active.headCommitId || null);
  }, [branches, branchName, updateParams]);

  useEffect(() => {
    if (!sampleId && samples.length > 0) {
      const next = new URLSearchParams(searchParams);
      next.set('sampleId', samples[0].id);
      setSearchParams(next, { replace: true });
    }
  }, [samples, sampleId, searchParams, setSearchParams]);

  useEffect(() => {
    if (!pendingIndex || samples.length === 0) return;
    const target = pendingIndex === 'first' ? samples[0] : samples[samples.length - 1];
    const next = new URLSearchParams(searchParams);
    next.set('sampleId', target.id);
    setSearchParams(next, { replace: true });
    setPendingIndex(null);
  }, [pendingIndex, samples, searchParams, setSearchParams]);

  const applyDraftPayload = useCallback((payload: AnnotationDraftPayload | null) => {
    if (!payload || payload.annotations.length === 0) {
      setAnnotations([]);
      setHistory([[]]);
      setHistoryIndex(0);
      setSelectedId(null);
      return;
    }
    const mapped = payload.annotations.map((item) => {
      const syncId = item.syncId || generateUUID();
      const label = labelMap.get(item.labelId);
      return {
        id: syncId,
        syncId: syncId,
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
    setAnnotations(mapped);
    setHistory([mapped]);
    setHistoryIndex(0);
    setSelectedId(null);
  }, [labelMap, projectId, currentSample?.id, setAnnotations, setHistory, setHistoryIndex, setSelectedId]);

  const applyCommitAnnotations = useCallback((annotations: AnnotationRead[]) => {
    const mapped = annotations.map((ann) => {
      const syncId = ann.syncId || ann.id;
      const label = labelMap.get(ann.labelId);
      return {
        id: syncId,
        syncId: syncId,
        parentId: ann.id,
        projectId: ann.projectId,
        sampleId: ann.sampleId,
        labelId: ann.labelId,
        labelName: label?.name,
        labelColor: label?.color,
        viewRole: ann.viewRole,
        type: ann.type,
        source: ann.source,
        data: ann.data,
        extra: ann.extra,
        confidence: ann.confidence,
        annotatorId: ann.annotatorId,
      } as Annotation;
    });
    setAnnotations(mapped);
    setHistory([mapped]);
    setHistoryIndex(0);
    setSelectedId(null);
  }, [labelMap, setAnnotations, setHistory, setHistoryIndex, setSelectedId]);

  const loadAnnotations = useCallback(async () => {
    if (!projectId || !currentSample?.id) return;
    setAnnotationsLoading(true);
    try {
      const working = await api.getWorkingAnnotations(projectId, currentSample.id, branchName);
      if (working && working.annotations && working.annotations.length > 0) {
        applyDraftPayload(working);
        return;
      }

      const drafts = await api.listAnnotationDrafts(projectId, branchName, currentSample.id);
      if (drafts.length > 0) {
        applyDraftPayload(drafts[0].payload);
        return;
      }

      if (headCommitId) {
        const committed = await api.getAnnotationsAtCommit(headCommitId, currentSample.id);
        applyCommitAnnotations(committed);
        return;
      }

      applyDraftPayload({ annotations: [] });
    } finally {
      setAnnotationsLoading(false);
    }
  }, [projectId, currentSample?.id, branchName, headCommitId, applyDraftPayload, applyCommitAnnotations]);

  useEffect(() => {
    loadAnnotations();
  }, [loadAnnotations]);

  useEffect(() => {
    return () => {
      syncDraftRef.current();
    };
  }, []);

  const canEditAnnotation = useCallback((annotation: Annotation) => {
    return canModifyAnnotation('annotation:create:assigned', annotation.annotatorId, user?.id);
  }, [user?.id]);

  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    if (!canAnnotate) {
      message.warning(t('workspace.noEditPermission'));
      return;
    }

    if (!annotationState.selectedLabel) {
      message.warning(t('workspace.noLabelSelected'));
      return;
    }

    if (!currentSample?.id) return;

    const newId = generateUUID();
    const newAnn: Annotation = {
      id: newId,
      syncId: newId,
      projectId: projectId || undefined,
      sampleId: currentSample.id,
      labelId: annotationState.selectedLabel.id,
      labelName: annotationState.selectedLabel.name,
      labelColor: annotationState.selectedLabel.color,
      type: event.type,
      source: 'manual',
      data: {
        x: event.bbox.x,
        y: event.bbox.y,
        width: event.bbox.width,
        height: event.bbox.height,
        rotation: event.bbox.rotation,
      },
      extra: {},
      confidence: 1,
      annotatorId: user?.id,
    };

    annotationState.handleAnnotationCreate(newAnn);
  }, [canAnnotate, annotationState, currentSample?.id, projectId, user?.id, t]);

  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSample?.id) return;
    if (!canEditAnnotation(updatedAnn)) {
      message.warning(t('workspace.cannotEditOthersAnnotation'));
      return;
    }
    annotationState.handleAnnotationUpdate(updatedAnn);
  }, [currentSample?.id, canEditAnnotation, annotationState, t]);

  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSample?.id) return;
    const ann = annotationState.annotations.find(a => a.id === id);
    if (ann && !canEditAnnotation(ann)) {
      message.warning(t('workspace.cannotDeleteOthersAnnotation'));
      return;
    }
    annotationState.handleAnnotationDelete(id);
  }, [currentSample?.id, annotationState, canEditAnnotation, t]);

  const handleSampleSelect = useCallback(async (index: number) => {
    if (index < 0 || index >= samples.length) return;
    await syncDraft();
    updateParams({ sampleId: samples[index].id });
  }, [samples, syncDraft, updateParams]);

  const handleNext = useCallback(async () => {
    if (currentIndex < 0) return;
    if (currentIndex < samples.length - 1) {
      await syncDraft();
      updateParams({ sampleId: samples[currentIndex + 1].id });
      return;
    }
    const totalPages = Math.max(1, Math.ceil(meta.total / (meta.limit || 1)));
    if (page < totalPages) {
      await syncDraft();
      setPendingIndex('first');
      updateParams({ page: String(page + 1) });
    }
  }, [currentIndex, samples, meta.total, meta.limit, page, syncDraft, updateParams]);

  const handlePrev = useCallback(async () => {
    if (currentIndex < 0) return;
    if (currentIndex > 0) {
      await syncDraft();
      updateParams({ sampleId: samples[currentIndex - 1].id });
      return;
    }
    if (page > 1) {
      await syncDraft();
      setPendingIndex('last');
      updateParams({ page: String(page - 1) });
    }
  }, [currentIndex, samples, page, syncDraft, updateParams]);

  const handleSubmitAndNext = useCallback(async () => {
    await syncDraft();
    handleNext();
  }, [syncDraft, handleNext]);

  const handleCommit = useCallback(async (messageText: string) => {
    if (!projectId) return;
    setCommitLoading(true);
    try {
      const result = await api.commitAnnotationDrafts(projectId, {
        branchName,
        commitMessage: messageText,
      });
      if (result?.commitId) {
        setHeadCommitId(result.commitId);
      }
      setCommitModalOpen(false);
      reloadSamples();
      if (currentSample?.id) {
        await loadAnnotations();
      }
    } finally {
      setCommitLoading(false);
    }
  }, [projectId, branchName, reloadSamples, currentSample?.id, loadAnnotations]);

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

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center gap-3">
        <Select
          value={branchName}
          onChange={async (value) => {
            await syncDraft();
            updateParams({ branch: value, page: '1' });
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
        <div className="flex-1" />
        <Select
          value={sortValue}
          onChange={async (value) => {
            await syncDraft();
            updateParams({ sort: value, page: '1' });
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
          annotationState.setSelectedId(id);
          annotationState.setCurrentTool('select');
        }}
        onAnnotationDelete={handleDeleteAnnotation}
        onZoomIn={() => canvasRef.current?.zoomIn()}
        onZoomOut={() => canvasRef.current?.zoomOut()}
        onResetView={() => canvasRef.current?.resetView()}
        currentUserId={user?.id}
        canEditAnnotation={canEditAnnotation}
        hasAnyEditPermission={canAnnotate}
        canvasArea={
          <AnnotationCanvas
            ref={canvasRef}
            imageUrl={currentSample?.primaryAssetUrl || ''}
            annotations={annotationState.annotations}
            onAnnotationCreate={canAnnotate ? handleAnnotationCreate : undefined}
            onAnnotationUpdate={handleUpdateAnnotation}
            onAnnotationDelete={handleDeleteAnnotation}
            currentTool={canAnnotate ? annotationState.currentTool : 'select'}
            labelColor={annotationState.selectedLabel?.color || '#ff0000'}
            selectedId={annotationState.selectedId}
            onSelect={annotationState.setSelectedId}
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

export default ProjectClassicWorkspace;
