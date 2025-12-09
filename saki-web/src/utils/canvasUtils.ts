export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
  rotation?: number;
}

/**
 * Clamps a point within the given bounds (0,0 to width,height).
 * @param p The point to clamp.
 * @param bounds The boundary size.
 * @returns The clamped point.
 */
export const clampPoint = (p: Point, bounds: Size): Point => {
  return {
    x: Math.max(0, Math.min(bounds.width, p.x)),
    y: Math.max(0, Math.min(bounds.height, p.y))
  };
};

/**
 * Calculates the scale and position to fit an image within a container while maintaining aspect ratio.
 * @param containerSize The size of the container.
 * @param imageSize The size of the image.
 * @returns The new scale and position (centered).
 */
export const calculateFitScale = (containerSize: Size, imageSize: Size): { scale: number; position: Point } => {
  const scaleW = containerSize.width / imageSize.width;
  const scaleH = containerSize.height / imageSize.height;
  const scale = Math.min(scaleW, scaleH);
  
  return {
    scale,
    position: {
      x: (containerSize.width - imageSize.width * scale) / 2,
      y: (containerSize.height - imageSize.height * scale) / 2
    }
  };
};

/**
 * Calculates the new scale and position for zooming towards a specific point (mouse pointer).
 * @param currentScale The current zoom scale.
 * @param stagePosition The current stage position (pan).
 * @param pointerPosition The pointer position relative to the stage.
 * @param deltaY The scroll delta (negative for zoom in, positive for zoom out).
 * @param scaleBy The scaling factor (default 1.1).
 * @returns The new scale and position.
 */
export const calculateZoom = (
  currentScale: number,
  stagePosition: Point,
  pointerPosition: Point,
  deltaY: number,
  scaleBy: number = 1.1
): { scale: number; position: Point } => {
  const newScale = deltaY < 0 ? currentScale * scaleBy : currentScale / scaleBy;

  const mousePointTo = {
    x: (pointerPosition.x - stagePosition.x) / currentScale,
    y: (pointerPosition.y - stagePosition.y) / currentScale,
  };

  const newPos = {
    x: pointerPosition.x - mousePointTo.x * newScale,
    y: pointerPosition.y - mousePointTo.y * newScale,
  };

  return { scale: newScale, position: newPos };
};

/**
 * Normalizes a rectangle so that width and height are positive.
 * @param rect The rectangle to normalize.
 * @returns The normalized rectangle.
 */
export const normalizeRect = (rect: Rect) => {
  return {
    x: rect.w < 0 ? rect.x + rect.w : rect.x,
    y: rect.h < 0 ? rect.y + rect.h : rect.y,
    width: Math.abs(rect.w),
    height: Math.abs(rect.h),
    rotation: 0
  };
};

/**
 * Calculates the Oriented Bounding Box (OBB) during the drawing process.
 * Step 1 ('width'): Defines the baseline vector (width and rotation).
 * Step 2 ('height'): Defines the height perpendicular to the baseline.
 * 
 * @param startPos The starting point of the drawing.
 * @param currentPos The current mouse position.
 * @param step The current drawing step ('width' or 'height').
 * @param existingRect The rectangle calculated in the previous step (for 'height' step).
 * @returns The calculated rectangle or null.
 */
export const calculateObbRect = (
  startPos: Point,
  currentPos: Point,
  step: 'width' | 'height',
  existingRect: Rect | null
): Rect | null => {
  if (step === 'width') {
    const dx = currentPos.x - startPos.x;
    const dy = currentPos.y - startPos.y;
    const width = Math.sqrt(dx * dx + dy * dy);
    const rotation = Math.atan2(dy, dx) * 180 / Math.PI;
    
    return {
      x: startPos.x,
      y: startPos.y,
      w: width,
      h: 0, 
      rotation: rotation
    };
  } else if (step === 'height' && existingRect) {
    const dx = currentPos.x - startPos.x;
    const dy = currentPos.y - startPos.y;
    
    // Project vector (dx, dy) onto the perpendicular vector of the baseline
    const rad = (existingRect.rotation || 0) * Math.PI / 180;
    const perpX = -Math.sin(rad);
    const perpY = Math.cos(rad);
    
    const height = dx * perpX + dy * perpY;
    
    return {
      ...existingRect,
      h: height
    };
  }
  return null;
};

/**
 * Finalizes the OBB rectangle, ensuring height is positive by shifting the origin if necessary.
 * @param rect The raw OBB rectangle (height might be negative).
 * @returns The finalized OBB rectangle with positive dimensions.
 */
export const finalizeObbRect = (rect: Rect) => {
  let finalRect = { ...rect };
          
  if (finalRect.h < 0) {
      const rad = (finalRect.rotation || 0) * Math.PI / 180;
      const shiftX = -Math.sin(rad) * finalRect.h;
      const shiftY = Math.cos(rad) * finalRect.h;
      
      finalRect.x += shiftX;
      finalRect.y += shiftY;
      finalRect.h = Math.abs(finalRect.h);
  }
  
  return {
    x: finalRect.x,
    y: finalRect.y,
    width: finalRect.w,
    height: finalRect.h,
    rotation: finalRect.rotation
  };
};
