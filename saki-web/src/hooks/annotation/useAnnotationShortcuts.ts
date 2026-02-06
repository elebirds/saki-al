/**
 * useAnnotationShortcuts Hook
 *
 * 管理标注工作空间的快捷键
 */

import {useEffect} from 'react';

export interface UseAnnotationShortcutsOptions {
    currentTool: 'select' | 'rect' | 'obb';
    onToolChange: (tool: 'select' | 'rect' | 'obb') => void;
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
                    onToolChange('select');
                    break;
                case 'r':
                    onToolChange('rect');
                    break;
                case 'o':
                    onToolChange('obb');
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
    }, [currentTool, onToolChange, onNext, onPrev, onSubmit, onUndo, onRedo, disabled]);
}

