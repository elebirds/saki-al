import { useRef, forwardRef, useImperativeHandle } from 'react';
import { Stage, Layer, Image as KonvaImage } from 'react-konva';
import useImage from 'use-image';
import { Annotation } from '../../types';
import AnnotationItem from './AnnotationItem';
import Crosshair from './Crosshair';
import CanvasTransformer from './CanvasTransformer';
import NewAnnotationLayer from './NewAnnotationLayer';
import CoordinateDisplay from './CoordinateDisplay';
import { 
  useDrawingTools, 
  useCanvasView, 
  useTransformer, 
  useKeyboardShortcuts,
  ToolType 
} from './hooks';
import { AnnotationCreateEvent } from './tools/types';

// ============================================================================
// 类型定义
// ============================================================================

export interface AnnotationCanvasRef {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
}

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
  /** 当前标签颜色 */
  labelColor?: string;
  /** 当前选中的标注 ID */
  selectedId: string | null;
  /** 所有应该被选中的标注 ID 集合（用于关联标注的高亮显示） */
  selectedAnnotationIds?: Set<string>;
  /** 检查单个标注是否可编辑 */
  canEditAnnotation?: (annotation: Annotation) => boolean;
}

export type { AnnotationCreateEvent, ToolType };

// ============================================================================
// 组件实现
// ============================================================================

/**
 * 标注画布组件
 * 
 * 可复用的画布组件，支持：
 * - 图像显示和缩放/平移
 * - 多种标注工具（矩形、OBB、选择）
 * - 标注的创建、编辑、删除
 */
const AnnotationCanvas = forwardRef<AnnotationCanvasRef, AnnotationCanvasProps>(({
  imageUrl,
  annotations,
  currentTool,
  labelColor = '#ff0000',
  selectedId,
  selectedAnnotationIds,
  onAnnotationCreate,
  onAnnotationUpdate,
  onAnnotationDelete,
  onSelect,
  canEditAnnotation,
}, ref) => {
  // ========== Refs ==========
  const containerRef = useRef<HTMLDivElement>(null);
  
  // ========== 图像加载 ==========
  const [image] = useImage(imageUrl);
  const imageBounds = image ? { width: image.width, height: image.height } : null;

  // ========== 视图控制 ==========
  const {
    stageSize,
    scale,
    position,
    stageRef,
    zoomIn,
    zoomOut,
    resetView,
    handleWheel,
  } = useCanvasView({ image, containerRef });

  // ========== 绘制工具 ==========
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

  // ========== Transformer ==========
  const { transformerRef } = useTransformer({
    selectedId,
    annotations,
    stageRef,
  });

  // ========== 键盘快捷键 ==========
  useKeyboardShortcuts({
    selectedId,
    onDelete: onAnnotationDelete,
    onDeselect: () => onSelect?.(null),
  });

  // ========== 暴露方法 ==========
  useImperativeHandle(ref, () => ({ zoomIn, zoomOut, resetView }));

  // ========== 派生状态 ==========
  const selectedAnnotation = annotations.find(a => a.id === selectedId);

  // ========== 渲染 ==========
  return (
    <div 
      ref={containerRef} 
      className="h-full w-full overflow-hidden bg-[#1e1e1e]"
    >
      <Stage
        ref={stageRef}
        width={stageSize.width}
        height={stageSize.height}
        scaleX={scale}
        scaleY={scale}
        x={position.x}
        y={position.y}
        draggable={allowStageDrag(!!selectedId)}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
      >
        <Layer>
          {/* 背景图像 */}
          {image && <KonvaImage image={image} />}
          
          {/* 已有标注 */}
          {annotations.map(ann => {
            // 判断标注是否被选中：要么是主选中标注，要么在 selectedAnnotationIds 中
            const isSelected = selectedId === ann.id || (selectedAnnotationIds?.has(ann.id) ?? false);
            // 检查是否可编辑此标注
            const canEdit = canEditAnnotation ? canEditAnnotation(ann) : true;
            return (
              <AnnotationItem
                key={ann.id}
                annotation={ann}
                isSelected={isSelected}
                scale={scale}
                image={image}
                stageX={position.x}
                stageY={position.y}
                currentTool={currentTool}
                onSelect={id => onSelect?.(id)}
                onUpdate={updated => onAnnotationUpdate?.(updated)}
                canEdit={canEdit}
              />
            );
          })}

          {/* 正在绘制的标注 */}
          <NewAnnotationLayer newRect={drawingRect} labelColor={labelColor} scale={scale} />

          {/* 十字准线 */}
          <Crosshair
            cursorPos={cursorPos}
            imageWidth={image?.width ?? 0}
            imageHeight={image?.height ?? 0}
            scale={scale}
            visible={showCrosshair && !!image}
          />

          {/* 变换控制器 */}
          <CanvasTransformer
            ref={transformerRef}
            selectedAnnotation={selectedAnnotation}
            currentTool={currentTool}
            image={image}
            canEdit={selectedAnnotation ? (canEditAnnotation ? canEditAnnotation(selectedAnnotation) : true) : true}
          />
        </Layer>
      </Stage>
      
      {/* 坐标显示 */}
      <CoordinateDisplay
        cursorPos={cursorPos}
        visible={showCrosshair && !!image}
      />
    </div>
  );
});

AnnotationCanvas.displayName = 'AnnotationCanvas';

export default AnnotationCanvas;
