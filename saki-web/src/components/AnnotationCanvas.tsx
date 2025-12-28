import { useState, useRef, useEffect, forwardRef, useImperativeHandle, useCallback } from 'react';
import { Stage, Layer, Image as KonvaImage } from 'react-konva';
import useImage from 'use-image';
import Konva from 'konva';
import { Annotation } from '../types';
import AnnotationItem from './canvas/AnnotationItem';
import Crosshair from './canvas/Crosshair';
import CanvasTransformer from './canvas/CanvasTransformer';
import NewAnnotationLayer from './canvas/NewAnnotationLayer';
import { useDrawingTools, ToolType } from './canvas/hooks';
import { AnnotationCreateEvent } from './canvas/tools/types';
import { calculateFitScale, calculateZoom } from '../utils/canvasUtils';

export interface AnnotationCanvasRef {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
}

/** 画布事件回调接口 */
export interface AnnotationCanvasCallbacks {
  /** 新标注创建事件 */
  onAnnotationCreate?: (event: AnnotationCreateEvent) => void;
  /** 标注更新事件 */
  onAnnotationUpdate?: (annotation: Annotation) => void;
  /** 标注删除事件 */
  onAnnotationDelete?: (id: string) => void;
  /** 标注选择事件 */
  onSelect?: (id: string | null) => void;
}

export interface AnnotationCanvasProps extends AnnotationCanvasCallbacks {
  /** 图像 URL */
  imageUrl: string;
  /** 标注列表 */
  annotations: Annotation[];
  /** 当前工具类型 */
  currentTool: ToolType;
  /** 当前标签颜色（用于新绘制的标注） */
  labelColor?: string;
  /** 当前选中的标注 ID */
  selectedId: string | null;
}

// 导出类型供外部使用
export type { AnnotationCreateEvent, ToolType };

/**
 * 标注画布组件
 * 
 * 一个可复用的画布组件，支持：
 * - 图像显示和缩放/平移
 * - 多种标注工具（矩形、OBB、选择）
 * - 标注的创建、编辑、删除
 * 
 * @example
 * ```tsx
 * <AnnotationCanvas
 *   imageUrl="/image.jpg"
 *   annotations={annotations}
 *   currentTool="rect"
 *   selectedId={selectedId}
 *   onAnnotationCreate={(event) => {
 *     // event.type: 'rect' | 'obb'
 *     // event.bbox: { x, y, width, height, rotation? }
 *     const newAnnotation = {
 *       id: generateId(),
 *       sampleId: currentSample.id,
 *       label: currentLabel,
 *       type: event.type,
 *       bbox: event.bbox,
 *     };
 *     setAnnotations([...annotations, newAnnotation]);
 *   }}
 *   onAnnotationUpdate={(ann) => updateAnnotation(ann)}
 *   onAnnotationDelete={(id) => deleteAnnotation(id)}
 *   onSelect={(id) => setSelectedId(id)}
 * />
 * ```
 */
const AnnotationCanvas = forwardRef<AnnotationCanvasRef, AnnotationCanvasProps>(({ 
  imageUrl, 
  annotations, 
  currentTool,
  labelColor = '#ff0000',
  selectedId,
  onAnnotationCreate,
  onAnnotationUpdate,
  onAnnotationDelete,
  onSelect,
}, ref) => {
  const [image] = useImage(imageUrl);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const transformerRef = useRef<Konva.Transformer>(null);

  // 图像边界
  const imageBounds = image ? { width: image.width, height: image.height } : null;

  // 使用绘制工具 Hook
  const {
    drawingRect,
    showCrosshair,
    allowStageDrag,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    cursorPos,
  } = useDrawingTools({
    currentTool,
    imageBounds,
    onAnnotationCreate,
    onSelect,
  });

  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      setScale(s => s * 1.2);
    },
    zoomOut: () => {
      setScale(s => s / 1.2);
    },
    resetView: () => {
      if (containerRef.current && image) {
        const { scale: newScale, position: newPos } = calculateFitScale(
          { width: containerRef.current.offsetWidth, height: containerRef.current.offsetHeight },
          { width: image.width, height: image.height }
        );
        setScale(newScale);
        setPosition(newPos);
      }
    }
  }));

  const selectedAnnotation = annotations.find(a => a.id === selectedId);

  // Responsive Stage & Initial Fit
  useEffect(() => {
    const checkSize = () => {
      if (containerRef.current && image) {
        const containerSize = {
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        };
        
        setStageSize(containerSize);

        const { scale: newScale, position: newPos } = calculateFitScale(
          containerSize,
          { width: image.width, height: image.height }
        );
        
        setScale(newScale);
        setPosition(newPos);
      }
    };
    
    if (image) {
      setTimeout(checkSize, 10);
    }
    
    window.addEventListener('resize', checkSize);
    return () => window.removeEventListener('resize', checkSize);
  }, [image]);

  // Handle Selection & Transformer
  useEffect(() => {
    if (selectedId && transformerRef.current && stageRef.current) {
      const node = stageRef.current.findOne('#' + selectedId);
      if (node) {
        transformerRef.current.nodes([node]);
        transformerRef.current.getLayer()?.batchDraw();
      }
    } else {
      transformerRef.current?.nodes([]);
      transformerRef.current?.getLayer()?.batchDraw();
    }
  }, [selectedId, annotations]);

  // Keyboard Delete
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
        onAnnotationDelete?.(selectedId);
        onSelect?.(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedId, onAnnotationDelete, onSelect]);

  // 滚轮缩放
  const handleWheelEvent = useCallback((e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;

    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const { scale: newScale, position: newPos } = calculateZoom(
      stage.scaleX(),
      { x: stage.x(), y: stage.y() },
      pointer,
      e.evt.deltaY
    );

    setScale(newScale);
    setPosition(newPos);
  }, []);

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', overflow: 'hidden', background: '#1e1e1e' }}>
      <Stage
        width={stageSize.width}
        height={stageSize.height}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => {/* cursorPos 在 hook 内部处理 */}}
        onMouseUp={handleMouseUp}
        onWheel={handleWheelEvent}
        scaleX={scale}
        scaleY={scale}
        x={position.x}
        y={position.y}
        draggable={allowStageDrag(!!selectedId)}
        ref={stageRef}
      >
        <Layer>
          {image && (
            <KonvaImage 
              image={image} 
            />
          )}
          
          {annotations.map((ann: Annotation) => (
            <AnnotationItem
              key={ann.id}
              annotation={ann}
              isSelected={selectedId === ann.id}
              scale={scale}
              image={image}
              stageX={position.x}
              stageY={position.y}
              currentTool={currentTool}
              onSelect={id => onSelect?.(id)}
              onUpdate={ann => onAnnotationUpdate?.(ann)}
            />
          ))}

          <NewAnnotationLayer 
            newRect={drawingRect} 
            labelColor={labelColor} 
            scale={scale} 
          />

          <Crosshair
            cursorPos={cursorPos}
            imageWidth={image ? image.width : 0}
            imageHeight={image ? image.height : 0}
            scale={scale}
            visible={showCrosshair && !!image}
          />

          <CanvasTransformer
            ref={transformerRef}
            selectedAnnotation={selectedAnnotation}
            currentTool={currentTool}
            image={image}
          />
        </Layer>
      </Stage>
    </div>
  );
});

AnnotationCanvas.displayName = 'AnnotationCanvas';

export default AnnotationCanvas;
