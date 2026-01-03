import { DrawingTool, ToolState, ToolEventContext, DrawingRect, AnnotationCreateEvent } from './types';

/**
 * 绘制工具基类
 * 提供通用的状态管理和默认实现
 */
export abstract class BaseTool implements DrawingTool {
  abstract readonly name: string;
  
  protected drawingRect: DrawingRect | null = null;
  protected isDrawing: boolean = false;
  protected startPos: { x: number; y: number } | null = null;
  protected completedAnnotation: AnnotationCreateEvent | null = null;

  getState(): ToolState {
    return {
      drawingRect: this.drawingRect,
      isDrawing: this.isDrawing,
    };
  }

  reset(): void {
    this.drawingRect = null;
    this.isDrawing = false;
    this.startPos = null;
    this.completedAnnotation = null;
  }

  abstract onMouseDown(ctx: ToolEventContext): void;
  abstract onMouseMove(ctx: ToolEventContext): void;
  abstract onMouseUp(ctx: ToolEventContext): void;

  getCompletedAnnotation(): AnnotationCreateEvent | null {
    const annotation = this.completedAnnotation;
    this.completedAnnotation = null;
    return annotation;
  }

  showCrosshair(): boolean {
    return true;
  }

  allowStageDrag(_hasSelection: boolean): boolean {
    return false;
  }
}
