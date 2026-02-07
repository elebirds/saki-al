import {useEffect, useRef} from 'react';
import Konva from 'konva';
import {Annotation} from '../../../types';

interface UseTransformerOptions {
    /** 选中的标注 ID */
    selectedId: string | null;
    /** 标注列表（用于依赖更新） */
    annotations: unknown[];
    /** Stage ref */
    stageRef: React.RefObject<Konva.Stage>;
}

interface UseTransformerReturn {
    /** Transformer ref */
    transformerRef: React.RefObject<Konva.Transformer>;
}

/**
 * Transformer 管理 Hook
 * 处理选中标注的变换控制器
 */
export function useTransformer(options: UseTransformerOptions): UseTransformerReturn {
    const {selectedId, annotations, stageRef} = options;
    const transformerRef = useRef<Konva.Transformer>(null);

    useEffect(() => {
        if (!transformerRef.current || !stageRef.current) {
            return;
        }

        // 检查选中的标注是否在当前画布的标注列表中
        const annotationExists = (annotations as Annotation[]).some((ann: Annotation) => ann.id === selectedId);

        if (selectedId && annotationExists) {
            // 只有在当前画布中存在该标注时才附加 transformer
            const node = stageRef.current.findOne('#' + selectedId);
            if (node) {
                transformerRef.current.nodes([node]);
                transformerRef.current.getLayer()?.batchDraw();
            } else {
                // 如果找不到节点，清除 transformer
                transformerRef.current.nodes([]);
                transformerRef.current.getLayer()?.batchDraw();
            }
        } else {
            // 如果没有选中或标注不在当前画布，清除 transformer
            transformerRef.current.nodes([]);
            transformerRef.current.getLayer()?.batchDraw();
        }
    }, [selectedId, annotations, stageRef]);

    return {transformerRef};
}

interface UseKeyboardShortcutsOptions {
    /** 选中的标注 ID */
    selectedId: string | null;
    /** 删除回调 */
    onDelete?: (id: string) => void;
    /** 取消选择回调 */
    onDeselect?: () => void;
}

/**
 * 键盘快捷键 Hook
 * 处理删除等快捷键操作
 */
export function useKeyboardShortcuts(options: UseKeyboardShortcutsOptions): void {
    const {selectedId, onDelete, onDeselect} = options;

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
                onDelete?.(selectedId);
                onDeselect?.();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [selectedId, onDelete, onDeselect]);
}
