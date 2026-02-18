/**
 * useAnnotationShortcuts Hook
 *
 * 管理标注工作空间的快捷键
 */

import {useEffect} from 'react';
import {
    ANNOTATION_TYPE_OBB,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TOOL_SELECT,
    AnnotationToolType,
    DEFAULT_DETECTION_ANNOTATION_TYPES,
    DetectionAnnotationType,
} from '../../types';

export interface UseAnnotationShortcutsOptions {
    currentTool: AnnotationToolType;
    onToolChange: (tool: AnnotationToolType) => void;
    enabledTools?: DetectionAnnotationType[];
    onNext: () => void;
    onPrev: () => void;
    onSubmit: () => void;
    onUndo: () => void;
    onRedo: () => void;
    /** 是否禁用快捷键（例如在同步中） */
    disabled?: boolean;
}

export function useAnnotationShortcuts(options: UseAnnotationShortcutsOptions): void {
    const {
        currentTool,
        onToolChange,
        enabledTools = DEFAULT_DETECTION_ANNOTATION_TYPES,
        onNext,
        onPrev,
        onSubmit,
        onUndo,
        onRedo,
        disabled = false,
    } = options;

    useEffect(() => {
        if (disabled) {
            return;
        }

        const handleKeyDown = (e: KeyboardEvent) => {
            // 忽略输入框中的输入
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
                return;
            }

            switch (e.key.toLowerCase()) {
                case 'v':
                    onToolChange(ANNOTATION_TOOL_SELECT);
                    break;
                case 'r':
                    if (enabledTools.includes(ANNOTATION_TYPE_RECT)) onToolChange(ANNOTATION_TYPE_RECT);
                    break;
                case 'o':
                    if (enabledTools.includes(ANNOTATION_TYPE_OBB)) onToolChange(ANNOTATION_TYPE_OBB);
                    break;
                case 'arrowright':
                    onNext();
                    break;
                case 'arrowleft':
                    onPrev();
                    break;
                case 's':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        onSubmit();
                    }
                    break;
                case 'z':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        if (e.shiftKey) {
                            onRedo();
                        } else {
                            onUndo();
                        }
                    }
                    break;
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [currentTool, onToolChange, enabledTools.join(','), onNext, onPrev, onSubmit, onUndo, onRedo, disabled]);
}
