/**
 * useAnnotationSubmit Hook
 * 
 * 封装标注提交的通用逻辑
 */

import { useCallback } from 'react';
import { message } from 'antd';
import { api } from '../../services/api';
import { Annotation } from '../../types';

export interface UseAnnotationSubmitOptions {
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 标注列表 */
  annotations: Annotation[];
  /** 更新样本状态的方法 */
  updateSampleStatus: (sampleId: string, status: 'labeled' | 'unlabeled' | 'skipped') => void;
  /** 切换到下一个样本 */
  onNext: () => void;
  /** 翻译函数 */
  t: (key: string) => string;
  /** 自定义转换函数（可选，用于特殊格式如 DualViewAnnotation） */
  convertAnnotations?: (annotations: Annotation[]) => Annotation[];
}

export interface UseAnnotationSubmitReturn {
  /** 提交标注 */
  handleSubmit: () => Promise<void>;
}

/**
 * 使用标注提交 hook
 */
export function useAnnotationSubmit(
  options: UseAnnotationSubmitOptions
): UseAnnotationSubmitReturn {
  const {
    currentSampleId,
    annotations,
    updateSampleStatus,
    onNext,
    t,
    convertAnnotations,
  } = options;

  const handleSubmit = useCallback(async () => {
    if (!currentSampleId) return;

    try {
      // 转换标注格式（如果有自定义转换函数）
      let annsToSave = convertAnnotations ? convertAnnotations(annotations) : annotations;

      // 直接使用前端坐标（左上角），后端会自动转换
      await api.saveAnnotations(currentSampleId, annsToSave, 'labeled');
      updateSampleStatus(currentSampleId, 'labeled');
      message.success(t('annotation.saved') || 'Saved');
      onNext();
    } catch (error) {
      message.error(t('annotation.saveError'));
    }
  }, [currentSampleId, annotations, updateSampleStatus, onNext, t, convertAnnotations]);

  return {
    handleSubmit,
  };
}

