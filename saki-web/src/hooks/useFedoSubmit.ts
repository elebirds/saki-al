/**
 * useFedoSubmit Hook
 * 
 * 封装 FEDO 标注提交逻辑
 */

import { useCallback } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { Annotation, DualViewAnnotation } from '../types';
import { originToCenter } from '../utils/canvasUtils';
import { dualToAnnotations } from '../utils/fedoAnnotations';
import { VIEW_TIME_ENERGY } from '../components/annotation/DualCanvasArea';

export interface UseFedoSubmitOptions {
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 主标注列表 */
  annotations: DualViewAnnotation[];
  /** 生成的标注列表 */
  generatedAnnotations: Annotation[];
  /** 标注的 view 信息映射 */
  annotationViews: Map<string, string>;
  /** 更新样本状态的方法 */
  updateSampleStatus: (sampleId: string, status: 'labeled' | 'unlabeled' | 'skipped') => void;
  /** 切换到下一个样本 */
  onNext: () => void;
  /** 翻译函数 */
  t: (key: string) => string;
}

export interface UseFedoSubmitReturn {
  /** 提交标注 */
  handleSubmit: () => Promise<void>;
}

/**
 * 使用 FEDO 标注提交 hook
 */
export function useFedoSubmit(
  options: UseFedoSubmitOptions
): UseFedoSubmitReturn {
  const {
    currentSampleId,
    annotations,
    generatedAnnotations,
    annotationViews,
    updateSampleStatus,
    onNext,
    t,
  } = options;

  const handleSubmit = useCallback(async () => {
    if (!currentSampleId) return;

    try {
      const annsToSave: Annotation[] = [];
      
      // 添加主标注
      annotations.forEach(dual => {
        const anns = dualToAnnotations(dual);
        const convertedAnns = anns.map(ann => {
          const view = annotationViews.get(ann.id) || VIEW_TIME_ENERGY;
          
          if (ann.data) {
            const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
            return {
              ...ann,
              extra: { ...ann.extra, view },
              data: originToCenter(bboxData),
            };
          }
          
          return {
            ...ann,
            extra: { ...ann.extra, view }
          };
        });
        annsToSave.push(...convertedAnns);
      });
      
      // 添加生成的标注
      generatedAnnotations.forEach(ann => {
        if (ann.data) {
          const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
          annsToSave.push({
            ...ann,
            data: originToCenter(bboxData),
          });
        } else {
          annsToSave.push(ann);
        }
      });
      
      await api.saveAnnotations(currentSampleId, annsToSave, 'labeled');
      updateSampleStatus(currentSampleId, 'labeled');
      message.success(t('annotation.saved') || 'Saved');
      onNext();
    } catch (error) {
      message.error(t('annotation.saveError'));
    }
  }, [currentSampleId, annotations, generatedAnnotations, annotationViews, updateSampleStatus, onNext, t]);

  return {
    handleSubmit,
  };
}

