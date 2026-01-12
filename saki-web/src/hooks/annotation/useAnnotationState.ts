/**
 * useAnnotationState Hook
 * 
 * 管理标注工作空间的公共状态，包括：
 * - 标注列表和选中状态
 * - 历史记录（撤销/重做）
 * - 工具选择
 * - 标签选择
 */

import { useState, useCallback, useRef, useEffect } from 'react';

// 基础类型约束：只需要有 id 属性
export interface AnnotationLike {
  id: string;
}

export interface UseAnnotationStateOptions<T extends AnnotationLike = AnnotationLike> {
  initialAnnotations?: T[];
}

export interface UseAnnotationStateReturn<T extends AnnotationLike = AnnotationLike> {
  // State
  annotations: T[];
  history: T[][];
  historyIndex: number;
  selectedId: string | null;
  currentTool: 'select' | 'rect' | 'obb';
  selectedLabel: any | null;
  
  // Setters
  setAnnotations: (annotations: T[]) => void;
  setSelectedId: (id: string | null) => void;
  setCurrentTool: (tool: 'select' | 'rect' | 'obb') => void;
  setSelectedLabel: (label: any | null) => void;
  
  // History operations
  addToHistory: (newAnnotations: T[]) => void;
  undo: () => void;
  redo: () => void;
  resetHistory: () => void;
  setHistory: (history: T[][]) => void;
  setHistoryIndex: (index: number) => void;
  
  // Annotation operations
  handleAnnotationCreate: (annotation: T) => void;
  handleAnnotationUpdate: (updatedAnnotation: T) => void;
  handleAnnotationDelete: (id: string) => void;
}

export function useAnnotationState<T extends AnnotationLike = AnnotationLike>(
  options: UseAnnotationStateOptions<T> = {}
): UseAnnotationStateReturn<T> {
  const { initialAnnotations = [] } = options;
  
  const [annotations, setAnnotations] = useState<T[]>(initialAnnotations);
  const [history, setHistory] = useState<T[][]>([initialAnnotations]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTool, setCurrentTool] = useState<'select' | 'rect' | 'obb'>('select');
  const [selectedLabel, setSelectedLabel] = useState<any | null>(null);

  // 使用 ref 来跟踪最新的 historyIndex，避免闭包问题
  const historyIndexRef = useRef(0);
  useEffect(() => {
    historyIndexRef.current = historyIndex;
  }, [historyIndex]);

  const addToHistory = useCallback((newAnnotations: T[]) => {
    setHistory((prevHistory) => {
      const currentIndex = historyIndexRef.current;
      const newHistory = prevHistory.slice(0, currentIndex + 1);
      newHistory.push(newAnnotations);
      setHistoryIndex(newHistory.length - 1);
      return newHistory;
    });
    setAnnotations(newAnnotations);
  }, []);

  const undo = useCallback(() => {
    if (historyIndex > 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      setAnnotations(history[newIndex]);
    }
  }, [history, historyIndex]);

  const redo = useCallback(() => {
    if (historyIndex < history.length - 1) {
      const newIndex = historyIndex + 1;
      setHistoryIndex(newIndex);
      setAnnotations(history[newIndex]);
    }
  }, [history, historyIndex]);

  const resetHistory = useCallback(() => {
    setAnnotations([]);
    setHistory([[]]);
    setHistoryIndex(0);
    setSelectedId(null);
  }, []);

  const setHistoryCallback = useCallback((newHistory: T[][]) => {
    setHistory(newHistory);
  }, []);

  const setHistoryIndexCallback = useCallback((index: number) => {
    setHistoryIndex(index);
  }, []);

  const handleAnnotationCreate = useCallback((annotation: T) => {
    addToHistory([...annotations, annotation]);
  }, [annotations, addToHistory]);

  const handleAnnotationUpdate = useCallback((updatedAnnotation: T) => {
    addToHistory(annotations.map(a => a.id === updatedAnnotation.id ? updatedAnnotation : a));
  }, [annotations, addToHistory]);

  const handleAnnotationDelete = useCallback((id: string) => {
    addToHistory(annotations.filter(a => a.id !== id));
    if (selectedId === id) {
      setSelectedId(null);
    }
  }, [annotations, selectedId, addToHistory]);

  return {
    // State
    annotations,
    history,
    historyIndex,
    selectedId,
    currentTool,
    selectedLabel,
    
    // Setters
    setAnnotations,
    setSelectedId,
    setCurrentTool,
    setSelectedLabel,
    
    // History operations
    addToHistory,
    undo,
    redo,
    resetHistory,
    setHistory: setHistoryCallback,
    setHistoryIndex: setHistoryIndexCallback,
    
    // Annotation operations
    handleAnnotationCreate,
    handleAnnotationUpdate,
    handleAnnotationDelete,
  };
}

