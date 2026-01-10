/**
 * useClassicAnnotations Hook
 * 
 * 封装 Classic 标注工作空间的标注处理逻辑
 */

import { useEffect, useCallback, useState, useMemo } from 'react';
import { message } from 'antd';
import { api } from '../../services/api';
import { Annotation, AnnotationType, SyncAction } from '../../types';
import { UseAnnotationStateReturn } from './useAnnotationState';
import { UseAnnotationSyncReturn } from './useAnnotationSync';
import { generateUUID } from '../../utils/uuid';

/** 权限范围类型 */
export type AccessScope = 'all' | 'assigned' | 'self' | 'none';

export interface UseClassicAnnotationsOptions {
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 当前用户 ID */
  currentUserId: string | undefined;
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
  /** 读取权限范围 */
  readScope: AccessScope;
  /** 修改权限范围 */
  modifyScope: AccessScope;
  /** 检查标注是否可编辑 */
  canEditAnnotation: (annotation: Annotation) => boolean;
  /** 是否有任何编辑权限 */
  hasAnyEditPermission: boolean;
}

/**
 * 使用 Classic 标注处理 hook
 */
export function useClassicAnnotations(
  options: UseClassicAnnotationsOptions
): UseClassicAnnotationsReturn {
  const {
    currentSampleId,
    currentUserId,
    annotationState,
    sync,
    t,
  } = options;

  // 权限范围状态
  const [readScope, setReadScope] = useState<AccessScope>('none');
  const [modifyScope, setModifyScope] = useState<AccessScope>('none');

  // 加载当前样本的标注
  useEffect(() => {
    if (currentSampleId) {
      api.getSampleAnnotations(currentSampleId).then((response) => {
        // 更新权限范围
        setReadScope(response.readScope || 'assigned');
        setModifyScope(response.modifyScope || 'none');
        
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSampleId]); // Only re-fetch when sample changes, not when annotationState updates

  // 检查是否有任何编辑权限
  const hasAnyEditPermission = useMemo(() => {
    return modifyScope !== 'none';
  }, [modifyScope]);

  // 检查单个标注是否可编辑
  const canEditAnnotation = useCallback((annotation: Annotation): boolean => {
    if (modifyScope === 'none') return false;
    if (modifyScope === 'all' || modifyScope === 'assigned') return true;
    if (modifyScope === 'self') {
      // 自己的标注或自动生成的标注（没有 annotatorId）可以编辑
      return !annotation.annotatorId || annotation.annotatorId === currentUserId;
    }
    return false;
  }, [modifyScope, currentUserId]);

  // 创建标注时调用 sync
  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    // 检查是否有编辑权限
    if (!hasAnyEditPermission) {
      message.warning(t('workspace.noEditPermission'));
      return;
    }

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
      annotatorId: currentUserId, // 设置当前用户为标注者
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
  }, [currentSampleId, currentUserId, annotationState, sync, t, hasAnyEditPermission]);

  // 更新标注时调用 sync
  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSampleId) return;

    // 检查是否有权限编辑此标注
    if (!canEditAnnotation(updatedAnn)) {
      message.warning(t('workspace.cannotEditOthersAnnotation'));
      return;
    }

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
  }, [currentSampleId, annotationState, sync, canEditAnnotation, t]);

  // 删除标注时调用 sync
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSampleId) return;

    // 找到要删除的标注，检查权限
    const annotation = annotationState.annotations.find(a => a.id === id);
    if (annotation && !canEditAnnotation(annotation)) {
      message.warning(t('workspace.cannotDeleteOthersAnnotation'));
      return;
    }

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
  }, [currentSampleId, annotationState, sync, canEditAnnotation, t]);

  return {
    handleAnnotationCreate,
    handleUpdateAnnotation,
    handleDeleteAnnotation,
    readScope,
    modifyScope,
    canEditAnnotation,
    hasAnyEditPermission,
  };
}

