/**
 * useSystemCapabilities Hook
 *
 * Provides cached system type information.
 * Fetching is triggered once at app startup via useInitSystemCapabilities.
 */

import { useCallback, useEffect } from 'react';
import { useSystemStore } from '../../store/systemStore';
import { AvailableTypes, TypeInfo } from '../../types';

// ============================================================================
// Hook Interface
// ============================================================================

interface UseSystemCapabilitiesReturn {
  /** Available types loaded from backend */
  availableTypes: AvailableTypes | null;
  /** Whether types are being loaded */
  loading: boolean;
  /** Error message if loading failed */
  error: string | null;
  /** Refresh available types from backend */
  refresh: () => Promise<void>;
  /** Get TypeInfo for a specific task type */
  getTaskTypeInfo: (type: string) => TypeInfo | undefined;
    /** Get label for a specific dataset type */
    getDatasetTypeLabel: (type: string) => string | undefined;
    /** Get color for a specific dataset type */
    getDatasetTypeColor: (type: string) => string;
    /** Get TypeInfo for a specific dataset type */
    getDatasetTypeInfo: (type: string) => TypeInfo | undefined;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useSystemCapabilities(): UseSystemCapabilitiesReturn {
  const availableTypes = useSystemStore((state) => state.availableTypes);
  const loading = useSystemStore((state) => state.loading);
  const error = useSystemStore((state) => state.error);
  const refresh = useSystemStore((state) => state.refreshAvailableTypes);

  const getTaskTypeInfo = useCallback(
    (type: string): TypeInfo | undefined => {
      return availableTypes?.taskTypes.find((t) => t.value === type);
    },
    [availableTypes]
  );

  const getDatasetTypeInfo = useCallback(
    (type: string): TypeInfo | undefined => {
      return availableTypes?.datasetTypes.find((t) => t.value === type);
    },
    [availableTypes]
  );

  const getDatasetTypeLabel = useCallback(
    (type: string): string | undefined => {
      return getDatasetTypeInfo(type)?.label;
    },
    [getDatasetTypeInfo]
  );

  const getDatasetTypeColor = useCallback(
    (type: string): string => {
      return getDatasetTypeInfo(type)?.color || 'default';
    },
    [getDatasetTypeInfo]
  );

  return {
    availableTypes,
    loading,
    error,
    refresh,
    getTaskTypeInfo,
    getDatasetTypeLabel,
    getDatasetTypeColor,
    getDatasetTypeInfo,
  };
}

/**
 * Initialize available types once on app startup.
 */
export function useInitSystemCapabilities() {
  const loadAvailableTypes = useSystemStore((state) => state.loadAvailableTypes);

  useEffect(() => {
    loadAvailableTypes();
  }, [loadAvailableTypes]);
}

export default useSystemCapabilities;
