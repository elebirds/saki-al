import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import {
  AnnotationDraftPayload,
  AnnotationSyncActionItem,
  AnnotationSyncResponse,
} from '../../types';

function convertKeysToCamel<T>(obj: unknown): T {
  if (Array.isArray(obj)) {
    return obj.map(item => convertKeysToCamel(item)) as T;
  }
  if (obj !== null && typeof obj === 'object') {
    return Object.keys(obj as object).reduce((result, key) => {
      const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
      (result as Record<string, unknown>)[camelKey] = convertKeysToCamel(
        (obj as Record<string, unknown>)[key]
      );
      return result;
    }, {} as T);
  }
  return obj as T;
}

function extractConflictPayload(error: unknown): AnnotationSyncResponse | null {
  const anyError = error as { originalError?: any; statusCode?: number };
  if (anyError?.statusCode !== 409) return null;
  const raw = anyError.originalError?.response?.data;
  if (!raw) return null;
  const data = raw.data ?? raw;
  return convertKeysToCamel<AnnotationSyncResponse>(data);
}

export interface UseAnnotationSyncOptions {
  projectId?: string;
  sampleId?: string;
  branchName?: string;
  enabled?: boolean;
}

export interface UseAnnotationSyncReturn {
  baseCommitId: string | null;
  seqId: number;
  isSyncing: boolean;
  loadSnapshot: () => Promise<AnnotationDraftPayload | null>;
  syncActions: (
    actions: AnnotationSyncActionItem[],
    meta?: Record<string, any>
  ) => Promise<AnnotationDraftPayload | null>;
}

export function useAnnotationSync(
  options: UseAnnotationSyncOptions
): UseAnnotationSyncReturn {
  const {
    projectId,
    sampleId,
    branchName = 'master',
    enabled = true,
  } = options;

  const [isSyncing, setIsSyncing] = useState(false);
  const [seqId, setSeqId] = useState(0);
  const [baseCommitId, setBaseCommitId] = useState<string | null>(null);
  const seqRef = useRef(0);
  const baseCommitRef = useRef<string | null>(null);

  useEffect(() => {
    seqRef.current = 0;
    baseCommitRef.current = null;
    setSeqId(0);
    setBaseCommitId(null);
  }, [projectId, sampleId, branchName]);

  const applyResponse = useCallback((response: AnnotationSyncResponse) => {
    seqRef.current = response.currentSeqId || 0;
    baseCommitRef.current = response.baseCommitId || null;
    setSeqId(seqRef.current);
    setBaseCommitId(baseCommitRef.current);
    return response.payload || null;
  }, []);

  const syncActions = useCallback(async (
    actions: AnnotationSyncActionItem[],
    meta?: Record<string, any>
  ) => {
    if (!enabled || !projectId || !sampleId) return null;
    setIsSyncing(true);
    try {
      const response = await api.syncAnnotation(projectId, sampleId, {
        baseCommitId: baseCommitRef.current,
        lastSeqId: seqRef.current,
        branchName,
        actions,
        meta,
      });
      return applyResponse(response);
    } catch (error) {
      const conflict = extractConflictPayload(error);
      if (conflict) {
        return applyResponse(conflict);
      }
      throw error;
    } finally {
      setIsSyncing(false);
    }
  }, [enabled, projectId, sampleId, branchName, applyResponse]);

  const loadSnapshot = useCallback(async () => {
    return syncActions([]);
  }, [syncActions]);

  return {
    baseCommitId,
    seqId,
    isSyncing,
    loadSnapshot,
    syncActions,
  };
}
