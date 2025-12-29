/**
 * useSystemCapabilities Hook
 * 
 * Manages system type information and frontend capability registration.
 * - Fetches available task types and annotation systems from backend
 * - Registers frontend's supported annotation systems on startup
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { AvailableTypes, TypeInfo } from '../types';

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
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useSystemCapabilities(): UseSystemCapabilitiesReturn {
  const [availableTypes, setAvailableTypes] = useState<AvailableTypes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load available types from backend
  const loadTypes = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const types = await api.getAvailableTypes();
      // TODO: Register frontend capabilities here if needed
      setAvailableTypes(types);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load types';
      setError(message);
      console.error('Failed to load available types:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load types and register on mount
  useEffect(() => {
    loadTypes();
  }, [loadTypes]);

  // Helper to get type info
  const getTaskTypeInfo = useCallback((type: string): TypeInfo | undefined => {
    return availableTypes?.taskTypes.find(t => t.value === type);
  }, [availableTypes]);

  return {
    availableTypes,
    loading,
    error,
    refresh: loadTypes,
    getTaskTypeInfo
  };
}

export default useSystemCapabilities;
