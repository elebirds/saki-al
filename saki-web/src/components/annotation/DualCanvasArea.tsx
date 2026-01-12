/**
 * DualCanvasArea Component
 * 
 * 双画布区域组件，用于 FEDO 标注系统
 * - 左侧：Time-Energy 视图（可标注）
 * - 右侧：L-ωd 视图（可标注）
 * 
 * 双侧都可以添加标注，通过 view 信息区分标注所属视图
 */

import { useRef, forwardRef, useImperativeHandle, useMemo } from 'react';
import { AnnotationCanvas, AnnotationCanvasRef } from '../canvas';
import { Annotation, MappedRegion } from '../../types';

// FEDO view 标识符
export const VIEW_TIME_ENERGY = 'time-energy';
export const VIEW_L_OMEGAD = 'L-omegad';

export interface DualCanvasAreaProps {
  // 画布数据
  timeEnergyImageUrl: string;
  lWdImageUrl: string;
  annotations: Annotation[];
  
  // 标注操作
  onAnnotationCreate?: (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
    view: string; // 'time-energy' 或 'L-omegad'
  }) => void;
  onAnnotationUpdate: (annotation: Annotation) => void;
  onAnnotationDelete: (id: string) => void;
  
  // 工具和选择
  currentTool: 'select' | 'rect' | 'obb';
  labelColor: string;
  selectedId: string | null;
  selectedAnnotationIds?: Set<string>; // 所有应该被选中的标注 ID（包括关联的）
  onSelect: (id: string | null) => void;
  
  // 当前选中标注的映射区域
  currentMappedRegions: MappedRegion[];
  
  // 权限控制
  canEditAnnotation?: (annotation: Annotation) => boolean;
}

export interface DualCanvasAreaRef {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
}

export const DualCanvasArea = forwardRef<DualCanvasAreaRef, DualCanvasAreaProps>(({
  timeEnergyImageUrl,
  lWdImageUrl,
  annotations,
  onAnnotationCreate,
  onAnnotationUpdate,
  onAnnotationDelete,
  currentTool,
  labelColor,
  selectedId,
  selectedAnnotationIds,
  onSelect,
  currentMappedRegions,
  canEditAnnotation,
}, ref) => {
  const timeEnergyCanvasRef = useRef<AnnotationCanvasRef>(null);
  const lWdCanvasRef = useRef<AnnotationCanvasRef>(null);

  // 根据 view 过滤标注，分别显示在对应的画布上
  const timeEnergyAnnotations = useMemo(() => {
    return annotations.filter(ann => ann.extra?.view === VIEW_TIME_ENERGY);
  }, [annotations]);

  const lOmegadAnnotations = useMemo(() => {
    return annotations.filter(ann => ann.extra?.view === VIEW_L_OMEGAD);
  }, [annotations]);

  // 为 Time-Energy 画布创建标注时的回调
  const handleTimeEnergyCreate = (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    if (onAnnotationCreate) {
      onAnnotationCreate({
        ...event,
        view: VIEW_TIME_ENERGY,
      });
    }
  };

  // 为 L-ωd 画布创建标注时的回调
  const handleLOmegadCreate = (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => {
    if (onAnnotationCreate) {
      onAnnotationCreate({
        ...event,
        view: VIEW_L_OMEGAD,
      });
    }
  };

  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      timeEnergyCanvasRef.current?.zoomIn();
      lWdCanvasRef.current?.zoomIn();
    },
    zoomOut: () => {
      timeEnergyCanvasRef.current?.zoomOut();
      lWdCanvasRef.current?.zoomOut();
    },
    resetView: () => {
      timeEnergyCanvasRef.current?.resetView();
      lWdCanvasRef.current?.resetView();
    },
  }));

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
        width: '100%',
        height: '100%',
      }}
    >
      {/* Left: Time-Energy View */}
      <div
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          background: '#333',
          borderRight: '2px solid #666',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 8,
            left: 8,
            zIndex: 10,
            background: 'rgba(0,0,0,0.6)',
            color: '#fff',
            padding: '4px 8px',
            borderRadius: 4,
            fontSize: 12,
          }}
        >
          Time-Energy
        </div>
        <AnnotationCanvas
          ref={timeEnergyCanvasRef}
          imageUrl={timeEnergyImageUrl}
          annotations={timeEnergyAnnotations}
          onAnnotationCreate={onAnnotationCreate ? handleTimeEnergyCreate : undefined}
          onAnnotationUpdate={onAnnotationUpdate}
          onAnnotationDelete={onAnnotationDelete}
          currentTool={currentTool}
          labelColor={labelColor}
          selectedId={selectedId}
          selectedAnnotationIds={selectedAnnotationIds}
          onSelect={onSelect}
          canEditAnnotation={canEditAnnotation}
        />
      </div>

      {/* Right: L-ωd View (Read-only mapped regions) */}
      <div
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          background: '#333',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 8,
            left: 8,
            zIndex: 10,
            background: 'rgba(0,0,0,0.6)',
            color: '#fff',
            padding: '4px 8px',
            borderRadius: 4,
            fontSize: 12,
          }}
        >
          L-ωd
        </div>
        <AnnotationCanvas
          ref={lWdCanvasRef}
          imageUrl={lWdImageUrl}
          annotations={lOmegadAnnotations}
          onAnnotationCreate={onAnnotationCreate ? handleLOmegadCreate : undefined}
          onAnnotationUpdate={onAnnotationUpdate}
          onAnnotationDelete={onAnnotationDelete}
          currentTool={currentTool}
          labelColor={labelColor}
          selectedId={selectedId}
          selectedAnnotationIds={selectedAnnotationIds}
          onSelect={onSelect}
          canEditAnnotation={canEditAnnotation}
        />
        {/* Mapped regions count indicator */}
        {currentMappedRegions.length > 0 && (
          <div
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              zIndex: 10,
              background: 'rgba(0,0,0,0.6)',
              color: '#fff',
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: 12,
            }}
          >
            {currentMappedRegions.length} mapped region
            {currentMappedRegions.length > 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
});

DualCanvasArea.displayName = 'DualCanvasArea';

