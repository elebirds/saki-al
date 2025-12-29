/**
 * DualCanvasArea Component
 * 
 * 双画布区域组件，用于 FEDO 标注系统
 * - 左侧：Time-Energy 视图（主标注区域）
 * - 右侧：L-ωd 视图（映射区域，只读）
 */

import React, { useRef, forwardRef, useImperativeHandle } from 'react';
import { AnnotationCanvas, AnnotationCanvasRef } from '../canvas';
import { Annotation, MappedRegion } from '../../types';

export interface DualCanvasAreaProps {
  // 画布数据
  timeEnergyImageUrl: string;
  lWdImageUrl: string;
  annotations: Annotation[];
  
  // 标注操作
  onAnnotationCreate: (event: {
    type: 'rect' | 'obb';
    bbox: { x: number; y: number; width: number; height: number; rotation?: number };
  }) => void;
  onAnnotationUpdate: (annotation: Annotation) => void;
  onAnnotationDelete: (id: string) => void;
  
  // 工具和选择
  currentTool: 'select' | 'rect' | 'obb';
  labelColor: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  
  // 同步状态
  isSyncing: boolean;
  
  // 当前选中标注的映射区域
  currentMappedRegions: MappedRegion[];
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
  onSelect,
  isSyncing,
  currentMappedRegions,
}, ref) => {
  const timeEnergyCanvasRef = useRef<AnnotationCanvasRef>(null);
  const lWdCanvasRef = useRef<AnnotationCanvasRef>(null);

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
        pointerEvents: isSyncing ? 'none' : 'auto',
        opacity: isSyncing ? 0.6 : 1,
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
          annotations={annotations}
          onAnnotationCreate={onAnnotationCreate}
          onAnnotationUpdate={onAnnotationUpdate}
          onAnnotationDelete={onAnnotationDelete}
          currentTool={currentTool}
          labelColor={labelColor}
          selectedId={selectedId}
          onSelect={onSelect}
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
          annotations={[]} // TODO: Convert mappedRegions to polygon Annotation format
          currentTool="select" // Force select mode - L-ωd view is read-only
          selectedId={null}
          onSelect={() => {}}
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

