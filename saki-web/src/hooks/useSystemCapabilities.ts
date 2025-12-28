/**
 * useSystemCapabilities Hook
 * 
 * Manages system type information and frontend capability registration.
 * - Fetches available task types and annotation systems from backend
 * - Registers frontend's supported annotation systems on startup
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../services/api';
import { AvailableTypes, AnnotationSystemType, TypeInfo } from '../types';

// ============================================================================
// Frontend Supported Annotation Systems
// ============================================================================

/**
 * List of annotation systems supported by this frontend.
 * Add new systems here when implementing new annotation UIs.
 */
const SUPPORTED_ANNOTATION_SYSTEMS: AnnotationSystemType[] = [
  'classic',  // Standard image annotation
  'fedo',     // FEDO dual-view annotation
];

const FRONTEND_VERSION = '1.0.0';

// Generate a unique client ID for this browser session
function getClientId(): string {
  let clientId = sessionStorage.getItem('saki_client_id');
  if (!clientId) {
    clientId = `web_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    sessionStorage.setItem('saki_client_id', clientId);
  }
  return clientId;
}

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
  /** Whether frontend capabilities have been registered */
  isRegistered: boolean;
  /** Refresh available types from backend */
  refresh: () => Promise<void>;
  /** Get TypeInfo for a specific task type */
  getTaskTypeInfo: (type: string) => TypeInfo | undefined;
  /** Get TypeInfo for a specific annotation system */
  getAnnotationSystemInfo: (type: string) => TypeInfo | undefined;
  /** Check if this frontend supports a given annotation system */
  supportsAnnotationSystem: (type: AnnotationSystemType) => boolean;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useSystemCapabilities(): UseSystemCapabilitiesReturn {
  const [availableTypes, setAvailableTypes] = useState<AvailableTypes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRegistered, setIsRegistered] = useState(false);
  
  const registeredRef = useRef(false);

  // Load available types from backend
  const loadTypes = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const types = await api.getAvailableTypes();
      setAvailableTypes(types);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load types';
      setError(message);
      console.error('Failed to load available types:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Register frontend capabilities
  const registerCapabilities = useCallback(async () => {
    if (registeredRef.current) return;
    
    try {
      const clientId = getClientId();
      
      // Register each supported annotation system
      for (const systemType of SUPPORTED_ANNOTATION_SYSTEMS) {
        await api.registerAnnotationCapability({
          systemType,
          version: FRONTEND_VERSION,
          features: getSystemFeatures(systemType),
          clientId,
        });
      }
      
      registeredRef.current = true;
      setIsRegistered(true);
      console.log('Frontend capabilities registered successfully');
    } catch (err) {
      console.warn('Failed to register frontend capabilities:', err);
      // Don't set error - this is not critical for operation
    }
  }, []);

  // Load types and register on mount
  useEffect(() => {
    loadTypes();
    registerCapabilities();
  }, [loadTypes, registerCapabilities]);

  // Helper to get type info
  const getTaskTypeInfo = useCallback((type: string): TypeInfo | undefined => {
    return availableTypes?.taskTypes.find(t => t.value === type);
  }, [availableTypes]);

  const getAnnotationSystemInfo = useCallback((type: string): TypeInfo | undefined => {
    return availableTypes?.annotationSystems.find(t => t.value === type);
  }, [availableTypes]);

  const supportsAnnotationSystem = useCallback((type: AnnotationSystemType): boolean => {
    return SUPPORTED_ANNOTATION_SYSTEMS.includes(type);
  }, []);

  return {
    availableTypes,
    loading,
    error,
    isRegistered,
    refresh: loadTypes,
    getTaskTypeInfo,
    getAnnotationSystemInfo,
    supportsAnnotationSystem,
  };
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get features list for a specific annotation system
 */
function getSystemFeatures(systemType: AnnotationSystemType): string[] {
  switch (systemType) {
    case 'classic':
      return ['rect', 'obb', 'zoom', 'pan', 'undo', 'redo'];
    case 'fedo':
      return ['rect', 'obb', 'dual-view', 'coordinate-mapping', 'non-monotonic-split'];
    default:
      return [];
  }
}

export default useSystemCapabilities;
