/**
 * FEDO Annotation Utilities
 * 
 * FEDO 标注相关的工具函数
 */

import { Annotation, DualViewAnnotation, MappedRegion, BoundingBox, AnnotationType } from '../types';
import { VIEW_TIME_ENERGY, VIEW_L_OMEGAD } from '../components/annotation/DualCanvasArea';

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
    source: 'manual',
    data: dual.primary.bbox,
    annotatorId: dual.annotatorId,
    extra: {
      view: VIEW_TIME_ENERGY, // 默认主标注在 Time-Energy 视图
    },
  });
  
  return annotations;
}

/** Convert Annotation to DualViewAnnotation */
export function annotationToDual(ann: Annotation, regions: MappedRegion[] = []): DualViewAnnotation {
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
    groupId: ann.groupId || ann.id,
    lineageId: ann.lineageId || ann.id,
    parentId: ann.parentId ?? undefined,
    sampleId: ann.sampleId || '',
    labelId: ann.labelId,
    labelName: ann.labelName || '',
    labelColor: ann.labelColor || '#ff0000',
    annotatorId: ann.annotatorId,
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
export function generatedToAnnotations(
  generated: Array<Record<string, any>>,
  groupId: string,
  labelId: string,
  labelName: string,
  labelColor: string,
  annotatorId?: string | null
): Annotation[] {
  return generated.map((gen) => {
    const data = gen.data || {};
    const view = gen.extra?.view || gen.view || VIEW_L_OMEGAD;
    const type = (gen.type || 'obb') as AnnotationType;
    const resolvedLabelId = gen.labelId || gen.label_id || labelId;
    const resolvedLabelName = gen.labelName || gen.label_name || labelName;
    const resolvedLabelColor = gen.labelColor || gen.label_color || labelColor;
    const source = (gen.source || 'system') as any;
    const extra = gen.extra || {};
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
      data: bboxData,
      annotatorId: gen.annotatorId || gen.annotator_id || annotatorId,
      extra: {
        ...extra,
        view: view,
        mapping_method: extra.mapping_method || extra.mappingMethod || 'placeholder',
      },
    };
  });
}

/** Convert backend generated annotations to MappedRegion[] (for backward compatibility) */
export function generatedToRegions(generated: Array<Record<string, any>>): MappedRegion[] {
  return generated
    .filter((gen) => {
      const view = gen.extra?.view || gen.view;
      return view === VIEW_L_OMEGAD;
    })
    .map((gen, index) => {
      const data = gen.data || {};
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
    source === 'model' ||
    source === 'fedo_mapping'
  );
}
