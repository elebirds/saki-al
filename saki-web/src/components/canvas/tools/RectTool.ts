import { BaseTool } from './BaseTool';
import { ToolEventContext } from './types';
import { normalizeRect } from '../../../utils/canvasUtils';

/**
 * 矩形标注工具
 * 通过拖拽绘制矩形边界框
 */
export class RectTool extends BaseTool {
  readonly name = 'rect';

  onMouseDown(ctx: ToolEventContext): void {
    this.isDrawing = true;
    this.startPos = { x: ctx.pos.x, y: ctx.pos.y };
    this.drawingRect = { 
      x: ctx.pos.x, 
      y: ctx.pos.y, 
      w: 0, 
      h: 0 
    };
  }

  onMouseMove(ctx: ToolEventContext): void {
    if (!this.isDrawing || !this.startPos) return;
    
    this.drawingRect = {
      x: this.startPos.x,
      y: this.startPos.y,
      w: ctx.pos.x - this.startPos.x,
      h: ctx.pos.y - this.startPos.y,
    };
  }

  onMouseUp(_ctx: ToolEventContext): void {
    if (!this.isDrawing || !this.drawingRect) {
      this.reset();
      return;
    }

    // 检查是否有足够大的区域
    if (Math.abs(this.drawingRect.w) > 5 && Math.abs(this.drawingRect.h) > 5) {
      const normalizedRect = normalizeRect(this.drawingRect);
      
      this.completedAnnotation = {
        id: Date.now().toString(),
        sampleId: 'current',
        label: 'Object',
        type: 'rect',
        bbox: normalizedRect,
      };
    }

    this.isDrawing = false;
    this.drawingRect = null;
    this.startPos = null;
  }

  showCrosshair(): boolean {
    return true;
  }

  allowStageDrag(_hasSelection: boolean): boolean {
    return false;
  }
}
