/**
 * Canvas 组件模块
 * 
 * 提供标注画布相关的所有组件和工具
 */

// 主画布组件
export { default as AnnotationCanvas } from './AnnotationCanvas';
export type { 
  AnnotationCanvasRef, 
  AnnotationCanvasProps, 
  AnnotationCanvasCallbacks 
} from './AnnotationCanvas';

// 子组件
export { default as AnnotationItem } from './AnnotationItem';
export { default as Crosshair } from './Crosshair';
export { default as CanvasTransformer } from './CanvasTransformer';
export { default as NewAnnotationLayer } from './NewAnnotationLayer';

// Hooks
export { useDrawingTools } from './hooks';
export type { ToolType } from './hooks';

// 工具类型
export type { 
  DrawingTool,
  DrawingRect,
  ToolEventContext,
  ToolState,
  AnnotationCreateEvent,
} from './tools';

// 具体工具实现（如需扩展）
export { RectTool, ObbTool, SelectTool, BaseTool } from './tools';
