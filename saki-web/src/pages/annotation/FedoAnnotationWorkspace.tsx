/**
 * FEDO Dual-View Annotation Workspace
 * 
 * Specialized annotation workspace for satellite FEDO data with:
 * - Left panel: Time-Energy view (ax1) for primary annotation
 * - Right panel: L-ωd view (ax3) showing mapped regions
 * - Real-time bidirectional synchronization
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Layout, message, Spin, Empty, Tag } from 'antd';
import { useTranslation } from 'react-i18next';
import { DeleteOutlined, RotateRightOutlined, BorderOutlined } from '@ant-design/icons';
import { AnnotationToolbar, AnnotationSidebar, DualCanvasArea, DualCanvasAreaRef, SampleList } from '../../components/annotation';
import { api } from '../../services/api';
import {
  useAnnotationState,
  useAnnotationSync,
  useAnnotationShortcuts,
} from '../../hooks';
import {
  Sample,
  Annotation,
  Dataset,
  Label,
  DualViewAnnotation,
  MappedRegion,
  BoundingBox,
  AnnotationType,
  SyncAction,
} from '../../types';
import { VIEW_TIME_ENERGY, VIEW_L_OMEGAD } from '../../components/annotation/DualCanvasArea';
import { originToCenter, centerToOrigin } from '../../utils/canvasUtils';

const { Content, Sider } = Layout;

// ============================================================================
// Helper Functions
// ============================================================================

/** Convert DualViewAnnotation to Annotation[] for AnnotationCanvas (one per view) */
function dualToAnnotations(dual: DualViewAnnotation): Annotation[] {
  const annotations: Annotation[] = [];
  
  // 根据 primary 的 view 信息决定显示在哪个画布
  // 如果 extra 中有 view 信息，使用它；否则默认为 Time-Energy
  // 注意：DualViewAnnotation 本身不包含 view 信息，我们需要从 Annotation 中获取
  // 这里我们假设主标注默认在 Time-Energy 视图
  // 实际上，view 信息应该从创建时的 extra 中获取
  
  // 为了简化，我们总是将主标注显示在 Time-Energy 视图
  // 如果需要在 L-ωd 视图显示，应该在创建时设置 view
  annotations.push({
    id: dual.id,
    sampleId: dual.sampleId,
    labelId: dual.labelId,
    labelName: dual.labelName,
    labelColor: dual.labelColor,
    type: dual.primary.type as AnnotationType,
    source: 'manual',
    data: dual.primary.bbox,
    extra: {
      view: VIEW_TIME_ENERGY, // 默认主标注在 Time-Energy 视图
    },
  });
  
  return annotations;
}

/** Convert Annotation to DualViewAnnotation */
function annotationToDual(ann: Annotation, regions: MappedRegion[] = []): DualViewAnnotation {
  const bbox: BoundingBox = {
    x: ann.data.x || 0,
    y: ann.data.y || 0,
    width: ann.data.width || 0,
    height: ann.data.height || 0,
    rotation: ann.data.rotation,
  };

  const extraRegions = ann.extra?.secondary?.regions || regions;

  return {
    id: ann.id,
    sampleId: ann.sampleId || '',
    labelId: ann.labelId,
    labelName: ann.labelName || '',
    labelColor: ann.labelColor || '#ff0000',
    primary: {
      type: ann.type as 'rect' | 'obb',
      bbox,
    },
    secondary: {
      regions: extraRegions,
    },
  };
}

/** Convert backend generated annotations to Annotation[] */
function generatedToAnnotations(
  generated: Array<Record<string, any>>,
  parentId: string,
  labelId: string,
  labelName: string,
  labelColor: string
): Annotation[] {
  return generated.map((gen) => {
    const data = gen.data || {};
    const view = gen.extra?.view || gen.view || VIEW_L_OMEGAD;
    const type = (gen.type || 'obb') as AnnotationType;
    
    // 后端返回的是中心点坐标，需要转换为起始点坐标用于前端显示
    let bboxData = {
      x: data.x || 0,
      y: data.y || 0,
      width: data.width || 0,
      height: data.height || 0,
      rotation: data.rotation || 0,
    };
    
    // 对于 OBB 类型，将中心点转换为起始点
    if (type === 'obb') {
      bboxData = centerToOrigin(bboxData);
    }
    
    return {
      id: gen.id || `generated-${Date.now()}-${Math.random()}`,
      labelId: gen.label_id || labelId,
      labelName: gen.label_name || labelName,
      labelColor: gen.label_color || labelColor,
      type: type,
      source: (gen.source || 'auto') as any,
      data: bboxData,
      extra: {
        parent_id: parentId,
        view: view,
        mapping_method: gen.extra?.mapping_method || 'placeholder',
      },
    };
  });
}

/** Convert backend generated annotations to MappedRegion[] (for backward compatibility) */
function generatedToRegions(generated: Array<Record<string, any>>): MappedRegion[] {
  return generated
    .filter((gen) => {
      const view = gen.extra?.view || gen.view;
      return view === VIEW_L_OMEGAD;
    })
    .map((gen, index) => {
      const data = gen.data || {};
      // 将 bbox 转换为 polygon points（简化处理，实际可能需要更复杂的转换）
      const bbox = {
        x: data.x || 0,
        y: data.y || 0,
        width: data.width || 0,
        height: data.height || 0,
        rotation: data.rotation || 0,
      };

      // 简化的转换：将 bbox 转换为矩形 polygon
      const polygonPoints: [number, number][] = [
        [bbox.x, bbox.y],
        [bbox.x + bbox.width, bbox.y],
        [bbox.x + bbox.width, bbox.y + bbox.height],
        [bbox.x, bbox.y + bbox.height],
      ];

      return {
        timeRange: [0, 0] as [number, number], // 后端应该提供这个信息
        polygonPoints,
        isPrimary: index === 0,
      };
    });
}

// ============================================================================
// Component
// ============================================================================

const FedoAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();
  const [searchParams] = useSearchParams();

  // Dataset & Samples State
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [labels, setLabels] = useState<Label[]>([]);

  // Dual Canvas Area Ref
  const dualCanvasAreaRef = useRef<DualCanvasAreaRef>(null);

  // Current sample
  const currentSample = samples[currentIndex];

  // 使用公共的状态管理 hook（适配 DualViewAnnotation）
  const annotationState = useAnnotationState<DualViewAnnotation>({
    initialAnnotations: [],
  });

  // 使用同步 hook（调用后端 sync 接口）
  const { isSyncing, isSyncReady, sync: syncBackend } = useAnnotationSync({ enabled: true });

  // 存储生成的标注（由 sync 返回的 generated 标注）
  const [generatedAnnotations, setGeneratedAnnotations] = useState<Annotation[]>([]);

  // ========================================================================
  // Memoized Conversions
  // ========================================================================

  // Convert DualViewAnnotation[] to Annotation[] for AnnotationCanvas
  // 包括主标注和生成的标注
  // 注意：我们需要存储每个 DualViewAnnotation 对应的 view 信息
  // 由于 DualViewAnnotation 不包含 view，我们需要从创建时的 context 中获取
  // 为了简化，我们使用一个 Map 来存储 view 信息
  const [annotationViews, setAnnotationViews] = useState<Map<string, string>>(new Map());
  
  const canvasAnnotations = useMemo(() => {
    const annotations: Annotation[] = [];
    
    // 添加所有主标注（根据 view 显示在对应画布）
    annotationState.annotations.forEach(dual => {
      const anns = dualToAnnotations(dual);
      // 从 annotationViews 中获取 view 信息，如果没有则使用默认值
      anns.forEach(ann => {
        const view = annotationViews.get(ann.id) || VIEW_TIME_ENERGY;
        ann.extra = { ...ann.extra, view };
      });
      annotations.push(...anns);
    });
    
    // 添加生成的标注（由 sync 返回的 generated 标注）
    annotations.push(...generatedAnnotations);
    
    return annotations;
  }, [annotationState.annotations, generatedAnnotations, annotationViews]);

  // 侧边栏显示的标注列表：只显示主标注（排除生成的标注）
  const sidebarAnnotations = useMemo(() => {
    return canvasAnnotations.filter(ann => {
      // 排除生成的标注（source === 'auto' 或 'fedo_mapping' 或有 parent_id）
      const source = ann.source as string;
      const isGenerated = 
        source === 'auto' || 
        source === 'fedo_mapping' || 
        !!ann.extra?.parent_id;
      return !isGenerated;
    });
  }, [canvasAnnotations]);

  // 存储所有应该被选中的标注 ID（包括主标注和关联的生成标注）
  const [selectedAnnotationIds, setSelectedAnnotationIds] = useState<Set<string>>(new Set());

  // 处理标注选中，自动选中关联的标注
  const handleAnnotationSelect = useCallback((id: string | null) => {
    if (!id) {
      annotationState.setSelectedId(null);
      setSelectedAnnotationIds(new Set());
      return;
    }

    // 找到选中的标注
    const selectedAnn = canvasAnnotations.find(ann => ann.id === id);
    if (!selectedAnn) {
      annotationState.setSelectedId(id);
      setSelectedAnnotationIds(new Set([id]));
      return;
    }

    // 判断是主标注还是生成的标注
    const source = selectedAnn.source as string;
    const isGenerated = 
      source === 'auto' || 
      source === 'fedo_mapping' || 
      !!selectedAnn.extra?.parent_id;
    
    if (isGenerated) {
      // 如果选中的是生成标注，选中它的父标注
      const parentId = selectedAnn.extra?.parent_id || selectedAnn.extra?.parentId;
      if (parentId) {
        // 找到父标注并选中
        const parentAnn = canvasAnnotations.find(ann => ann.id === parentId);
        if (parentAnn) {
          // 选中父标注，并找到所有关联的生成标注
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
        // 检查 parent_id（可能是 parent_id 或 parentId）
        const parentId = ann.extra?.parent_id || ann.extra?.parentId;
        if (parentId === id) {
          relatedIds.add(ann.id);
        }
      });
      annotationState.setSelectedId(id);
      setSelectedAnnotationIds(relatedIds);
    }
  }, [canvasAnnotations, annotationState]);

  // ========================================================================
  // Data Loading
  // ========================================================================

  useEffect(() => {
    if (datasetId) {
      setLoading(true);
      
      // Load samples with sort settings from localStorage
      const sortSettingsStr = localStorage.getItem(`dataset_${datasetId}_sort`);
      let sortOptions: {
        sortBy?: 'name' | 'status' | 'created_at' | 'updated_at' | 'remark';
        sortOrder?: 'asc' | 'desc';
      } = {};
      
      if (sortSettingsStr) {
        try {
          const sortSettings = JSON.parse(sortSettingsStr);
          sortOptions = {
            sortBy: sortSettings.sortBy,
            sortOrder: sortSettings.sortOrder,
          };
        } catch (e) {
          console.error('Failed to parse sort settings:', e);
        }
      }
      
      Promise.all([
        api.getDataset(datasetId),
        api.getLabels(datasetId),
        api.getSamples(datasetId, sortOptions),
      ])
        .then(([ds, loadedLabels, samps]) => {
          if (ds) setDataset(ds);
          setLabels(loadedLabels);
          if (loadedLabels.length > 0 && !annotationState.selectedLabel) {
            annotationState.setSelectedLabel(loadedLabels[0]);
          }
          setSamples(samps);
          // 如果URL中有sampleId参数，跳转到对应的sample
          const sampleId = searchParams.get('sampleId');
          if (sampleId && samps.length > 0) {
            const index = samps.findIndex(s => s.id === sampleId);
            if (index !== -1) {
              setCurrentIndex(index);
            }
          }
          setLoading(false);
        })
        .catch((err) => {
          console.error('Failed to load dataset:', err);
          message.error('Failed to load dataset');
          setLoading(false);
        });
    }
  }, [datasetId, searchParams]);

  // Load sample data
  useEffect(() => {
    if (currentSample?.id) {
      // Load annotations for this sample
      api.getSampleAnnotations(currentSample.id).then((response) => {
        // 分离主标注和生成的标注
        const mainAnnotations: Annotation[] = [];
        const generated: Annotation[] = [];
        
        response.annotations.forEach((ann) => {
          // 根据 source 和 extra.parent_id 判断是主标注还是生成的标注
          // 生成的标注可能是 source === 'auto' 或 'fedo_mapping'，或者有 parent_id
          const source = ann.source as string;
          const parentId = ann.extra?.parent_id || ann.extra?.parentId;
          const isGenerated = 
            source === 'auto' || 
            source === 'fedo_mapping' || 
            !!parentId;
          
          // 后端返回的是中心点坐标，需要转换为起始点坐标用于前端显示
          // 对于 OBB 类型，将中心点转换为起始点
          if (ann.type === 'obb' && ann.data) {
            const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
            ann = {
              ...ann,
              data: centerToOrigin(bboxData)
            };
          }
          
          if (isGenerated) {
            generated.push(ann);
          } else {
            mainAnnotations.push(ann);
          }
        });
        
        // 将生成的标注按 parent_id 分组，用于构建 MappedRegion
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
        
        // 将主标注转换为 DualViewAnnotation，并关联生成的标注
        const dualAnns: DualViewAnnotation[] = mainAnnotations.map((ann) => {
          // 找到该主标注关联的生成标注，转换为 MappedRegion
          const relatedGenerated = generatedByParent.get(ann.id) || [];
          const regions: MappedRegion[] = relatedGenerated
            .filter(gen => gen.extra?.view === VIEW_L_OMEGAD) // 只处理 L-ωd 视图的生成标注
            .map((gen, index) => {
              const data = gen.data || {};
              const bbox = {
                x: data.x || 0,
                y: data.y || 0,
                width: data.width || 0,
                height: data.height || 0,
                rotation: data.rotation || 0,
              };
              
              // 将 bbox 转换为 polygon points
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
        // 设置初始标注并添加到历史记录
        if (dualAnns.length > 0) {
          annotationState.addToHistory(dualAnns);
        } else {
          annotationState.setAnnotations([]);
        }
        
        // 设置生成的标注（用于在画布上显示）
        // 确保生成的标注都有正确的 parent_id 和 view 信息
        // 这些生成的标注会通过 parent_id 关联到主标注，并在画布上显示
        setGeneratedAnnotations(generated);
      });
    } else {
      // 清空生成的标注
      setGeneratedAnnotations([]);
    }
  }, [currentSample?.id]);

  // ========================================================================
  // Annotation Handlers
  // ========================================================================

  const handleAnnotationCreate = useCallback(
    async (event: {
      type: 'rect' | 'obb';
      bbox: { x: number; y: number; width: number; height: number; rotation?: number };
      view: string; // 'time-energy' 或 'L-omegad'
    }) => {
      if (!annotationState.selectedLabel) {
        message.warning(t('workspace.noLabelSelected'));
        return;
      }

      if (!currentSample) return;

      // 使用UUID格式生成ID，与后端生成的ID格式保持一致
      const newId = crypto.randomUUID();
      const view = event.view || VIEW_TIME_ENERGY;

      // 将起始点转换为中心点再发送给后端（后端期望中心点坐标，无论rect还是obb）
      // 对于rect类型，rotation为0或undefined，originToCenter仍然能正确处理
      let bboxData = originToCenter(event.bbox);
      
      // 调用后端 sync 接口
      const syncAction: SyncAction = {
        action: 'create',
        annotationId: newId,
        labelId: annotationState.selectedLabel.id,
        type: event.type as AnnotationType,
        data: bboxData,
        extra: { view },
      };

      try {
        // 调用后端 sync
        const syncResponse = await syncBackend(currentSample.id, [syncAction]);
        const syncResult = syncResponse.results[0];
        
        // 处理后端返回的生成标注
        let regions: MappedRegion[] = [];
        const newGeneratedAnnotations: Annotation[] = [];
        
        if (syncResult?.generated) {
          // 将生成的标注转换为 MappedRegion（用于显示在 secondary 区域）
          regions = generatedToRegions(syncResult.generated);
          
          // 将生成的标注转换为 Annotation 格式，添加到画布上
          const generated = generatedToAnnotations(
            syncResult.generated,
            newId,
            annotationState.selectedLabel.id,
            annotationState.selectedLabel.name || 'unknown',
            annotationState.selectedLabel.color || '#ff0000'
          );
          newGeneratedAnnotations.push(...generated);
        }

        // 创建主标注（DualViewAnnotation）
        // 如果是在 Time-Energy 视图创建的，作为 primary
        // 如果是在 L-ωd 视图创建的，也作为 primary（但 view 不同）
        const newAnn: DualViewAnnotation = {
          id: newId,
          sampleId: currentSample.id,
          labelId: annotationState.selectedLabel.id,
          labelName: annotationState.selectedLabel.name || 'unknown',
          labelColor: annotationState.selectedLabel.color || '#ff0000',
          primary: {
            type: event.type,
            bbox: event.bbox,
          },
          secondary: {
            regions,
          },
        };

        // 添加主标注
        annotationState.handleAnnotationCreate(newAnn);
        
        // 存储该标注的 view 信息
        setAnnotationViews(prev => {
          const newMap = new Map(prev);
          newMap.set(newId, view);
          return newMap;
        });
        
        // 添加生成的标注（如果有）
        if (newGeneratedAnnotations.length > 0) {
          setGeneratedAnnotations(prev => [...prev, ...newGeneratedAnnotations]);
        }
      } catch (error) {
        console.error('Sync failed:', error);
        // 即使 sync 失败，也创建标注（降级处理）
        const newAnn: DualViewAnnotation = {
          id: newId,
          sampleId: currentSample.id,
          labelId: annotationState.selectedLabel.id,
          labelName: annotationState.selectedLabel.name || 'unknown',
          labelColor: annotationState.selectedLabel.color || '#ff0000',
          primary: {
            type: event.type,
            bbox: event.bbox,
          },
          secondary: {
            regions: [],
          },
        };
        annotationState.handleAnnotationCreate(newAnn);
        
        // 存储该标注的 view 信息
        setAnnotationViews(prev => {
          const newMap = new Map(prev);
          newMap.set(newId, view);
          return newMap;
        });
      }
    },
    [currentSample, annotationState, syncBackend, t]
  );

  const handleUpdateAnnotation = useCallback(
    async (updatedAnn: Annotation) => {
      if (!currentSample) return;

      // 将起始点转换为中心点再发送给后端（后端期望中心点坐标，无论rect还是obb）
      let bboxData = updatedAnn.data;
      if (bboxData) {
        const bboxDataTyped = bboxData as { x: number; y: number; width: number; height: number; rotation?: number };
        bboxData = originToCenter(bboxDataTyped);
      }

      // 调用后端 sync
      const syncAction: SyncAction = {
        action: 'update',
        annotationId: updatedAnn.id,
        labelId: updatedAnn.labelId,
        type: updatedAnn.type,
        data: bboxData,
        extra: updatedAnn.extra || {},
      };

      try {
        const syncResponse = await syncBackend(currentSample.id, [syncAction]);
        
        // 处理后端返回的生成标注
        const syncResult = syncResponse.results[0];
        let regions: MappedRegion[] = [];
        const generatedAnnotations: Annotation[] = [];
        
        if (syncResult?.generated) {
          // 过滤掉 regenerate_children 信号，只处理实际的生成标注
          const actualGenerated = syncResult.generated.filter(
            (gen: any) => !gen._action || gen._action !== 'regenerate_children'
          );
          
          if (actualGenerated.length > 0) {
            regions = generatedToRegions(actualGenerated);
            
            // 将生成的标注转换为 Annotation 格式
            const generated = generatedToAnnotations(
              actualGenerated,
              updatedAnn.id,
              updatedAnn.labelId,
              updatedAnn.labelName || 'unknown',
              updatedAnn.labelColor || '#ff0000'
            );
            generatedAnnotations.push(...generated);
            
            // 更新生成的标注：删除旧的，添加新的
            setGeneratedAnnotations(prev => {
              // 删除该 parent_id 对应的旧生成标注
              const filtered = prev.filter(ann => {
                const parentId = ann.extra?.parent_id || ann.extra?.parentId;
                return parentId !== updatedAnn.id;
              });
              // 添加新的生成标注
              return [...filtered, ...generatedAnnotations];
            });
            
            // 如果当前选中的是主标注或其关联的生成标注，更新选中状态
            // 保持主标注的选中状态，并更新关联的生成标注 ID
            if (annotationState.selectedId === updatedAnn.id || 
                selectedAnnotationIds.has(updatedAnn.id)) {
              const newRelatedIds = new Set([updatedAnn.id]);
              generatedAnnotations.forEach(genAnn => {
                newRelatedIds.add(genAnn.id);
              });
              setSelectedAnnotationIds(newRelatedIds);
            }
          } else {
            // 如果只有 regenerate_children 信号，删除旧的生成标注
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
        // 即使 sync 失败，也更新标注（使用现有的 regions）
        const existingDual = annotationState.annotations.find((a) => a.id === updatedAnn.id);
        const existingRegions = existingDual?.secondary?.regions || [];
        const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, existingRegions);
        annotationState.handleAnnotationUpdate(dualAnn);
      }
    },
    [currentSample, annotationState, syncBackend]
  );

  const handleDeleteAnnotation = useCallback(
    async (id: string) => {
      if (!currentSample) return;

      const syncAction: SyncAction = {
        action: 'delete',
        annotationId: id,
        extra: {},
      };

      try {
        await syncBackend(currentSample.id, [syncAction]);
        annotationState.handleAnnotationDelete(id);
        
        // 删除该标注对应的生成标注
        setGeneratedAnnotations(prev => prev.filter(ann => {
          const parentId = ann.extra?.parent_id || ann.extra?.parentId;
          return parentId !== id;
        }));
      } catch (error) {
        console.error('Sync failed:', error);
        annotationState.handleAnnotationDelete(id);
        
        // 删除该标注对应的生成标注
        setGeneratedAnnotations(prev => prev.filter(ann => {
          const parentId = ann.extra?.parent_id || ann.extra?.parentId;
          return parentId !== id;
        }));
      }
    },
    [currentSample, annotationState, syncBackend]
  );

  // ========================================================================
  // Navigation
  // ========================================================================

  const handleNext = useCallback(() => {
    if (currentIndex < samples.length - 1) {
      setCurrentIndex((c) => c + 1);
      annotationState.resetHistory();
    }
  }, [currentIndex, samples.length, annotationState]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex((c) => c - 1);
      annotationState.resetHistory();
    }
  }, [currentIndex, annotationState]);

  const handleSubmit = useCallback(async () => {
    if (!currentSample) return;
    try {
      // 保存主标注和生成的标注
      const annsToSave: Annotation[] = [];
      
      // 添加主标注，确保使用正确的 view 信息
      annotationState.annotations.forEach(dual => {
        const anns = dualToAnnotations(dual);
        // 从 annotationViews 中获取正确的 view 信息，并转换坐标
        const convertedAnns = anns.map(ann => {
          const view = annotationViews.get(ann.id) || VIEW_TIME_ENERGY;
          
          // 将起始点转换为中心点（后端期望中心点坐标，无论rect还是obb）
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
      
      // 添加生成的标注，也需要转换为中心点
      // 注意：生成的标注的annotatorId应该保持为null或系统标识，因为它们不是手动创建的
      generatedAnnotations.forEach(ann => {
        // 将起始点转换为中心点（后端期望中心点坐标，无论rect还是obb）
        if (ann.data) {
          const bboxData = ann.data as { x: number; y: number; width: number; height: number; rotation?: number };
          annsToSave.push({
            ...ann,
            data: originToCenter(bboxData),
            // 生成的标注不设置annotatorId，因为它们是由系统自动生成的
          });
        } else {
          annsToSave.push(ann);
        }
      });
      
      await api.saveAnnotations(currentSample.id, annsToSave, 'labeled');
      message.success(t('annotation.saved') || 'Saved');
      handleNext();
    } catch (error) {
      message.error('Failed to save annotations');
    }
  }, [currentSample, annotationState.annotations, generatedAnnotations, annotationViews, handleNext, t]);

  // ========================================================================
  // Keyboard Shortcuts
  // ========================================================================

  useAnnotationShortcuts({
    currentTool: annotationState.currentTool,
    onToolChange: annotationState.setCurrentTool,
    onNext: handleNext,
    onPrev: handlePrev,
    onSubmit: handleSubmit,
    onUndo: annotationState.undo,
    onRedo: annotationState.redo,
    disabled: isSyncing, // 同步时禁用快捷键
  });

  const handleSampleSelect = useCallback((index: number) => {
    setCurrentIndex(index);
    annotationState.resetHistory();
  }, [annotationState]);

  // ========================================================================
  // Get Image URLs from sample metadata
  // ========================================================================

  const timeEnergyImageUrl: string =
    currentSample?.metaData?.timeEnergyImageUrl || currentSample?.url || '';

  const lWdImageUrl: string = currentSample?.metaData?.lWdImageUrl || '';

  // ========================================================================
  // Selected Annotation Info
  // ========================================================================

  const selectedAnnotation = annotationState.annotations.find(
    (a) => a.id === annotationState.selectedId
  );
  const currentMappedRegions = selectedAnnotation?.secondary?.regions || [];

  // ========================================================================
  // Render
  // ========================================================================

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Spin size="large">
          <div style={{ minHeight: 200 }} />
        </Spin>
      </div>
    );
  }

  if (!dataset || samples.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Empty description="No samples found for this dataset" />
      </div>
    );
  }

  if (!currentSample) {
    return <div>{t('workspace.loading')}</div>;
  }

  // Check if labels are configured
  if (labels.length === 0) {
    return (
      <Layout
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Empty description={t('workspace.noLabelsConfigured')} />
      </Layout>
    );
  }

  return (
    <Layout style={{ height: '100%' }}>
      {/* Left Sidebar - Sample List */}
      <Sider width={250} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
        <SampleList
          samples={samples}
          currentIndex={currentIndex}
          onSampleSelect={handleSampleSelect}
        />
      </Sider>

      <Content style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Toolbar */}
        <AnnotationToolbar
          labels={labels}
          selectedLabel={annotationState.selectedLabel}
          onLabelChange={annotationState.setSelectedLabel}
          historyIndex={annotationState.historyIndex}
          historyLength={annotationState.history.length}
          onUndo={annotationState.undo}
          onRedo={annotationState.redo}
          currentTool={annotationState.currentTool}
          onToolChange={annotationState.setCurrentTool}
          onZoomIn={() => {
            dualCanvasAreaRef.current?.zoomIn();
          }}
          onZoomOut={() => {
            dualCanvasAreaRef.current?.zoomOut();
          }}
          onResetView={() => {
            dualCanvasAreaRef.current?.resetView();
          }}
          syncStatus={{
            isSyncing,
            isSyncReady,
          }}
        />

        {/* Dual Canvas Area */}
        <DualCanvasArea
          ref={dualCanvasAreaRef}
          timeEnergyImageUrl={timeEnergyImageUrl}
          lWdImageUrl={lWdImageUrl}
          annotations={canvasAnnotations}
          onAnnotationCreate={handleAnnotationCreate}
          onAnnotationUpdate={handleUpdateAnnotation}
          onAnnotationDelete={handleDeleteAnnotation}
          currentTool={annotationState.currentTool}
          labelColor={annotationState.selectedLabel?.color || '#ff0000'}
          selectedId={annotationState.selectedId}
          selectedAnnotationIds={selectedAnnotationIds}
          onSelect={handleAnnotationSelect}
          isSyncing={isSyncing}
          currentMappedRegions={currentMappedRegions}
        />
      </Content>

      {/* Right Sidebar */}
      <AnnotationSidebar
        annotations={sidebarAnnotations}
        selectedId={annotationState.selectedId}
        onAnnotationSelect={(id) => {
          handleAnnotationSelect(id);
          annotationState.setCurrentTool('select');
        }}
        onAnnotationDelete={handleDeleteAnnotation}
        currentIndex={currentIndex}
        totalSamples={samples.length}
        onPrev={handlePrev}
        onNext={handleNext}
        onSubmit={handleSubmit}
        renderAnnotationItem={(item, index) => {
          // 检查该标注是否被选中（包括通过关联标注选中）
          const isSelected = selectedAnnotationIds.has(item.id);
          
          return (
            <div
              style={{
                padding: '8px 16px',
                background: isSelected ? '#e6f7ff' : 'transparent',
                cursor: 'pointer',
                borderLeft:
                  isSelected
                    ? `4px solid ${item.labelColor || '#1890ff'}`
                    : '4px solid transparent',
              }}
              onClick={() => {
                handleAnnotationSelect(item.id);
                annotationState.setCurrentTool('select');
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {item.type === 'obb' ? (
                      <RotateRightOutlined />
                    ) : (
                      <BorderOutlined />
                    )}
                    <Tag color={item.labelColor}>{item.labelName}</Tag>
                    <span>#{index + 1}</span>
                  </div>
                  {/* 显示关联的生成标注数量 */}
                  {(() => {
                    // 找到所有关联的生成标注
                    const relatedGenerated = canvasAnnotations.filter(ann => {
                      const parentId = ann.extra?.parent_id || ann.extra?.parentId;
                      return parentId === item.id;
                    });
                    
                    if (relatedGenerated.length > 0) {
                      // 获取主标注的 view
                      const mainView = item.extra?.view || annotationViews.get(item.id) || VIEW_TIME_ENERGY;
                      
                      // 获取生成标注的 view（通常是另一个画板）
                      // 如果生成标注有多个，取第一个的 view
                      const generatedView = relatedGenerated[0]?.extra?.view;
                      
                      // 如果生成标注没有 view，根据主标注的 view 推断
                      // 主标注在 Time-Energy，生成标注应该在 L-omegad
                      // 主标注在 L-omegad，生成标注应该在 Time-Energy
                      const inferredGeneratedView = generatedView || 
                        (mainView === VIEW_TIME_ENERGY ? VIEW_L_OMEGAD : VIEW_TIME_ENERGY);
                      
                      // 格式化显示：主标注画板 → 生成标注数量 生成标注画板
                      const mainViewLabel = mainView === VIEW_TIME_ENERGY ? 'T-E' : 'L-omegad';
                      const generatedViewLabel = inferredGeneratedView === VIEW_TIME_ENERGY ? 'T-E' : 'L-omegad';
                      
                      return (
                        <div style={{ marginTop: 4, fontSize: 11, color: '#888' }}>
                          {mainViewLabel} → {relatedGenerated.length} {generatedViewLabel} mapped annotation{relatedGenerated.length > 1 ? 's' : ''}
                        </div>
                      );
                    }
                    return null;
                  })()}
                </div>
                <button
                  type="button"
                  onClick={(e: React.MouseEvent) => {
                    e.stopPropagation();
                    handleDeleteAnnotation(item.id);
                  }}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    cursor: 'pointer',
                    color: '#ff4d4f',
                    padding: '4px 8px',
                  }}
                >
                  <DeleteOutlined />
                </button>
              </div>
            </div>
          );
        }}
      />
    </Layout>
  );
};

export default FedoAnnotationWorkspace;
