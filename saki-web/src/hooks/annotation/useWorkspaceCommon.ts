/**
 * useWorkspaceCommon Hook
 * 
 * 封装标注工作空间的通用逻辑
 */

import { useEffect, useCallback } from 'react';
import { Label } from '../../types';
import { AnnotationLike, UseAnnotationStateReturn } from './useAnnotationState';

export interface UseWorkspaceCommonOptions<T extends AnnotationLike> {
  /** 标签列表 */
  labels: Label[];
  /** 标注状态管理 */
  annotationState: UseAnnotationStateReturn<T>;
}

export interface UseWorkspaceCommonReturn {
  /** 初始化默认标签选择 */
  initializeDefaultLabel: () => void;
}

/**
 * 使用工作空间通用逻辑 hook
 */
export function useWorkspaceCommon<T extends AnnotationLike>(
  options: UseWorkspaceCommonOptions<T>
): UseWorkspaceCommonReturn {
  const { labels, annotationState } = options;

  // 初始化默认标签选择
  const initializeDefaultLabel = useCallback(() => {
    if (labels.length > 0 && !annotationState.selectedLabel) {
      annotationState.setSelectedLabel(labels[0]);
    }
  }, [labels, annotationState]);

  // 自动初始化
  useEffect(() => {
    initializeDefaultLabel();
  }, [initializeDefaultLabel]);

  return {
    initializeDefaultLabel,
  };
}

