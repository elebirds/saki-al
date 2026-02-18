/**
 * useFedoAnnotations Hook
 *
 * FEDO 标注工作空间的标注处理逻辑（不依赖后端同步）。
 */

import {useCallback, useMemo, useState} from 'react';
import {message} from 'antd';
import {
    Annotation,
    AnnotationDraftItem,
    AnnotationSyncActionItem,
    AnnotationType,
    DualViewAnnotation,
    MappedRegion,
} from '../../types';
import {UseAnnotationStateReturn} from './useAnnotationState';
import {annotationToDual, isGeneratedAnnotation,} from '../../utils/fedoAnnotations';
import {VIEW_L_OMEGAD, VIEW_TIME_ENERGY} from '../../components/annotation/DualCanvasArea';
import {
    attrsFromAnnotationLike,
    canvasDataToGeometry,
    geometryToCanvasData,
    resolveAnnotationView,
} from '../../utils/annotationGeometry';
import {generateUUID} from '../../utils/uuid';

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
    /** 可选：同步回调，返回最新完整标注列表 */
    onSyncActions?: (actions: AnnotationSyncActionItem[]) => Promise<Annotation[] | null>;
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
        onSyncActions,
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

    const getGroupId = useCallback((annotation: Annotation): string => {
        return annotation.groupId || annotation.id;
    }, []);

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
                groupId: dual.groupId || dual.id,
                lineageId: dual.lineageId || dual.id,
                sampleId: dual.sampleId,
                labelId: dual.labelId,
                labelName: dual.labelName,
                labelColor: dual.labelColor,
                type: dual.primary.type as AnnotationType,
                source: 'manual',
                annotatorId: dual.annotatorId,
                geometry: canvasDataToGeometry(dual.primary.type as AnnotationType, dual.primary.bbox as Record<string, any>),
                attrs: {
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

        const groupId = getGroupId(selectedAnn);
        const relatedIds = new Set<string>();
        canvasAnnotations.forEach((ann) => {
            if (getGroupId(ann) === groupId) {
                relatedIds.add(ann.id);
            }
        });
        const primary = canvasAnnotations.find(
            (ann) => getGroupId(ann) === groupId && !isGeneratedAnnotation(ann)
        ) || selectedAnn;
        annotationState.setSelectedId(primary.id);
        setSelectedAnnotationIds(relatedIds);
    }, [canvasAnnotations, annotationState, getGroupId]);

    const buildDraftItem = useCallback((annotation: Annotation): AnnotationDraftItem => {
        return {
            id: annotation.id,
            projectId: projectId || undefined,
            sampleId: currentSampleId,
            labelId: annotation.labelId,
            groupId: annotation.groupId || annotation.id,
            lineageId: annotation.lineageId || annotation.id,
            parentId: annotation.parentId ?? null,
            viewRole: annotation.viewRole || 'main',
            type: annotation.type,
            source: annotation.source || 'manual',
            geometry: annotation.geometry,
            attrs: attrsFromAnnotationLike(annotation),
            confidence: annotation.confidence ?? 1,
            annotatorId: annotation.annotatorId ?? currentUserId ?? null,
        };
    }, [projectId, currentSampleId, currentUserId]);

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

        const generatedByGroup = new Map<string, Annotation[]>();
        generated.forEach((genAnn) => {
            const groupId = getGroupId(genAnn);
            if (!groupId) return;
            if (!generatedByGroup.has(groupId)) {
                generatedByGroup.set(groupId, []);
            }
            generatedByGroup.get(groupId)!.push(genAnn);
        });

        const dualAnns: DualViewAnnotation[] = mainAnnotations.map((ann) => {
            const groupId = getGroupId(ann);
            const relatedGenerated = groupId ? generatedByGroup.get(groupId) || [] : [];
            const regions: MappedRegion[] = relatedGenerated
                .filter(gen => resolveAnnotationView(gen) === VIEW_L_OMEGAD)
                .map((gen, index) => {
                    const data = geometryToCanvasData(gen.type, gen.geometry);
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
            const view = resolveAnnotationView(ann) || VIEW_TIME_ENERGY;
            views.set(ann.id, view);
        });
        setAnnotationViews(views);

        setBaseAnnotations(dualAnns);
        setBaseHistory([dualAnns]);
        setBaseHistoryIndex(0);
        setBaseSelectedId(null);
        setGeneratedAnnotations(generated);
    }, [getGroupId, setBaseAnnotations, setBaseHistory, setBaseHistoryIndex, setBaseSelectedId]);

    const triggerSync = useCallback(async (
        actions: AnnotationSyncActionItem[]
    ) => {
        if (!onSyncActions) return;
        const updated = await onSyncActions(actions);
        if (updated) {
            applyBaseAnnotations(updated);
        }
    }, [onSyncActions, applyBaseAnnotations]);

    // 创建标注
    const handleAnnotationCreate = useCallback(async (event: {
        type: 'rect' | 'obb';
        bbox: { x: number; y: number; width: number; height: number; rotation?: number };
        view: string;
    }) => {
        if (!hasAnyEditPermission) {
            if (t) message.warning(t('annotation.workspace.noEditPermission'));
            return;
        }

        if (!annotationState.selectedLabel) {
            if (t) message.warning(t('annotation.workspace.noLabelSelected'));
            return;
        }

        if (!currentSampleId) return;

        const newId = generateUUID();
        const view = event.view || VIEW_TIME_ENERGY;

        const newAnn: DualViewAnnotation = {
            id: newId,
            groupId: newId,
            lineageId: newId,
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
            groupId: newId,
            lineageId: newId,
            sampleId: currentSampleId,
            labelId: annotationState.selectedLabel.id,
            labelName: annotationState.selectedLabel.name || 'unknown',
            labelColor: annotationState.selectedLabel.color || '#ff0000',
            viewRole: 'main',
            type: event.type,
            source: 'manual',
            geometry: canvasDataToGeometry(event.type, event.bbox as Record<string, any>),
            attrs: {view},
            annotatorId: currentUserId,
        };

        await triggerSync([{
            type: 'add',
            groupId: newId,
            data: buildDraftItem(baseAnnotation),
        }]);
    }, [hasAnyEditPermission, annotationState, currentSampleId, currentUserId, t, buildDraftItem, triggerSync]);

    // 更新标注
    const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
        if (!currentSampleId) return;

        if (!canEditAnnotation(updatedAnn)) {
            if (t) message.warning(t('annotation.workspace.cannotEditOthersAnnotation'));
            return;
        }

        const dual = annotationState.annotations.find(d => d.id === updatedAnn.id);
        if (dual) {
            const updatedData = geometryToCanvasData(updatedAnn.type, updatedAnn.geometry);
            const updatedDual: DualViewAnnotation = {
                ...dual,
                primary: {
                    type: updatedAnn.type as 'rect' | 'obb',
                    bbox: {
                        x: updatedData.x,
                        y: updatedData.y,
                        width: updatedData.width,
                        height: updatedData.height,
                        rotation: updatedData.rotation,
                    },
                },
            };
            annotationState.handleAnnotationUpdate(updatedDual);
        }
        const view = resolveAnnotationView(updatedAnn) || annotationViews.get(updatedAnn.id) || VIEW_TIME_ENERGY;
        const updatedWithView: Annotation = {
            ...updatedAnn,
            groupId: updatedAnn.groupId || updatedAnn.id,
            lineageId: updatedAnn.lineageId || updatedAnn.id,
            attrs: {...attrsFromAnnotationLike(updatedAnn), view},
        };
        await triggerSync([{
            type: 'update',
            groupId: updatedWithView.groupId || updatedAnn.id,
            data: buildDraftItem(updatedWithView),
        }]);
    }, [currentSampleId, annotationState, canEditAnnotation, t, annotationViews, buildDraftItem, triggerSync]);

    // 删除标注
    const handleDeleteAnnotation = useCallback(async (id: string) => {
        if (!currentSampleId) return;

        const annotation = canvasAnnotations.find(a => a.id === id);
        if (annotation && !canEditAnnotation(annotation)) {
            if (t) message.warning(t('annotation.workspace.cannotDeleteOthersAnnotation'));
            return;
        }

        const groupId = annotation ? getGroupId(annotation) : id;
        annotationState.handleAnnotationDelete(id);
        setGeneratedAnnotations(prev => prev.filter(ann => getGroupId(ann) !== groupId));
        await triggerSync([{
            type: 'delete',
            groupId: groupId,
        }]);
    }, [currentSampleId, annotationState, canvasAnnotations, canEditAnnotation, t, triggerSync, getGroupId]);

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
