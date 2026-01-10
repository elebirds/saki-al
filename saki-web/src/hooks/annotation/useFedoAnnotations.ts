/**
 * useFedoAnnotations Hook
 * 
 * 封装 FEDO 标注工作空间的标注处理逻辑
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { message } from 'antd';
import { api } from '../../services/api';
import {
  Annotation,
  DualViewAnnotation,
  MappedRegion,
  AnnotationType,
  SyncAction,
} from '../../types';
import { UseAnnotationStateReturn } from './useAnnotationState';
import { UseAnnotationSyncReturn } from './useAnnotationSync';
import {
  dualToAnnotations,
  annotationToDual,
  generatedToAnnotations,
  generatedToRegions,
  isGeneratedAnnotation,
} from '../../utils/fedoAnnotations';
import { VIEW_TIME_ENERGY, VIEW_L_OMEGAD } from '../../components/annotation/DualCanvasArea';
import { generateUUID } from '../../utils/uuid';

/** 权限范围类型 */
export type AccessScope = 'all' | 'assigned' | 'self' | 'none';

export interface UseFedoAnnotationsOptions {
  /** 当前样本 ID */
  currentSampleId: string | undefined;
  /** 当前用户 ID */
  currentUserId?: string;
  /** 标注状态管理 */
  annotationState: UseAnnotationStateReturn<DualViewAnnotation>;
  /** 同步 hook */
  sync: UseAnnotationSyncReturn['sync'];
  /** 样本切换时的回调 */
  onSampleChange?: () => void;
  /** 翻译函数 */
  t?: (key: string) => string;
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
  /** 加载样本的标注 */
  loadSampleAnnotations: () => Promise<void>;
  
  // 权限相关
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
 * 使用 FEDO 标注处理 hook
 */
export function useFedoAnnotations(
  options: UseFedoAnnotationsOptions
): UseFedoAnnotationsReturn {
  const {
    currentSampleId,
    currentUserId,
    annotationState,
    sync,
    onSampleChange,
    t,
  } = options;

  // 状态
  const [generatedAnnotations, setGeneratedAnnotations] = useState<Annotation[]>([]);
  const [annotationViews, setAnnotationViews] = useState<Map<string, string>>(new Map());
  const [selectedAnnotationIds, setSelectedAnnotationIds] = useState<Set<string>>(new Set());
  
  // 权限范围状态
  const [readScope, setReadScope] = useState<AccessScope>('assigned');
  const [modifyScope, setModifyScope] = useState<AccessScope>('none');

  // 检查是否有任何编辑权限
  const hasAnyEditPermission = useMemo(() => {
    return modifyScope !== 'none';
  }, [modifyScope]);

  // 检查单个标注是否可编辑
  const canEditAnnotation = useCallback((annotation: Annotation): boolean => {
    // 生成的标注不可编辑
    if (isGeneratedAnnotation(annotation)) return false;
    if (modifyScope === 'none') return false;
    if (modifyScope === 'all' || modifyScope === 'assigned') return true;
    if (modifyScope === 'self') {
      return !annotation.annotatorId || annotation.annotatorId === currentUserId;
    }
    return false;
  }, [modifyScope, currentUserId]);

  // 计算属性：用于画布显示的标注
  const canvasAnnotations = useMemo(() => {
    const annotations: Annotation[] = [];
    
    // 添加所有主标注（根据 view 显示在对应画布）
    annotationState.annotations.forEach(dual => {
      const anns = dualToAnnotations(dual);
      anns.forEach(ann => {
        const view = annotationViews.get(ann.id) || VIEW_TIME_ENERGY;
        ann.extra = { ...ann.extra, view };
      });
      annotations.push(...anns);
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
      // 如果选中的是生成标注，选中它的父标注
      const parentId = selectedAnn.extra?.parent_id || selectedAnn.extra?.parentId;
      if (parentId) {
        const parentAnn = canvasAnnotations.find(ann => ann.id === parentId);
        if (parentAnn) {
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
        annotationState.setSelectedId(id);
        setSelectedAnnotationIds(new Set([id]));
      }
    } else {
      // 如果选中的是主标注，找到所有关联的生成标注并一起选中
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

  // 创建标注
  const handleAnnotationCreate = useCallback(async (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
    view: string;
  }) => {
    // 检查是否有编辑权限
    if (!hasAnyEditPermission) {
      if (t) {
        message.warning(t('workspace.noEditPermission'));
      }
      return;
    }

    if (!annotationState.selectedLabel) {
      if (t) {
        message.warning(t('workspace.noLabelSelected'));
      }
      return;
    }

    if (!currentSampleId) return;

    const newId = generateUUID();
    const view = event.view || VIEW_TIME_ENERGY;
    
    // 直接使用前端坐标（左上角），后端会自动转换
    const syncAction: SyncAction = {
      action: 'create',
      annotationId: newId,
      labelId: annotationState.selectedLabel.id,
      type: event.type as AnnotationType,
      data: event.bbox,
      extra: { view },
    };

    try {
      const syncResponse = await sync(currentSampleId, [syncAction]);
      const syncResult = syncResponse.results[0];
      
      let regions: MappedRegion[] = [];
      const newGeneratedAnnotations: Annotation[] = [];
      
      if (syncResult?.generated) {
        regions = generatedToRegions(syncResult.generated);
        
        const generated = generatedToAnnotations(
          syncResult.generated,
          newId,
          annotationState.selectedLabel.id,
          annotationState.selectedLabel.name || 'unknown',
          annotationState.selectedLabel.color || '#ff0000',
          currentUserId
        );
        newGeneratedAnnotations.push(...generated);
      }

      const newAnn: DualViewAnnotation = {
        id: newId,
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
          regions,
        },
      };

      annotationState.handleAnnotationCreate(newAnn);
      
      setAnnotationViews(prev => {
        const newMap = new Map(prev);
        newMap.set(newId, view);
        return newMap;
      });
      
      if (newGeneratedAnnotations.length > 0) {
        setGeneratedAnnotations(prev => [...prev, ...newGeneratedAnnotations]);
      }
    } catch (error) {
      console.error('Sync failed:', error);
      // 降级处理
      const newAnn: DualViewAnnotation = {
        id: newId,
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
    }
  }, [currentSampleId, annotationState, sync, t]);

  // 更新标注
  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    if (!currentSampleId) return;

    // 检查是否有权限编辑此标注
    if (!canEditAnnotation(updatedAnn)) {
      if (t) {
        message.warning(t('workspace.cannotEditOthersAnnotation'));
      }
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
      const syncResponse = await sync(currentSampleId, [syncAction]);
      const syncResult = syncResponse.results[0];
      
      let regions: MappedRegion[] = [];
      const generatedAnnotations: Annotation[] = [];
      
      if (syncResult?.generated) {
        const actualGenerated = syncResult.generated.filter(
          (gen: any) => !gen._action || gen._action !== 'regenerate_children'
        );
        
        if (actualGenerated.length > 0) {
          regions = generatedToRegions(actualGenerated);
          
          const generated = generatedToAnnotations(
            actualGenerated,
            updatedAnn.id,
            updatedAnn.labelId,
            updatedAnn.labelName || 'unknown',
            updatedAnn.labelColor || '#ff0000',
            updatedAnn.annotatorId || currentUserId
          );
          generatedAnnotations.push(...generated);
          
          setGeneratedAnnotations(prev => {
            const filtered = prev.filter(ann => {
              const parentId = ann.extra?.parent_id || ann.extra?.parentId;
              return parentId !== updatedAnn.id;
            });
            return [...filtered, ...generatedAnnotations];
          });
          
          if (annotationState.selectedId === updatedAnn.id || 
              selectedAnnotationIds.has(updatedAnn.id)) {
            const newRelatedIds = new Set([updatedAnn.id]);
            generatedAnnotations.forEach(genAnn => {
              newRelatedIds.add(genAnn.id);
            });
            setSelectedAnnotationIds(newRelatedIds);
          }
        } else {
          setGeneratedAnnotations(prev => {
            return prev.filter(ann => {
              const parentId = ann.extra?.parent_id || ann.extra?.parentId;
              return parentId !== updatedAnn.id;
            });
          });
        }
      }

      const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, regions);
      annotationState.handleAnnotationUpdate(dualAnn);
    } catch (error) {
      console.error('Sync failed:', error);
      const existingDual = annotationState.annotations.find((a) => a.id === updatedAnn.id);
      const existingRegions = existingDual?.secondary?.regions || [];
      const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, existingRegions);
      annotationState.handleAnnotationUpdate(dualAnn);
    }
  }, [currentSampleId, annotationState, sync, selectedAnnotationIds]);

  // 删除标注
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!currentSampleId) return;

    // 找到要删除的标注，检查权限
    const annotation = canvasAnnotations.find(a => a.id === id);
    if (annotation && !canEditAnnotation(annotation)) {
      if (t) {
        message.warning(t('workspace.cannotDeleteOthersAnnotation'));
      }
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
      
      setGeneratedAnnotations(prev => prev.filter(ann => {
        const parentId = ann.extra?.parent_id || ann.extra?.parentId;
        return parentId !== id;
      }));
    } catch (error) {
      console.error('Sync failed:', error);
      annotationState.handleAnnotationDelete(id);
      
      setGeneratedAnnotations(prev => prev.filter(ann => {
        const parentId = ann.extra?.parent_id || ann.extra?.parentId;
        return parentId !== id;
      }));
    }
  }, [currentSampleId, annotationState, sync, canvasAnnotations, canEditAnnotation, t]);

  // 加载样本的标注
  const loadSampleAnnotations = useCallback(async () => {
    if (!currentSampleId) return;

    const response = await api.getSampleAnnotations(currentSampleId);
    
    // 更新权限范围
    setReadScope(response.readScope || 'assigned');
    setModifyScope(response.modifyScope || 'none');
    
    // 分离主标注和生成的标注
    const mainAnnotations: Annotation[] = [];
    const generated: Annotation[] = [];
    
    response.annotations.forEach((ann: any) => {
      // 转换字段名：后端返回 snake_case，前端使用 camelCase
      const annotation: Annotation = {
        ...ann,
        annotatorId: ann.annotatorId || ann.annotator_id || null,
        labelId: ann.labelId || ann.label_id,
        labelName: ann.labelName || ann.label_name,
        labelColor: ann.labelColor || ann.label_color,
        sampleId: ann.sampleId || ann.sample_id,
      };
      
      // 后端已经转换为左上角坐标，直接使用
      if (isGeneratedAnnotation(annotation)) {
        generated.push(annotation);
      } else {
        mainAnnotations.push(annotation);
      }
    });
    
    // 将生成的标注按 parent_id 分组
    const generatedByParent = new Map<string, Annotation[]>();
    generated.forEach(genAnn => {
      const parentId = genAnn.extra?.parent_id || genAnn.extra?.parentId;
      if (parentId) {
        if (!generatedByParent.has(parentId)) {
          generatedByParent.set(parentId, []);
        }
        generatedByParent.get(parentId)!.push(genAnn);
      }
    });
    
    // 将主标注转换为 DualViewAnnotation
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
    
    // 存储每个标注的 view 信息
    const views = new Map<string, string>();
    mainAnnotations.forEach(ann => {
      const view = ann.extra?.view || VIEW_TIME_ENERGY;
      views.set(ann.id, view);
    });
    setAnnotationViews(views);
    
    // 重置历史记录
    annotationState.resetHistory();
    if (dualAnns.length > 0) {
      annotationState.addToHistory(dualAnns);
    } else {
      annotationState.setAnnotations([]);
    }
    
    // 设置生成的标注
    setGeneratedAnnotations(generated);
  }, [currentSampleId, annotationState]);

  // 当样本改变时加载标注
  useEffect(() => {
    loadSampleAnnotations();
    onSampleChange?.();
  }, [currentSampleId]); // eslint-disable-line react-hooks/exhaustive-deps

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
    loadSampleAnnotations,
    // 权限相关
    readScope,
    modifyScope,
    canEditAnnotation,
    hasAnyEditPermission,
  };
}

