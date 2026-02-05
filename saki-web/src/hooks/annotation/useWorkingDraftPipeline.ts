import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import { Annotation, AnnotationDraftPayload } from '../../types';

export interface UseWorkingDraftPipelineOptions {
  projectId?: string;
  sampleId?: string;
  branchName?: string;
  annotations: Annotation[];
  enabled?: boolean;
  debounceMs?: number;
  buildPayload: (annotations: Annotation[]) => AnnotationDraftPayload;
}

export interface UseWorkingDraftPipelineReturn {
  isSavingWorking: boolean;
  saveWorkingNow: () => Promise<void>;
  syncDraft: () => Promise<void>;
}

export function useWorkingDraftPipeline(
  options: UseWorkingDraftPipelineOptions
): UseWorkingDraftPipelineReturn {
  const {
    projectId,
    sampleId,
    branchName,
    annotations,
    enabled = true,
    debounceMs = 600,
    buildPayload,
  } = options;

  const [isSavingWorking, setIsSavingWorking] = useState(false);
  const timerRef = useRef<number | null>(null);
  const payloadRef = useRef<AnnotationDraftPayload | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const saveWorkingNow = useCallback(async () => {
    if (!enabled || !projectId || !sampleId) return;
    const payload = payloadRef.current || buildPayload(annotations);
    if (isMountedRef.current) {
      setIsSavingWorking(true);
    }
    try {
      await api.upsertWorkingAnnotations(projectId, sampleId, {
        ...payload,
        branchName,
      });
    } catch (error) {
      console.warn('Failed to save working annotations', error);
    } finally {
      if (isMountedRef.current) {
        setIsSavingWorking(false);
      }
    }
  }, [enabled, projectId, sampleId, branchName, buildPayload, annotations]);

  const syncDraft = useCallback(async () => {
    if (!enabled || !projectId || !sampleId) return;
    await saveWorkingNow();
    try {
      await api.syncWorkingToDraft(projectId, sampleId, branchName);
    } catch (error) {
      console.warn('Failed to sync working to draft', error);
    }
  }, [enabled, projectId, sampleId, branchName, saveWorkingNow]);

  useEffect(() => {
    if (!enabled || !projectId || !sampleId) return;
    payloadRef.current = buildPayload(annotations);
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      saveWorkingNow();
    }, debounceMs);

    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [annotations, enabled, projectId, sampleId, branchName, debounceMs, buildPayload, saveWorkingNow]);

  return {
    isSavingWorking,
    saveWorkingNow,
    syncDraft,
  };
}
