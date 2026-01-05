/**
 * useDatasetLoader Hook
 * 
 * 统一管理数据集、标签和样本的加载逻辑
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { message } from 'antd';
import { api } from '../services/api';
import { Dataset, Label, Sample } from '../types';
import { useSortSettings, SortOptions } from './useSortSettings';

export interface UseDatasetLoaderOptions {
  /** 数据集 ID */
  datasetId: string | undefined;
  /** 是否自动加载（默认 true） */
  autoLoad?: boolean;
  /** 是否显示加载错误提示（默认 true） */
  showError?: boolean;
}

export interface UseDatasetLoaderReturn {
  /** 数据集 */
  dataset: Dataset | null;
  /** 标签列表 */
  labels: Label[];
  /** 样本列表 */
  samples: Sample[];
  /** 是否正在加载 */
  loading: boolean;
  /** 当前样本索引 */
  currentIndex: number;
  /** 设置当前样本索引 */
  setCurrentIndex: (index: number) => void;
  /** 当前样本 */
  currentSample: Sample | undefined;
  /** 排序设置 */
  sortOptions: SortOptions;
  /** 重新加载数据 */
  reload: () => Promise<void>;
  /** 更新样本状态 */
  updateSampleStatus: (sampleId: string, status: 'labeled' | 'unlabeled' | 'skipped') => void;
}

/**
 * 使用数据集加载器 hook
 */
export function useDatasetLoader(
  options: UseDatasetLoaderOptions
): UseDatasetLoaderReturn {
  const { datasetId, autoLoad = true, showError = true } = options;
  const [searchParams] = useSearchParams();
  
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);

  // 使用排序设置 hook
  const { sortBy, sortOrder, sortOptions } = useSortSettings(datasetId);

  // 当前样本
  const currentSample = samples[currentIndex];

  // 加载数据
  const loadData = useCallback(async () => {
    if (!datasetId) {
      setLoading(false);
      return;
    }

    setLoading(true);

    try {
      const [ds, loadedLabels, loadedSamples] = await Promise.all([
        api.getDataset(datasetId),
        api.getLabels(datasetId),
        api.getSamples(datasetId, { sortBy, sortOrder }),
      ]);

      if (ds) setDataset(ds);
      setLabels(loadedLabels);
      setSamples(loadedSamples);

      // 如果 URL 中有 sampleId 参数，跳转到对应的样本
      const sampleId = searchParams.get('sampleId');
      if (sampleId && loadedSamples.length > 0) {
        const index = loadedSamples.findIndex(s => s.id === sampleId);
        if (index !== -1) {
          setCurrentIndex(index);
        }
      }
    } catch (error) {
      console.error('Failed to load dataset:', error);
      if (showError) {
        message.error('加载数据失败');
      }
    } finally {
      setLoading(false);
    }
  }, [datasetId, sortBy, sortOrder, searchParams, showError]);

  // 自动加载
  useEffect(() => {
    if (autoLoad) {
      loadData();
    }
  }, [autoLoad, loadData]);

  // 更新样本状态
  const updateSampleStatus = useCallback((sampleId: string, status: 'labeled' | 'unlabeled' | 'skipped') => {
    setSamples((prevSamples) =>
      prevSamples.map((sample) =>
        sample.id === sampleId ? { ...sample, status } : sample
      )
    );
  }, []);

  return {
    dataset,
    labels,
    samples,
    loading,
    currentIndex,
    setCurrentIndex,
    currentSample,
    sortOptions,
    reload: loadData,
    updateSampleStatus,
  };
}

