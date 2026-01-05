/**
 * useClassicAnnotations Hook
 * 
 * 封装 Classic 标注工作空间的标注处理逻辑
 */

import { useEffect, useCallback } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { Annotation, AnnotationType, SyncAction } from '../types';
import { UseAnnotationStateReturn } from './useAnnotationState';
import { UseAnnotationSyncReturn } from './useAnnotationSync';
import { generateUUID } from '../utils/uuid';

export interface UseClassicAnnotationsOptions {
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 标注状态管理 */
  annotationState: UseAnnotationStateReturn<Annotation>;
  /** 同步 hook */
  sync: UseAnnotationSyncReturn['sync'];
  /** 翻译函数 */
  t: (key: string) => string;
}

export interface UseClassicAnnotationsReturn {
  /** 创建标注 */
  handleAnnotationCreate: (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => Promise<void>;
  /** 更新标注 */
  handleUpdateAnnotation: (updatedAnn: Annotation) => Promise<void>;
  /** 删除标注 */
  handleDeleteAnnotation: (id: string) => Promise<void>;
}

/**
 * 使用 Classic 标注处理 hook
 */
export function useClassicAnnotations(
  options: UseClassicAnnotationsOptions
): UseClassicAnnotationsReturn {
  const {
    currentSampleId,
    annotationState,
    sync,
    t,
  } = options;

  // 加载当前样本的标注
  useEffect(() => {
    if (currentSampleId) {
      api.getSampleAnnotations(currentSampleId).then((response) => {
        // 后端已经转换为左上角坐标，直接使用
        // 重置历史记录
        annotationState.resetHistory();
        // 设置初始标注并添加到历史记录
        if (response.annotations.length > 0) {
          annotationState.addToHistory(response.annotations);
        } else {
          annotationState.setAnnotations([]);
        }
      });
    }
  }, [currentSampleId, annotationState]);

  // 创建标注时调用 sync
  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    if (!annotationState.selectedLabel) {
      message.warning(t('workspace.noLabelSelected'));
      return;
    }

    if (!currentSampleId) return;

    // 使用UUID格式生成ID，与后端生成的ID格式保持一致
    const newId = generateUUID();
    const newAnn: Annotation = {
      id: newId,
      sampleId: currentSampleId,
      labelId: annotationState.selectedLabel.id,
      labelName: annotationState.selectedLabel.name,
      labelColor: annotationState.selectedLabel.color,
      type: event.type as AnnotationType,
      source: 'manual',
      data: {
        x: event.bbox.x,
        y: event.bbox.y,
        width: event.bbox.width,
        height: event.bbox.height,
        rotation: event.bbox.rotation,
      },
      extra: {},
    };

    // 直接使用前端坐标（左上角），后端会自动转换
    const syncAction: SyncAction = {
      action: 'create',
      annotationId: newId,
      labelId: annotationState.selectedLabel.id,
      type: event.type as AnnotationType,
      data: newAnn.data,
      extra: {},
    };

    try {
      await sync(currentSampleId, [syncAction]);
      // Classic 模式下，sync 不返回生成的标注，直接使用创建的标注
      annotationState.handleAnnotationCreate(newAnn);
    } catch (error) {
      console.error('Sync failed:', error);
      // 即使 sync 失败，也创建标注（降级处理）
      annotationState.handleAnnotationCreate(newAnn);
    }
  }, [currentSampleId, annotationState, sync, t]);

  // 更新标注时调用 sync
  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSampleId) return;

    // 直接使用前端坐标（左上角），后端会自动转换
    const syncAction: SyncAction = {
      action: 'update',
      annotationId: updatedAnn.id,
      labelId: updatedAnn.labelId,
      type: updatedAnn.type,
      data: updatedAnn.data,
      extra: updatedAnn.extra || {},
    };

    try {
      await sync(currentSampleId, [syncAction]);
      annotationState.handleAnnotationUpdate(updatedAnn);
    } catch (error) {
      console.error('Sync failed:', error);
      annotationState.handleAnnotationUpdate(updatedAnn);
    }
  }, [currentSampleId, annotationState, sync]);

  // 删除标注时调用 sync
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSampleId) return;

    const syncAction: SyncAction = {
      action: 'delete',
      annotationId: id,
      extra: {},
    };

    try {
      await sync(currentSampleId, [syncAction]);
      annotationState.handleAnnotationDelete(id);
    } catch (error) {
      console.error('Sync failed:', error);
      annotationState.handleAnnotationDelete(id);
    }
  }, [currentSampleId, annotationState, sync]);

  return {
    handleAnnotationCreate,
    handleUpdateAnnotation,
    handleDeleteAnnotation,
  };
}

