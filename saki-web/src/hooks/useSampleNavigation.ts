/**
 * useSampleNavigation Hook
 * 
 * 统一管理样本导航逻辑（上一张、下一张）
 */

import { useCallback } from 'react';

export interface UseSampleNavigationOptions {
  /** 当前样本索引 */
  currentIndex: number;
  /** 样本总数 */
  totalSamples: number;
  /** 设置当前样本索引 */
  setCurrentIndex: (index: number) => void;
  /** 切换到下一个样本前的回调 */
  onBeforeNext?: () => void;
  /** 切换到上一个样本前的回调 */
  onBeforePrev?: () => void;
}

export interface UseSampleNavigationReturn {
  /** 切换到下一个样本 */
  handleNext: () => void;
  /** 切换到上一个样本 */
  handlePrev: () => void;
  /** 切换到指定索引的样本 */
  handleGoTo: (index: number) => void;
  /** 是否可以切换到下一个 */
  canGoNext: boolean;
  /** 是否可以切换到上一个 */
  canGoPrev: boolean;
}

/**
 * 使用样本导航 hook
 */
export function useSampleNavigation(
  options: UseSampleNavigationOptions
): UseSampleNavigationReturn {
  const {
    currentIndex,
    totalSamples,
    setCurrentIndex,
    onBeforeNext,
    onBeforePrev,
  } = options;

  const handleNext = useCallback(() => {
    if (currentIndex < totalSamples - 1) {
      onBeforeNext?.();
      setCurrentIndex(currentIndex + 1);
    }
  }, [currentIndex, totalSamples, setCurrentIndex, onBeforeNext]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) {
      onBeforePrev?.();
      setCurrentIndex(currentIndex - 1);
    }
  }, [currentIndex, setCurrentIndex, onBeforePrev]);

  const handleGoTo = useCallback((index: number) => {
    if (index >= 0 && index < totalSamples) {
      setCurrentIndex(index);
    }
  }, [totalSamples, setCurrentIndex]);

  const canGoNext = currentIndex < totalSamples - 1;
  const canGoPrev = currentIndex > 0;

  return {
    handleNext,
    handlePrev,
    handleGoTo,
    canGoNext,
    canGoPrev,
  };
}

