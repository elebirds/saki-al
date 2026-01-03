import { BaseTool } from './BaseTool';
import { ToolEventContext, ToolState } from './types';
import { calculateObbRect, finalizeObbRect } from '../../../utils/canvasUtils';

type ObbStep = 'none' | 'width' | 'height';

/**
 * 方向包围盒（OBB）标注工具
 * 三步绘制：
 * 1. 第一次点击确定起点
 * 2. 移动鼠标绘制宽度和角度，第二次点击确定
 * 3. 移动鼠标绘制高度，第三次点击完成
 */
export class ObbTool extends BaseTool {
  readonly name = 'obb';
  
  private step: ObbStep = 'none';

  getState(): ToolState {
    return {
      ...super.getState(),
      extra: { step: this.step },
    };
  }

  reset(): void {
    super.reset();
    this.step = 'none';
  }

  onMouseDown(ctx: ToolEventContext): void {
    if (this.step === 'none') {
      // 步骤1: 开始绘制基线（宽度）
      this.step = 'width';
      this.startPos = { x: ctx.pos.x, y: ctx.pos.y };
      this.drawingRect = { 
        x: ctx.pos.x, 
        y: ctx.pos.y, 
        w: 0, 
        h: 0, 
        rotation: 0 
      };
    } else if (this.step === 'width') {
      // 步骤2: 完成基线，开始绘制高度
      this.step = 'height';
    } else if (this.step === 'height') {
      // 步骤3: 完成高度，生成最终标注
      if (this.drawingRect) {
        const finalRect = finalizeObbRect(this.drawingRect);
        
        this.completedAnnotation = {
          type: 'obb',
          bbox: finalRect,
        };
      }
      // 重置绘制状态，但保留 completedAnnotation
      this.step = 'none';
      this.drawingRect = null;
      this.isDrawing = false;
      this.startPos = null;
    }
  }

  onMouseMove(ctx: ToolEventContext): void {
    if (this.step === 'none' || !this.startPos) return;

    const obbRect = calculateObbRect(
      this.startPos, 
      ctx.pos, 
      this.step as 'width' | 'height', 
      this.drawingRect
    );
    
    if (obbRect) {
      this.drawingRect = obbRect;
    }
  }

  onMouseUp(_ctx: ToolEventContext): void {
    // OBB 工具通过点击来推进步骤，不使用 mouseUp
  }

  showCrosshair(): boolean {
    return true;
  }

  allowStageDrag(_hasSelection: boolean): boolean {
    return false;
  }
}
