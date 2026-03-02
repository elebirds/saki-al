/**
 * FEDO Annotation Utilities
 *
 * FEDO 标注相关的工具函数
 */

import {
    Annotation,
    ANNOTATION_TYPE_OBB,
    AnnotationType,
    BoundingBox,
    DetectionAnnotationType,
    DualViewAnnotation,
    MappedRegion,
} from '../types';
import {VIEW_L_OMEGAD, VIEW_TIME_ENERGY} from '../components/annotation/DualCanvasArea';
import {canvasDataToGeometry, geometryToCanvasData, resolveAnnotationView} from './annotationGeometry';

/** Convert DualViewAnnotation to Annotation[] for AnnotationCanvas (one per view) */
export function dualToAnnotations(dual: DualViewAnnotation): Annotation[] {
    const annotations: Annotation[] = [];

    annotations.push({
        id: dual.id,
        groupId: dual.groupId || dual.id,
        lineageId: dual.lineageId || dual.id,
        parentId: dual.parentId ?? undefined,
        sampleId: dual.sampleId,
        labelId: dual.labelId,
        labelName: dual.labelName,
        labelColor: dual.labelColor,
        type: dual.primary.type as AnnotationType,
        source: dual.source || 'manual',
        geometry: canvasDataToGeometry(dual.primary.type as AnnotationType, dual.primary.bbox as Record<string, any>),
        attrs: {
            view: VIEW_TIME_ENERGY,
        },
        annotatorId: dual.annotatorId,
    });

    return annotations;
}

/** Convert Annotation to DualViewAnnotation */
export function annotationToDual(ann: Annotation, regions: MappedRegion[] = []): DualViewAnnotation {
    const data = geometryToCanvasData(ann.type, ann.geometry);
    const bbox: BoundingBox = {
        x: data.x || 0,
        y: data.y || 0,
        width: data.width || 0,
        height: data.height || 0,
        rotation: data.rotation,
    };

    const extraRegions = (ann.attrs?.secondary?.regions || regions) as MappedRegion[];

    return {
        id: ann.id,
        groupId: ann.groupId || ann.id,
        lineageId: ann.lineageId || ann.id,
        parentId: ann.parentId ?? undefined,
        sampleId: ann.sampleId || '',
        labelId: ann.labelId,
        labelName: ann.labelName || '',
        labelColor: ann.labelColor || '#ff0000',
        annotatorId: ann.annotatorId,
        source: ann.source || 'manual',
        primary: {
            type: ann.type as DetectionAnnotationType,
            bbox,
        },
        secondary: {
            regions: extraRegions,
        },
    };
}

/** Convert backend generated annotations to Annotation[] */
export function generatedToAnnotations(
    generated: Array<Record<string, any>>,
    groupId: string,
    labelId: string,
    labelName: string,
    labelColor: string,
    annotatorId?: string | null
): Annotation[] {
    return generated.map((gen) => {
        const inferredType = (gen.type || ANNOTATION_TYPE_OBB) as AnnotationType;
        const data = geometryToCanvasData(inferredType, gen.geometry);
        const view = resolveAnnotationView(gen) || VIEW_L_OMEGAD;
        const type = (gen.type || ANNOTATION_TYPE_OBB) as AnnotationType;
        const resolvedLabelId = gen.labelId || gen.label_id || labelId;
        const resolvedLabelName = gen.labelName || gen.label_name || labelName;
        const resolvedLabelColor = gen.labelColor || gen.label_color || labelColor;
        const source = (gen.source || 'system') as any;
        const attrs = gen.attrs || {};
        const resolvedGroupId = gen.groupId || gen.group_id || groupId;
        const resolvedLineageId = gen.lineageId || gen.lineage_id || gen.id;

        // 后端已经转换为左上角坐标，直接使用
        const bboxData = {
            x: data.x || 0,
            y: data.y || 0,
            width: data.width || 0,
            height: data.height || 0,
            rotation: data.rotation || 0,
        };

        return {
            id: gen.id || `generated-${Date.now()}-${Math.random()}`,
            groupId: resolvedGroupId,
            lineageId: resolvedLineageId,
            labelId: resolvedLabelId,
            labelName: resolvedLabelName,
            labelColor: resolvedLabelColor,
            type: type,
            source: source,
            geometry: gen.geometry || canvasDataToGeometry(type, bboxData as Record<string, any>),
            annotatorId: gen.annotatorId || gen.annotator_id || annotatorId,
            attrs: {
                ...attrs,
                view: view,
                mapping_method: attrs.mapping_method || attrs.mappingMethod || 'placeholder',
            },
        };
    });
}

/** Convert backend generated annotations to MappedRegion[] (for backward compatibility) */
export function generatedToRegions(generated: Array<Record<string, any>>): MappedRegion[] {
    return generated
        .filter((gen) => {
            const view = resolveAnnotationView(gen);
            return view === VIEW_L_OMEGAD;
        })
        .map((gen, index) => {
            const type = (gen.type || ANNOTATION_TYPE_OBB) as AnnotationType;
            const data = geometryToCanvasData(type, gen.geometry);
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
                timeRange: [0, 0] as [number, number],
                polygonPoints,
                isPrimary: index === 0,
            };
        });
}

/**
 * 判断标注是否是生成的标注
 */
export function isGeneratedAnnotation(ann: Annotation): boolean {
    const source = ann.source as string;
    return (
        source === 'auto' ||
        source === 'system' ||
        source === 'fedo_mapping'
    );
}
