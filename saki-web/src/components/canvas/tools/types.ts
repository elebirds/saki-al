import Konva from 'konva';
import { Annotation } from '../../../types';

/** 绘制过程中的临时矩形数据 */
export interface DrawingRect {
  x: number;
  y: number;
  w: number;
  h: number;
  rotation?: number;
}

/** 图像边界信息 */
export interface ImageBounds {
  width: number;
  height: number;
}

/** 工具事件上下文 */
export interface ToolEventContext {
  /** 鼠标/触摸位置（相对于图像坐标） */
  pos: { x: number; y: number };
  /** 图像边界 */
  imageBounds: ImageBounds;
  /** Konva 事件对象 */
  event: Konva.KonvaEventObject<MouseEvent>;
}

/** 工具状态 */
export interface ToolState {
  /** 当前绘制中的矩形 */
  drawingRect: DrawingRect | null;
  /** 是否正在绘制 */
  isDrawing: boolean;
  /** 额外的工具特定状态 */
  extra?: Record<string, unknown>;
}

/** 绘制工具接口 */
export interface DrawingTool {
  /** 工具名称 */
  readonly name: string;
  
  /** 获取当前工具状态 */
  getState(): ToolState;
  
  /** 重置工具状态 */
  reset(): void;
  
  /** 鼠标按下事件处理 */
  onMouseDown(ctx: ToolEventContext): void;
  
  /** 鼠标移动事件处理 */
  onMouseMove(ctx: ToolEventContext): void;
  
  /** 鼠标释放事件处理 */
  onMouseUp(ctx: ToolEventContext): void;
  
  /** 获取绘制完成的标注（如果有） */
  getCompletedAnnotation(): AnnotationCreateEvent | null;
  
  /** 是否显示十字准线 */
  showCrosshair(): boolean;
  
  /** 是否允许画布拖拽 */
  allowStageDrag(hasSelection: boolean): boolean;
}

/** 工具工厂函数类型 */
export type ToolFactory = (options?: ToolOptions) => DrawingTool;

/** 工具选项 */
export interface ToolOptions {
  /** 标签颜色 */
  labelColor?: string;
  /** 选择回调 */
  onSelect?: (id: string | null) => void;
}

/** 标注创建事件数据 */
export interface AnnotationCreateEvent {
  type: 'rect' | 'obb';
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
    rotation?: number;
  };
}

/** 画布事件回调接口 */
export interface CanvasEventCallbacks {
  /** 新标注创建 */
  onAnnotationCreate?: (event: AnnotationCreateEvent) => void;
  /** 标注更新 */
  onAnnotationUpdate?: (annotation: Annotation) => void;
  /** 标注删除 */
  onAnnotationDelete?: (id: string) => void;
  /** 标注选择 */
  onAnnotationSelect?: (id: string | null) => void;
}
