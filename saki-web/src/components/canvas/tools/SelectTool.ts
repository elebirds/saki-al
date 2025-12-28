import { DrawingTool, ToolState, ToolEventContext } from './types';

/**
 * 选择工具
 * 用于选择和操作已有的标注
 */
export class SelectTool implements DrawingTool {
  readonly name = 'select';
  
  private pendingDeselect: boolean = false;

  getState(): ToolState {
    return {
      drawingRect: null,
      isDrawing: false,
    };
  }

  reset(): void {
    this.pendingDeselect = false;
  }

  onMouseDown(ctx: ToolEventContext): void {
    // 检查是否点击了空白区域
    const target = ctx.event.target;
    const clickedOnEmpty = target === target.getStage() || 
                           target.className === 'Image';
    
    if (clickedOnEmpty) {
      this.pendingDeselect = true;
    }
  }

  onMouseMove(_ctx: ToolEventContext): void {
    // 选择工具不需要处理移动事件
  }

  onMouseUp(_ctx: ToolEventContext): void {
    this.pendingDeselect = false;
  }

  getCompletedAnnotation(): null {
    return null;
  }

  /** 检查是否需要取消选择 */
  shouldDeselect(): boolean {
    const result = this.pendingDeselect;
    this.pendingDeselect = false;
    return result;
  }

  showCrosshair(): boolean {
    return false;
  }

  allowStageDrag(hasSelection: boolean): boolean {
    return !hasSelection;
  }
}
