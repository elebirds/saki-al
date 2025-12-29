/**
 * useAnnotationSync Hook
 * 
 * 统一管理标注同步功能。
 * - Classic: 调用后端 sync 接口，但后台不进行任何操作，直接返回
 * - FEDO: 调用后端 sync 接口，后台计算对应点集并生成对应侧的相应标注
 */

import { useState, useCallback } from 'react';
import { api } from '../services/api';
import { SyncAction, SyncResponse } from '../types';

export interface UseAnnotationSyncOptions {
  /** 是否启用同步（默认 true） */
  enabled?: boolean;
}

export interface UseAnnotationSyncReturn {
  /** 是否正在同步中 */
  isSyncing: boolean;
  /** 同步状态是否就绪 */
  isSyncReady: boolean;
  /** 执行同步操作 */
  sync: (sampleId: string, actions: SyncAction[]) => Promise<SyncResponse>;
}

export function useAnnotationSync(
  options: UseAnnotationSyncOptions = {}
): UseAnnotationSyncReturn {
  const { enabled = true } = options;
  const [isSyncing, setIsSyncing] = useState(false);
  const [isSyncReady, setIsSyncReady] = useState(true);

  const sync = useCallback(async (sampleId: string, actions: SyncAction[]): Promise<SyncResponse> => {
    if (!enabled || actions.length === 0) {
      return {
        sampleId,
        results: [],
        ready: true,
      };
    }

    setIsSyncing(true);
    setIsSyncReady(false);

    try {
      const response = await api.syncAnnotations(sampleId, actions);
      setIsSyncReady(true);
      return response;
    } catch (error) {
      console.error('Sync failed:', error);
      setIsSyncReady(true);
      throw error;
    } finally {
      setIsSyncing(false);
    }
  }, [enabled]);

  return {
    isSyncing,
    isSyncReady,
    sync,
  };
}

