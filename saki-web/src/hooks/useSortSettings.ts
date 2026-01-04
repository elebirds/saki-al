/**
 * useSortSettings Hook
 * 
 * 管理数据集的排序设置（从 localStorage 读取和保存）
 */

import { useState, useEffect, useCallback, useMemo } from 'react';

export type SortBy = 'name' | 'status' | 'created_at' | 'updated_at' | 'remark';
export type SortOrder = 'asc' | 'desc';

export interface SortOptions {
  sortBy?: SortBy;
  sortOrder?: SortOrder;
}

export interface UseSortSettingsReturn {
  sortBy: SortBy;
  sortOrder: SortOrder;
  setSortBy: (sortBy: SortBy) => void;
  setSortOrder: (sortOrder: SortOrder) => void;
  sortOptions: SortOptions;
}

/**
 * 从 localStorage 读取排序设置
 */
function getSortSettingsFromStorage(datasetId: string | undefined): { sortBy: SortBy; sortOrder: SortOrder } {
  if (!datasetId) {
    return { sortBy: 'created_at', sortOrder: 'desc' };
  }
  
  const sortSettingsStr = localStorage.getItem(`dataset_${datasetId}_sort`);
  if (sortSettingsStr) {
    try {
      const sortSettings = JSON.parse(sortSettingsStr);
      return {
        sortBy: sortSettings.sortBy || 'created_at',
        sortOrder: sortSettings.sortOrder || 'desc',
      };
    } catch (e) {
      console.error('Failed to parse sort settings:', e);
    }
  }
  
  return { sortBy: 'created_at', sortOrder: 'desc' };
}

/**
 * 保存排序设置到 localStorage
 */
function saveSortSettingsToStorage(datasetId: string | undefined, sortBy: SortBy, sortOrder: SortOrder) {
  if (!datasetId) return;
  
  const sortSettings = { sortBy, sortOrder };
  localStorage.setItem(`dataset_${datasetId}_sort`, JSON.stringify(sortSettings));
}

/**
 * 使用排序设置 hook
 * 
 * @param datasetId 数据集 ID
 * @param defaultSortBy 默认排序字段
 * @param defaultSortOrder 默认排序顺序
 */
export function useSortSettings(
  datasetId: string | undefined,
  defaultSortBy: SortBy = 'created_at',
  defaultSortOrder: SortOrder = 'desc'
): UseSortSettingsReturn {
  const initialSettings = getSortSettingsFromStorage(datasetId);
  const [sortBy, setSortByState] = useState<SortBy>(initialSettings.sortBy || defaultSortBy);
  const [sortOrder, setSortOrderState] = useState<SortOrder>(initialSettings.sortOrder || defaultSortOrder);

  // 当 datasetId 改变时，重新读取排序设置
  useEffect(() => {
    if (datasetId) {
      const savedSettings = getSortSettingsFromStorage(datasetId);
      setSortByState(savedSettings.sortBy || defaultSortBy);
      setSortOrderState(savedSettings.sortOrder || defaultSortOrder);
    }
  }, [datasetId, defaultSortBy, defaultSortOrder]);

  // 保存排序设置到 localStorage
  useEffect(() => {
    saveSortSettingsToStorage(datasetId, sortBy, sortOrder);
  }, [datasetId, sortBy, sortOrder]);

  const setSortBy = useCallback((newSortBy: SortBy) => {
    setSortByState(newSortBy);
  }, []);

  const setSortOrder = useCallback((newSortOrder: SortOrder) => {
    setSortOrderState(newSortOrder);
  }, []);

  // 使用 useMemo 稳定 sortOptions 对象的引用
  const sortOptions: SortOptions = useMemo(() => ({
    sortBy,
    sortOrder,
  }), [sortBy, sortOrder]);

  return {
    sortBy,
    sortOrder,
    setSortBy,
    setSortOrder,
    sortOptions,
  };
}

