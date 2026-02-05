/**
 * useFedoAnnotations Hook
 *
 * FEDO 标注工作空间的标注处理逻辑（不依赖后端同步）。
 */

import { useCallback, useMemo, useState } from 'react';
import { message } from 'antd';
import {
  Annotation,
  DualViewAnnotation,
  MappedRegion,
  AnnotationType,
  AnnotationSyncAction,
} from '../../types';
import { UseAnnotationStateReturn } from './useAnnotationState';
import {
  annotationToDual,
  isGeneratedAnnotation,
  generatedToAnnotations,
} from '../../utils/fedoAnnotations';
import { VIEW_TIME_ENERGY, VIEW_L_OMEGAD } from '../../components/annotation/DualCanvasArea';
import { generateUUID } from '../../utils/uuid';
import { api } from '../../services/api';

export interface UseFedoAnnotationsOptions {
  /** 当前项目 ID */
  projectId?: string;
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 当前用户 ID */
  currentUserId?: string;
  /** 标注状态管理 */
  annotationState: UseAnnotationStateReturn<DualViewAnnotation>;
  /** 翻译函数 */
  t?: (key: string) => string;
  /** 权限：是否有编辑权限 */
  hasAnyEditPermission?: boolean;
  /** 权限：是否可编辑指定标注 */
  canEditAnnotation?: (annotation: Annotation) => boolean;
}

export interface UseFedoAnnotationsReturn {
  // 状态
  /** 生成的标注列表 */
  generatedAnnotations: Annotation[];
  /** 标注的 view 信息映射 */
  annotationViews: Map<string, string>;
  /** 选中的标注 ID 集合 */
  selectedAnnotationIds: Set<string>;

  // 计算属性
  /** 用于画布显示的标注（主标注 + 生成标注） */
  canvasAnnotations: Annotation[];
  /** 用于侧边栏显示的标注（只包含主标注） */
  sidebarAnnotations: Annotation[];

  // 方法
  /** 处理标注选中 */
  handleAnnotationSelect: (id: string | null) => void;
  /** 创建标注 */
  handleAnnotationCreate: (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
    view: string;
  }) => Promise<void>;
  /** 更新标注 */
  handleUpdateAnnotation: (updatedAnn: Annotation) => Promise<void>;
  /** 删除标注 */
  handleDeleteAnnotation: (id: string) => Promise<void>;
  /** 应用外部加载的标注列表 */
  applyBaseAnnotations: (annotations: Annotation[]) => void;

  // 权限相关
  /** 检查标注是否可编辑 */
  canEditAnnotation: (annotation: Annotation) => boolean;
  /** 是否有任何编辑权限 */
  hasAnyEditPermission: boolean;
}

export function useFedoAnnotations(
  options: UseFedoAnnotationsOptions
): UseFedoAnnotationsReturn {
  const {
    projectId,
    currentSampleId,
    currentUserId,
    annotationState,
    t,
    hasAnyEditPermission: hasAnyEditPermissionProp = true,
    canEditAnnotation: canEditAnnotationProp,
  } = options;
  const {
    setAnnotations: setBaseAnnotations,
    setHistory: setBaseHistory,
    setHistoryIndex: setBaseHistoryIndex,
    setSelectedId: setBaseSelectedId,
  } = annotationState;

  // 状态
  const [generatedAnnotations, setGeneratedAnnotations] = useState<Annotation[]>([]);
  const [annotationViews, setAnnotationViews] = useState<Map<string, string>>(new Map());
  const [selectedAnnotationIds, setSelectedAnnotationIds] = useState<Set<string>>(new Set());

  const hasAnyEditPermission = hasAnyEditPermissionProp;

  const canEditAnnotation = useCallback((annotation: Annotation): boolean => {
    if (isGeneratedAnnotation(annotation)) return false;
    if (!hasAnyEditPermissionProp) return false;
    if (canEditAnnotationProp) {
      return canEditAnnotationProp(annotation);
    }
    return true;
  }, [hasAnyEditPermissionProp, canEditAnnotationProp]);

  // 计算属性：用于画布显示的标注
  const canvasAnnotations = useMemo(() => {
    const annotations: Annotation[] = [];

    // 添加所有主标注（根据 view 显示在对应画布）
    annotationState.annotations.forEach(dual => {
      annotations.push({
        id: dual.id,
        sampleId: dual.sampleId,
        labelId: dual.labelId,
        labelName: dual.labelName,
        labelColor: dual.labelColor,
        type: dual.primary.type as AnnotationType,
        source: 'manual',
        data: dual.primary.bbox,
        annotatorId: dual.annotatorId,
        extra: {
          view: annotationViews.get(dual.id) || VIEW_TIME_ENERGY,
        },
      });
    });

    // 添加生成的标注
    annotations.push(...generatedAnnotations);

    return annotations;
  }, [annotationState.annotations, generatedAnnotations, annotationViews]);

  // 计算属性：用于侧边栏显示的标注（只包含主标注）
  const sidebarAnnotations = useMemo(() => {
    return canvasAnnotations.filter(ann => !isGeneratedAnnotation(ann));
  }, [canvasAnnotations]);

  // 处理标注选中
  const handleAnnotationSelect = useCallback((id: string | null) => {
    if (!id) {
      annotationState.setSelectedId(null);
      setSelectedAnnotationIds(new Set());
      return;
    }

    const selectedAnn = canvasAnnotations.find(ann => ann.id === id);
    if (!selectedAnn) {
      annotationState.setSelectedId(id);
      setSelectedAnnotationIds(new Set([id]));
      return;
    }

    const isGenerated = isGeneratedAnnotation(selectedAnn);

    if (isGenerated) {
      const parentId = selectedAnn.extra?.parent_id || selectedAnn.extra?.parentId;
      if (parentId) {
        const relatedIds = new Set([parentId]);
        canvasAnnotations.forEach(ann => {
          const annParentId = ann.extra?.parent_id || ann.extra?.parentId;
          if (annParentId === parentId) {
            relatedIds.add(ann.id);
          }
        });
        annotationState.setSelectedId(parentId);
        setSelectedAnnotationIds(relatedIds);
      } else {
        annotationState.setSelectedId(id);
        setSelectedAnnotationIds(new Set([id]));
      }
    } else {
      const relatedIds = new Set([id]);
      canvasAnnotations.forEach(ann => {
        const parentId = ann.extra?.parent_id || ann.extra?.parentId;
        if (parentId === id) {
          relatedIds.add(ann.id);
        }
      });
      annotationState.setSelectedId(id);
      setSelectedAnnotationIds(relatedIds);
    }
  }, [canvasAnnotations, annotationState]);

  const syncGeneratedAnnotations = useCallback(async (
    action: AnnotationSyncAction,
    baseAnnotation: Annotation,
    view: string
  ) => {
    if (!projectId || !currentSampleId) return;
    try {
      const response = await api.syncAnnotation(projectId, currentSampleId, {
        action,
        annotationId: baseAnnotation.id,
        labelId: baseAnnotation.labelId,
        type: baseAnnotation.type,
        data: baseAnnotation.data,
        extra: {
          ...baseAnnotation.extra,
          view,
        },
      });

      if (!response?.success) {
        const errorMessage = response?.error || 'Failed to sync auto mapping';
        if (t) message.warning(errorMessage);
        return;
      }

      const generatedItems = (response.generated || []).filter((item) => !item?._action);
      if (generatedItems.length === 0) {
        return;
      }

      const mapped = generatedToAnnotations(
        generatedItems,
        baseAnnotation.id,
        baseAnnotation.labelId,
        baseAnnotation.labelName || '',
        baseAnnotation.labelColor || '#ff0000',
        baseAnnotation.annotatorId || currentUserId
      );

      setGeneratedAnnotations((prev) => {
        const filtered = prev.filter((ann) => {
          const parentId = ann.extra?.parent_id || ann.extra?.parentId;
          return parentId !== baseAnnotation.id;
        });
        return [...filtered, ...mapped];
      });
    } catch (error) {
      if (t) message.warning('Failed to sync auto mapping');
    }
  }, [projectId, currentSampleId, currentUserId, t]);

  // 创建标注
  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
    view: string;
  }) => {
    if (!hasAnyEditPermission) {
      if (t) message.warning(t('workspace.noEditPermission'));
      return;
    }

    if (!annotationState.selectedLabel) {
      if (t) message.warning(t('workspace.noLabelSelected'));
      return;
    }

    if (!currentSampleId) return;

    const newId = generateUUID();
    const view = event.view || VIEW_TIME_ENERGY;

    const newAnn: DualViewAnnotation = {
      id: newId,
      syncId: newId,
      parentId: null,
      sampleId: currentSampleId,
      labelId: annotationState.selectedLabel.id,
      labelName: annotationState.selectedLabel.name || 'unknown',
      labelColor: annotationState.selectedLabel.color || '#ff0000',
      annotatorId: currentUserId,
      primary: {
        type: event.type,
        bbox: event.bbox,
      },
      secondary: {
        regions: [],
      },
    };

    annotationState.handleAnnotationCreate(newAnn);
    setAnnotationViews(prev => {
      const newMap = new Map(prev);
      newMap.set(newId, view);
      return newMap;
    });

    const baseAnnotation: Annotation = {
      id: newId,
      sampleId: currentSampleId,
      labelId: annotationState.selectedLabel.id,
      labelName: annotationState.selectedLabel.name || 'unknown',
      labelColor: annotationState.selectedLabel.color || '#ff0000',
      type: event.type,
      source: 'manual',
      data: {
        x: event.bbox.x,
        y: event.bbox.y,
        width: event.bbox.width,
        height: event.bbox.height,
        rotation: event.bbox.rotation,
      },
      extra: { view },
      annotatorId: currentUserId,
    };

    await syncGeneratedAnnotations('create', baseAnnotation, view);
  }, [hasAnyEditPermission, annotationState, currentSampleId, currentUserId, t, syncGeneratedAnnotations]);

  // 更新标注
  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSampleId) return;

    if (!canEditAnnotation(updatedAnn)) {
      if (t) message.warning(t('workspace.cannotEditOthersAnnotation'));
      return;
    }

    const dual = annotationState.annotations.find(d => d.id === updatedAnn.id);
    if (dual) {
      const updatedDual: DualViewAnnotation = {
        ...dual,
        primary: {
          type: updatedAnn.type as 'rect' | 'obb',
          bbox: {
            x: updatedAnn.data.x,
            y: updatedAnn.data.y,
            width: updatedAnn.data.width,
            height: updatedAnn.data.height,
            rotation: updatedAnn.data.rotation,
          },
        },
      };
      annotationState.handleAnnotationUpdate(updatedDual);
    }
    const view = updatedAnn.extra?.view || annotationViews.get(updatedAnn.id) || VIEW_TIME_ENERGY;
    await syncGeneratedAnnotations('update', {
      ...updatedAnn,
      extra: { ...updatedAnn.extra, view },
    }, view);
  }, [currentSampleId, annotationState, canEditAnnotation, t, annotationViews, syncGeneratedAnnotations]);

  // 删除标注
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSampleId) return;

    const annotation = canvasAnnotations.find(a => a.id === id);
    if (annotation && !canEditAnnotation(annotation)) {
      if (t) message.warning(t('workspace.cannotDeleteOthersAnnotation'));
      return;
    }

    annotationState.handleAnnotationDelete(id);
    setGeneratedAnnotations(prev => prev.filter(ann => {
      const parentId = ann.extra?.parent_id || ann.extra?.parentId;
      return parentId !== id;
    }));
  }, [currentSampleId, annotationState, canvasAnnotations, canEditAnnotation, t]);

  const applyBaseAnnotations = useCallback((annotations: Annotation[]) => {
    const mainAnnotations: Annotation[] = [];
    const generated: Annotation[] = [];

    annotations.forEach((ann) => {
      if (isGeneratedAnnotation(ann)) {
        generated.push(ann);
      } else {
        mainAnnotations.push(ann);
      }
    });

    const generatedByParent = new Map<string, Annotation[]>();
    generated.forEach((genAnn) => {
      const parentId = genAnn.extra?.parent_id || genAnn.extra?.parentId;
      if (parentId) {
        if (!generatedByParent.has(parentId)) {
          generatedByParent.set(parentId, []);
        }
        generatedByParent.get(parentId)!.push(genAnn);
      }
    });

    const dualAnns: DualViewAnnotation[] = mainAnnotations.map((ann) => {
      const relatedGenerated = generatedByParent.get(ann.id) || [];
      const regions: MappedRegion[] = relatedGenerated
        .filter(gen => gen.extra?.view === VIEW_L_OMEGAD)
        .map((gen, index) => {
          const data = gen.data || {};
          const bbox = {
            x: data.x || 0,
            y: data.y || 0,
            width: data.width || 0,
            height: data.height || 0,
            rotation: data.rotation || 0,
          };

          const polygonPoints: [number, number][] = [
            [bbox.x, bbox.y],
            [bbox.x + bbox.width, bbox.y],
            [bbox.x + bbox.width, bbox.y + bbox.height],
            [bbox.x, bbox.y + bbox.height],
          ];

          return {
            timeRange: [0, 0] as [number, number],
            polygonPoints,
            isPrimary: index === 0,
          };
        });

      return annotationToDual(ann, regions);
    });

    const views = new Map<string, string>();
    mainAnnotations.forEach((ann) => {
      const view = ann.extra?.view || VIEW_TIME_ENERGY;
      views.set(ann.id, view);
    });
    setAnnotationViews(views);

    setBaseAnnotations(dualAnns);
    setBaseHistory([dualAnns]);
    setBaseHistoryIndex(0);
    setBaseSelectedId(null);
    setGeneratedAnnotations(generated);
  }, [setBaseAnnotations, setBaseHistory, setBaseHistoryIndex, setBaseSelectedId]);

  return {
    generatedAnnotations,
    annotationViews,
    selectedAnnotationIds,
    canvasAnnotations,
    sidebarAnnotations,
    handleAnnotationSelect,
    handleAnnotationCreate,
    handleUpdateAnnotation,
    handleDeleteAnnotation,
    applyBaseAnnotations,
    canEditAnnotation,
    hasAnyEditPermission,
  };
}
