import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AnnotationCreateEvent, DrawingRect, DrawingTool, ToolEventContext} from '../tools/types';
import {RectTool} from '../tools/RectTool';
import {ObbTool} from '../tools/ObbTool';
import {SelectTool} from '../tools/SelectTool';
import {clampPoint} from '../../../utils/canvasUtils';
import {ANNOTATION_TOOL_SELECT, ANNOTATION_TYPE_OBB, ANNOTATION_TYPE_RECT, AnnotationToolType} from '../../../types';
import Konva from 'konva';

export type ToolType = AnnotationToolType;

interface UseDrawingToolsOptions {
    currentTool: ToolType;
    imageBounds: { width: number; height: number } | null;
    onAnnotationCreate?: (event: AnnotationCreateEvent) => void;
    onSelect?: (id: string | null) => void;
}

interface UseDrawingToolsReturn {
    /** 当前绘制中的矩形 */
    drawingRect: DrawingRect | null;
    /** 是否显示十字准线 */
    showCrosshair: boolean;
    /** 是否允许画布拖拽 */
    allowStageDrag: (hasSelection: boolean) => boolean;
    /** 鼠标按下处理 */
    handleMouseDown: (e: Konva.KonvaEventObject<MouseEvent>) => void;
    /** 鼠标移动处理 */
    handleMouseMove: (e: Konva.KonvaEventObject<MouseEvent>) => void;
    /** 鼠标释放处理 */
    handleMouseUp: (e: Konva.KonvaEventObject<MouseEvent>) => void;
    /** 当前光标位置（图像坐标） */
    cursorPos: { x: number; y: number } | null;
}

/**
 * 绘制工具管理 Hook
 * 负责工具切换、状态管理和事件分发
 */
export function useDrawingTools(options: UseDrawingToolsOptions): UseDrawingToolsReturn {
    const {currentTool, imageBounds, onAnnotationCreate, onSelect} = options;

    const [drawingRect, setDrawingRect] = useState<DrawingRect | null>(null);
    const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);

    // 工具实例缓存
    const toolsRef = useRef<Map<ToolType, DrawingTool>>(new Map());

    // 获取或创建工具实例
    const getTool = useCallback((type: ToolType): DrawingTool => {
        let tool = toolsRef.current.get(type);
        if (!tool) {
            switch (type) {
                case ANNOTATION_TYPE_RECT:
                    tool = new RectTool();
                    break;
                case ANNOTATION_TYPE_OBB:
                    tool = new ObbTool();
                    break;
                case ANNOTATION_TOOL_SELECT:
                default:
                    tool = new SelectTool();
                    break;
            }
            toolsRef.current.set(type, tool);
        }
        return tool;
    }, []);

    const activeTool = useMemo(() => getTool(currentTool), [currentTool, getTool]);

    // 工具切换时重置状态
    useEffect(() => {
        toolsRef.current.forEach((tool, type) => {
            if (type !== currentTool) {
                tool.reset();
            }
        });
        setDrawingRect(null);
    }, [currentTool]);

    // 创建事件上下文
    const createContext = useCallback((e: Konva.KonvaEventObject<MouseEvent>): ToolEventContext | null => {
        const stage = e.target.getStage();
        const pos = stage?.getRelativePointerPosition();

        if (!pos || !imageBounds) return null;

        const clampedPos = clampPoint(pos, imageBounds);

        return {
            pos: clampedPos,
            imageBounds,
            event: e,
        };
    }, [imageBounds]);

    // 检查并处理完成的标注
    const checkCompletedAnnotation = useCallback(() => {
        const completed = activeTool.getCompletedAnnotation();
        if (completed) {
            onAnnotationCreate?.(completed);
        }
    }, [activeTool, onAnnotationCreate]);

    const handleMouseDown = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
        const ctx = createContext(e);
        if (!ctx) return;

        // 对于选择工具，需要特殊处理取消选择
        if (currentTool === ANNOTATION_TOOL_SELECT) {
            const selectTool = activeTool as SelectTool;
            selectTool.onMouseDown(ctx);
            if (selectTool.shouldDeselect()) {
                onSelect?.(null);
            }
            return;
        }

        // 其他绘制工具需要先取消选择
        onSelect?.(null);

        activeTool.onMouseDown(ctx);
        setDrawingRect(activeTool.getState().drawingRect);

        // 检查是否有完成的标注（如 OBB 的最后一次点击）
        checkCompletedAnnotation();

        // 更新绘制状态
        setDrawingRect(activeTool.getState().drawingRect);
    }, [createContext, currentTool, activeTool, onSelect, checkCompletedAnnotation]);

    const handleMouseMove = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
        const ctx = createContext(e);
        if (!ctx) {
            setCursorPos(null);
            return;
        }

        // 更新光标位置
        if (activeTool.showCrosshair()) {
            setCursorPos(ctx.pos);
        } else {
            setCursorPos(null);
        }

        activeTool.onMouseMove(ctx);
        setDrawingRect(activeTool.getState().drawingRect);
    }, [createContext, activeTool]);

    const handleMouseUp = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
        const ctx = createContext(e);
        if (!ctx) return;

        activeTool.onMouseUp(ctx);

        // 检查是否有完成的标注
        checkCompletedAnnotation();

        // 更新绘制状态
        setDrawingRect(activeTool.getState().drawingRect);
    }, [createContext, activeTool, checkCompletedAnnotation]);

    const allowStageDrag = useCallback((hasSelection: boolean) => {
        return activeTool.allowStageDrag(hasSelection);
    }, [activeTool]);

    return {
        drawingRect,
        showCrosshair: activeTool.showCrosshair(),
        allowStageDrag,
        handleMouseDown,
        handleMouseMove,
        handleMouseUp,
        cursorPos,
    };
}
