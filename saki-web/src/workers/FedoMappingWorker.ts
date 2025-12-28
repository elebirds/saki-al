/**
 * FEDO Mapping Worker Wrapper
 * 
 * Provides a Promise-based interface to the Web Worker for coordinate mapping.
 * Handles worker lifecycle, message routing, and binary data transfer.
 */

import { BoundingBox, MappedRegion } from '../types';

// ============================================================================
// Types
// ============================================================================

interface WorkerMessage {
  type: 'init' | 'mapBboxToPhysical' | 'mapIndicesToPhysical' | 'findIndicesInPolygon';
  id?: string;
  data?: ArrayBuffer;
  bbox?: BoundingBox;
  indices?: [number, number][];
  polygon?: [number, number][];
}

interface WorkerResponse {
  type: 'ready' | 'bboxMapped' | 'indicesMapped' | 'indicesInPolygon' | 'error';
  id?: string;
  indices?: [number, number][];
  L?: number[];
  Wd?: number[];
  regions?: MappedRegion[];
  message?: string;
}

interface BboxMappingResult {
  indices: [number, number][];
  L: number[];
  Wd: number[];
  regions: MappedRegion[];
}

interface IndicesMappingResult {
  L: number[];
  Wd: number[];
}

// ============================================================================
// Worker Wrapper Class
// ============================================================================

export class FedoMappingWorker {
  private worker: Worker;
  private pendingRequests: Map<string, {
    resolve: (value: any) => void;
    reject: (reason: any) => void;
  }>;
  private requestId: number = 0;
  private initialized: boolean = false;
  private initPromise: Promise<void> | null = null;

  constructor() {
    // Import worker using Vite's worker syntax
    this.worker = new Worker(
      new URL('./fedoMapping.worker.ts', import.meta.url),
      { type: 'module' }
    );
    this.pendingRequests = new Map();

    this.worker.onmessage = this.handleMessage.bind(this);
    this.worker.onerror = this.handleError.bind(this);
  }

  private handleMessage(e: MessageEvent<WorkerResponse>) {
    const msg = e.data;

    if (msg.type === 'ready') {
      this.initialized = true;
      return;
    }

    if (msg.type === 'error') {
      const pending = this.pendingRequests.get(msg.id!);
      if (pending) {
        pending.reject(new Error(msg.message || 'Worker error'));
        this.pendingRequests.delete(msg.id!);
      }
      return;
    }

    const pending = this.pendingRequests.get(msg.id!);
    if (pending) {
      pending.resolve(msg);
      this.pendingRequests.delete(msg.id!);
    }
  }

  private handleError(e: ErrorEvent) {
    console.error('Worker error:', e);
    // Reject all pending requests
    for (const [id, { reject }] of this.pendingRequests) {
      reject(new Error(`Worker error: ${e.message}`));
      this.pendingRequests.delete(id);
    }
  }

  private generateId(): string {
    return `req_${++this.requestId}`;
  }

  private sendRequest<T>(message: WorkerMessage): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = this.generateId();
      message.id = id;
      this.pendingRequests.set(id, { resolve, reject });
      this.worker.postMessage(message);
    });
  }

  // ============================================================================
  // Public API
  // ============================================================================

  /**
   * Initialize the worker with binary lookup table data
   * @param buffer - Binary lookup table from backend
   */
  async initialize(buffer: ArrayBuffer): Promise<void> {
    if (this.initPromise) {
      return this.initPromise;
    }

    this.initPromise = new Promise<void>((resolve, reject) => {
      const onMessage = (e: MessageEvent<WorkerResponse>) => {
        if (e.data.type === 'ready') {
          this.initialized = true;
          resolve();
        } else if (e.data.type === 'error') {
          reject(new Error(e.data.message));
        }
      };

      const originalHandler = this.worker.onmessage;
      this.worker.onmessage = (e) => {
        onMessage(e);
        if (originalHandler) {
          this.worker.onmessage = originalHandler as any;
        }
      };

      // Transfer the buffer to worker (zero-copy)
      this.worker.postMessage({ type: 'init', data: buffer }, [buffer]);
    });

    return this.initPromise;
  }

  /**
   * Check if worker is initialized
   */
  isReady(): boolean {
    return this.initialized;
  }

  /**
   * Map a bounding box from Time-Energy view to physical coordinates
   * @param bbox - Bounding box in normalized coordinates [0, 1]
   * @returns Mapped indices, L/Wd values, and L-ωd regions
   */
  async mapBboxToPhysical(bbox: BoundingBox): Promise<BboxMappingResult> {
    if (!this.initialized) {
      throw new Error('Worker not initialized. Call initialize() first.');
    }

    const response = await this.sendRequest<WorkerResponse>({
      type: 'mapBboxToPhysical',
      bbox,
    });

    return {
      indices: response.indices!,
      L: response.L!,
      Wd: response.Wd!,
      regions: response.regions!,
    };
  }

  /**
   * Map specific indices to physical coordinates
   * @param indices - Array of [i, j] index pairs
   * @returns L and Wd values for each index
   */
  async mapIndicesToPhysical(indices: [number, number][]): Promise<IndicesMappingResult> {
    if (!this.initialized) {
      throw new Error('Worker not initialized. Call initialize() first.');
    }

    const response = await this.sendRequest<WorkerResponse>({
      type: 'mapIndicesToPhysical',
      indices,
    });

    return {
      L: response.L!,
      Wd: response.Wd!,
    };
  }

  /**
   * Find all indices that fall within a polygon in L-ωd space
   * Used for reverse mapping (L-ωd selection → Time-Energy indices)
   * @param polygon - Polygon vertices in L-ωd coordinates
   * @returns Array of [i, j] indices contained in the polygon
   */
  async findIndicesInPolygon(polygon: [number, number][]): Promise<[number, number][]> {
    if (!this.initialized) {
      throw new Error('Worker not initialized. Call initialize() first.');
    }

    const response = await this.sendRequest<WorkerResponse>({
      type: 'findIndicesInPolygon',
      polygon,
    });

    return response.indices!;
  }

  /**
   * Terminate the worker
   */
  dispose(): void {
    this.worker.terminate();
    this.pendingRequests.clear();
    this.initialized = false;
    this.initPromise = null;
  }
}

// ============================================================================
// Singleton Factory
// ============================================================================

let workerInstance: FedoMappingWorker | null = null;

/**
 * Get or create the FEDO mapping worker singleton
 */
export function getFedoMappingWorker(): FedoMappingWorker {
  if (!workerInstance) {
    workerInstance = new FedoMappingWorker();
  }
  return workerInstance;
}

/**
 * Dispose the worker singleton
 */
export function disposeFedoMappingWorker(): void {
  if (workerInstance) {
    workerInstance.dispose();
    workerInstance = null;
  }
}
