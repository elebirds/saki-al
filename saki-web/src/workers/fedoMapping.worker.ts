/**
 * FEDO Coordinate Mapping Worker
 * 
 * Handles efficient coordinate transformations between:
 * - Screen pixels ↔ Normalized drawing area
 * - Normalized coordinates ↔ Data indices (i, j)
 * - Data indices ↔ Physical coordinates (L, ωd)
 * 
 * Uses Float32Array for vectorized operations to achieve <100ms
 * performance on 2700×140 data matrices.
 */

// ============================================================================
// Types
// ============================================================================

interface LookupData {
  nTime: number;
  nEnergy: number;
  L: Float32Array;
  Wd: Float32Array;  // Flattened N×M matrix
  LMin: number;
  LMax: number;
  WdMin: number;
  WdMax: number;
}

interface BoundingBox {
  x: number;      // Normalized [0, 1]
  y: number;
  width: number;
  height: number;
  rotation?: number;  // Degrees
}

interface MappedRegion {
  timeRange: [number, number];
  polygonPoints: [number, number][];
  isPrimary: boolean;
}

type WorkerMessage = 
  | { type: 'init'; data: ArrayBuffer }
  | { type: 'mapBboxToPhysical'; bbox: BoundingBox; id: string }
  | { type: 'mapIndicesToPhysical'; indices: [number, number][]; id: string }
  | { type: 'findIndicesInPolygon'; polygon: [number, number][]; id: string };

type WorkerResponse =
  | { type: 'ready' }
  | { type: 'bboxMapped'; id: string; indices: [number, number][]; L: number[]; Wd: number[]; regions: MappedRegion[] }
  | { type: 'indicesMapped'; id: string; L: number[]; Wd: number[] }
  | { type: 'indicesInPolygon'; id: string; indices: [number, number][] }
  | { type: 'error'; id: string; message: string };

// ============================================================================
// Lookup Table State
// ============================================================================

let lookup: LookupData | null = null;

// ============================================================================
// Binary Data Parsing
// ============================================================================

function parseLookupBinary(buffer: ArrayBuffer): LookupData {
  const view = new DataView(buffer);
  let offset = 0;

  // Read header: nTime (4B), nEnergy (4B), LMin-LMax-WdMin-WdMax (4×8B = 32B)
  const nTime = view.getUint32(offset, true);
  offset += 4;
  const nEnergy = view.getUint32(offset, true);
  offset += 4;
  const LMin = view.getFloat64(offset, true);
  offset += 8;
  const LMax = view.getFloat64(offset, true);
  offset += 8;
  const WdMin = view.getFloat64(offset, true);
  offset += 8;
  const WdMax = view.getFloat64(offset, true);
  offset += 8;

  // Read L array: float32 (N × 4B)
  const L = new Float32Array(buffer, offset, nTime);
  offset += nTime * 4;

  // Read Wd matrix: float32 (N × M × 4B)
  const Wd = new Float32Array(buffer, offset, nTime * nEnergy);
  offset += nTime * nEnergy * 4;

  // E array is also in the binary but we don't need it for mapping

  return { nTime, nEnergy, L, Wd, LMin, LMax, WdMin, WdMax };
}

// ============================================================================
// Coordinate Transformation Functions
// ============================================================================

/**
 * Convert normalized bbox [0,1] to index ranges
 */
function bboxToIndexRange(bbox: BoundingBox, nTime: number, nEnergy: number): {
  iMin: number; iMax: number; jMin: number; jMax: number;
} {
  // For now, handle axis-aligned case
  // TODO: Handle rotation with OBB
  let { x, y, width, height } = bbox;

  // Clamp to [0, 1]
  const xMin = Math.max(0, Math.min(1, x));
  const xMax = Math.max(0, Math.min(1, x + width));
  const yMin = Math.max(0, Math.min(1, y));
  const yMax = Math.max(0, Math.min(1, y + height));

  // Convert to indices
  const iMin = Math.max(0, Math.min(nTime - 1, Math.floor(xMin * nTime)));
  const iMax = Math.max(0, Math.min(nTime - 1, Math.floor(xMax * nTime)));
  const jMin = Math.max(0, Math.min(nEnergy - 1, Math.floor(yMin * nEnergy)));
  const jMax = Math.max(0, Math.min(nEnergy - 1, Math.floor(yMax * nEnergy)));

  return { iMin, iMax, jMin, jMax };
}

/**
 * Check if a point is inside a rotated rectangle (OBB)
 * Note: This function expects bbox.x and bbox.y to be the origin point (corner),
 * not the center point. The frontend uses origin point coordinates internally.
 */
function isPointInOBB(
  px: number, py: number,  // Point in normalized coords
  bbox: BoundingBox
): boolean {
  const rotation = (bbox.rotation || 0) * Math.PI / 180;
  // Calculate center point from origin point (bbox.x, bbox.y is the origin/corner)
  const cx = bbox.x + bbox.width / 2;
  const cy = bbox.y + bbox.height / 2;

  // Translate point to origin
  const dx = px - cx;
  const dy = py - cy;

  // Rotate point back
  const cos = Math.cos(-rotation);
  const sin = Math.sin(-rotation);
  const rx = dx * cos - dy * sin;
  const ry = dx * sin + dy * cos;

  // Check if inside axis-aligned rect centered at origin
  return Math.abs(rx) <= bbox.width / 2 && Math.abs(ry) <= bbox.height / 2;
}

/**
 * Get all indices within a bounding box (handles OBB rotation)
 */
function getIndicesInBbox(bbox: BoundingBox, nTime: number, nEnergy: number): [number, number][] {
  const { iMin, iMax, jMin, jMax } = bboxToIndexRange(bbox, nTime, nEnergy);
  const indices: [number, number][] = [];
  const hasRotation = bbox.rotation && Math.abs(bbox.rotation) > 0.1;

  for (let i = iMin; i <= iMax; i++) {
    for (let j = jMin; j <= jMax; j++) {
      if (hasRotation) {
        // Convert index to normalized coords and check OBB
        const nx = (i + 0.5) / nTime;
        const ny = (j + 0.5) / nEnergy;
        if (isPointInOBB(nx, ny, bbox)) {
          indices.push([i, j]);
        }
      } else {
        indices.push([i, j]);
      }
    }
  }

  return indices;
}

/**
 * Map indices to physical coordinates using lookup table
 */
function mapIndicesToPhysical(
  indices: [number, number][],
  lookup: LookupData
): { L: number[]; Wd: number[] } {
  const L: number[] = new Array(indices.length);
  const Wd: number[] = new Array(indices.length);

  for (let k = 0; k < indices.length; k++) {
    const [i, j] = indices[k];
    // Clamp indices
    const ci = Math.max(0, Math.min(lookup.nTime - 1, i));
    const cj = Math.max(0, Math.min(lookup.nEnergy - 1, j));
    
    L[k] = lookup.L[ci];
    Wd[k] = lookup.Wd[ci * lookup.nEnergy + cj];
  }

  return { L, Wd };
}

/**
 * Detect inflection point in L values (for non-monotonic handling)
 */
function findInflectionPoints(L: Float32Array, timeIndices: number[]): number[] {
  if (timeIndices.length < 3) return [];

  const inflections: number[] = [];
  let prevDiff = L[timeIndices[1]] - L[timeIndices[0]];

  for (let k = 2; k < timeIndices.length; k++) {
    const currDiff = L[timeIndices[k]] - L[timeIndices[k - 1]];
    if (prevDiff * currDiff < 0) {
      // Sign change - inflection point
      inflections.push(timeIndices[k - 1]);
    }
    prevDiff = currDiff;
  }

  return inflections;
}

/**
 * Compute convex hull polygon from points
 * Uses Graham scan algorithm
 */
function computeConvexHull(points: [number, number][]): [number, number][] {
  if (points.length < 3) return points;

  // Find lowest point
  let lowest = 0;
  for (let i = 1; i < points.length; i++) {
    if (points[i][1] < points[lowest][1] ||
        (points[i][1] === points[lowest][1] && points[i][0] < points[lowest][0])) {
      lowest = i;
    }
  }

  // Swap lowest to front
  [points[0], points[lowest]] = [points[lowest], points[0]];
  const pivot = points[0];

  // Sort by polar angle
  const sorted = points.slice(1).sort((a, b) => {
    const angleA = Math.atan2(a[1] - pivot[1], a[0] - pivot[0]);
    const angleB = Math.atan2(b[1] - pivot[1], b[0] - pivot[0]);
    return angleA - angleB;
  });

  // Graham scan
  const hull: [number, number][] = [pivot];
  for (const p of sorted) {
    while (hull.length > 1) {
      const top = hull[hull.length - 1];
      const second = hull[hull.length - 2];
      const cross = (top[0] - second[0]) * (p[1] - second[1]) -
                    (top[1] - second[1]) * (p[0] - second[0]);
      if (cross <= 0) {
        hull.pop();
      } else {
        break;
      }
    }
    hull.push(p);
  }

  // Close the polygon
  hull.push(hull[0]);
  return hull;
}

/**
 * Split indices into regions and compute L-ωd polygons
 */
function splitIntoRegions(
  indices: [number, number][],
  L: number[],
  Wd: number[],
  lookup: LookupData
): MappedRegion[] {
  if (indices.length === 0) return [];

  // Get unique time indices
  const timeSet = new Set<number>();
  for (const [i] of indices) timeSet.add(i);
  const timeIndices = Array.from(timeSet).sort((a, b) => a - b);

  // Find inflection points
  const inflections = findInflectionPoints(lookup.L, timeIndices);

  if (inflections.length === 0) {
    // Single region (monotonic)
    const points: [number, number][] = [];
    for (let k = 0; k < indices.length; k++) {
      points.push([L[k], Wd[k]]);
    }
    const polygon = computeConvexHull(points);

    return [{
      timeRange: [timeIndices[0], timeIndices[timeIndices.length - 1]],
      polygonPoints: polygon,
      isPrimary: true,
    }];
  }

  // Multiple regions (non-monotonic)
  const regions: MappedRegion[] = [];
  const splitPoints = [timeIndices[0], ...inflections, timeIndices[timeIndices.length - 1] + 1];

  for (let r = 0; r < splitPoints.length - 1; r++) {
    const regionStart = splitPoints[r];
    const regionEnd = splitPoints[r + 1];

    const regionPoints: [number, number][] = [];
    const regionTimeRange: [number, number] = [regionStart, regionEnd - 1];

    for (let k = 0; k < indices.length; k++) {
      const [i] = indices[k];
      if (i >= regionStart && i < regionEnd) {
        regionPoints.push([L[k], Wd[k]]);
      }
    }

    if (regionPoints.length > 0) {
      const polygon = computeConvexHull(regionPoints);
      regions.push({
        timeRange: regionTimeRange,
        polygonPoints: polygon,
        isPrimary: r === 0,
      });
    }
  }

  return regions;
}

// ============================================================================
// Message Handler
// ============================================================================

self.onmessage = function(e: MessageEvent<WorkerMessage>) {
  const msg = e.data;

  try {
    switch (msg.type) {
      case 'init': {
        lookup = parseLookupBinary(msg.data);
        self.postMessage({ type: 'ready' } as WorkerResponse);
        break;
      }

      case 'mapBboxToPhysical': {
        if (!lookup) {
          throw new Error('Lookup table not initialized');
        }

        const indices = getIndicesInBbox(msg.bbox, lookup.nTime, lookup.nEnergy);
        const { L, Wd } = mapIndicesToPhysical(indices, lookup);
        const regions = splitIntoRegions(indices, L, Wd, lookup);

        self.postMessage({
          type: 'bboxMapped',
          id: msg.id,
          indices,
          L,
          Wd,
          regions,
        } as WorkerResponse);
        break;
      }

      case 'mapIndicesToPhysical': {
        if (!lookup) {
          throw new Error('Lookup table not initialized');
        }

        const { L, Wd } = mapIndicesToPhysical(msg.indices, lookup);
        
        self.postMessage({
          type: 'indicesMapped',
          id: msg.id,
          L,
          Wd,
        } as WorkerResponse);
        break;
      }

      case 'findIndicesInPolygon': {
        if (!lookup) {
          throw new Error('Lookup table not initialized');
        }

        // For reverse mapping: given L-ωd polygon, find all indices
        // This is the "one box becomes two regions" scenario
        const polygon = msg.polygon;
        const indices: [number, number][] = [];

        // Check each cell in the matrix
        for (let i = 0; i < lookup.nTime; i++) {
          for (let j = 0; j < lookup.nEnergy; j++) {
            const l = lookup.L[i];
            const wd = lookup.Wd[i * lookup.nEnergy + j];
            
            if (isPointInPolygon(l, wd, polygon)) {
              indices.push([i, j]);
            }
          }
        }

        self.postMessage({
          type: 'indicesInPolygon',
          id: msg.id,
          indices,
        } as WorkerResponse);
        break;
      }
    }
  } catch (error) {
    self.postMessage({
      type: 'error',
      id: (msg as any).id || 'unknown',
      message: error instanceof Error ? error.message : 'Unknown error',
    } as WorkerResponse);
  }
};

/**
 * Check if point is inside polygon (ray casting algorithm)
 */
function isPointInPolygon(x: number, y: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    
    if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

export {};
