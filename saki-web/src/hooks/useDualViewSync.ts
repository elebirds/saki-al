/**
 * useDualViewSync Hook
 * 
 * Manages Worker communication and real-time annotation mapping between
 * Time-Energy and L-ωd views for FEDO data annotation.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { FedoMappingWorker, getFedoMappingWorker, disposeFedoMappingWorker } from '../workers';
import { BoundingBox, MappedRegion } from '../types';

// ============================================================================
// Types
// ============================================================================

interface BboxMappingResult {
  indices: [number, number][];
  L: number[];
  Wd: number[];
  regions: MappedRegion[];
}

interface UseDualViewSyncReturn {
  /** Whether the worker is initialized and ready */
  isReady: boolean;
  /** Whether a mapping operation is in progress */
  isMapping: boolean;
  /** Current mapped regions (for the selected annotation) */
  mappedRegions: MappedRegion[];
  /** Last error message, if any */
  error: string | null;
  /** Initialize the worker with a sample's lookup table URL */
  initializeWithLookupTable: (lookupTableUrl: string) => Promise<void>;
  /** Map a bounding box from Time-Energy view to L-ωd regions */
  mapBboxToLWd: (bbox: BoundingBox) => Promise<BboxMappingResult>;
  /** Map specific indices to physical coordinates */
  mapIndicesToPhysical: (indices: [number, number][]) => Promise<{ L: number[]; Wd: number[] }>;
  /** Find indices contained in an L-ωd polygon (reverse mapping) */
  findIndicesInPolygon: (polygon: [number, number][]) => Promise<[number, number][]>;
  /** Dispose the worker */
  dispose: () => void;
}

// ============================================================================
// Hook Implementation
// ============================================================================

export function useDualViewSync(): UseDualViewSyncReturn {
  const [isReady, setIsReady] = useState(false);
  const [isMapping, setIsMapping] = useState(false);
  const [mappedRegions, setMappedRegions] = useState<MappedRegion[]>([]);
  const [error, setError] = useState<string | null>(null);
  
  const workerRef = useRef<FedoMappingWorker | null>(null);
  const currentSampleIdRef = useRef<string | null>(null);

  // ========================================================================
  // Initialize Worker with Sample
  // ========================================================================

  const initializeWithLookupTable = useCallback(async (lookupTableUrl: string) => {
    // Skip if already initialized for this URL
    if (currentSampleIdRef.current === lookupTableUrl && isReady) {
      return;
    }

    setIsReady(false);
    setError(null);

    try {
      // Fetch lookup table binary from the provided URL
      const response = await fetch(lookupTableUrl);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch lookup table: ${response.statusText}`);
      }
      
      const buffer = await response.arrayBuffer();
      
      // Get or create worker
      if (!workerRef.current) {
        workerRef.current = getFedoMappingWorker();
      }
      
      // Initialize worker with the lookup table
      await workerRef.current.initialize(buffer);
      
      currentSampleIdRef.current = lookupTableUrl;
      setIsReady(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      console.error('Failed to initialize dual view sync:', err);
    }
  }, [isReady]);

  // ========================================================================
  // Map Bounding Box to L-ωd Space
  // ========================================================================

  const mapBboxToLWd = useCallback(async (bbox: BoundingBox): Promise<BboxMappingResult> => {
    if (!workerRef.current || !isReady) {
      throw new Error('Worker not initialized');
    }

    setIsMapping(true);
    setError(null);

    try {
      const result = await workerRef.current.mapBboxToPhysical(bbox);
      setMappedRegions(result.regions);
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      throw err;
    } finally {
      setIsMapping(false);
    }
  }, [isReady]);

  // ========================================================================
  // Map Indices to Physical Coordinates
  // ========================================================================

  const mapIndicesToPhysical = useCallback(async (indices: [number, number][]): Promise<{ L: number[]; Wd: number[] }> => {
    if (!workerRef.current || !isReady) {
      throw new Error('Worker not initialized');
    }

    setIsMapping(true);
    setError(null);

    try {
      return await workerRef.current.mapIndicesToPhysical(indices);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      throw err;
    } finally {
      setIsMapping(false);
    }
  }, [isReady]);

  // ========================================================================
  // Find Indices in L-ωd Polygon (Reverse Mapping)
  // ========================================================================

  const findIndicesInPolygon = useCallback(async (polygon: [number, number][]): Promise<[number, number][]> => {
    if (!workerRef.current || !isReady) {
      throw new Error('Worker not initialized');
    }

    setIsMapping(true);
    setError(null);

    try {
      return await workerRef.current.findIndicesInPolygon(polygon);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      throw err;
    } finally {
      setIsMapping(false);
    }
  }, [isReady]);

  // ========================================================================
  // Dispose Worker
  // ========================================================================

  const dispose = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.dispose();
      workerRef.current = null;
    }
    disposeFedoMappingWorker();
    currentSampleIdRef.current = null;
    setIsReady(false);
    setMappedRegions([]);
    setError(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      dispose();
    };
  }, [dispose]);

  // ========================================================================
  // Return
  // ========================================================================

  return {
    isReady,
    isMapping,
    mappedRegions,
    error,
    initializeWithLookupTable,
    mapBboxToLWd,
    mapIndicesToPhysical,
    findIndicesInPolygon,
    dispose,
  };
}

export default useDualViewSync;
