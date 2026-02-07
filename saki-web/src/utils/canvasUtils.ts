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

    return {scale: newScale, position: newPos};
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
 * Normalizes an angle to be within -90° to 90° range.
 * This ensures text labels are never upside down.
 * If the angle exceeds this range, we flip it by 180° and return a flag to swap the origin.
 *
 * @param angleDeg The angle in degrees.
 * @returns The normalized angle and whether to flip the direction.
 */
export const normalizeObbAngle = (angleDeg: number): { angle: number; shouldFlip: boolean } => {
    // Normalize to -180 to 180 range first
    let angle = angleDeg;
    while (angle > 180) angle -= 360;
    while (angle < -180) angle += 360;

    // If angle is between -180 and -90, or between 90 and 180, flip it
    if (angle > 90) {
        return {angle: angle - 180, shouldFlip: true};
    } else if (angle < -90) {
        return {angle: angle + 180, shouldFlip: true};
    }

    return {angle, shouldFlip: false};
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
        const rawRotation = Math.atan2(dy, dx) * 180 / Math.PI;

        // Normalize angle to -90° to 90° range to prevent upside-down text
        const {angle: rotation, shouldFlip} = normalizeObbAngle(rawRotation);

        // If we need to flip, swap the start and end points
        let originX = startPos.x;
        let originY = startPos.y;
        if (shouldFlip) {
            originX = currentPos.x;
            originY = currentPos.y;
        }

        return {
            x: originX,
            y: originY,
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
 * Converts OBB coordinates from origin point (top-left corner) to center point.
 * This is needed because the backend expects center point coordinates.
 *
 * @param bbox Bounding box with origin point (x, y) and dimensions (width, height, rotation)
 * @returns Bounding box with center point coordinates
 */
export const originToCenter = (bbox: { x: number; y: number; width: number; height: number; rotation?: number }) => {
    const rotation = bbox.rotation || 0;
    const rad = rotation * Math.PI / 180;

    // Calculate the offset vector from origin to center in local (unrotated) coordinates
    // The origin is at the corner, so offset is (width/2, height/2) in local space
    const localOffsetX = bbox.width / 2;
    const localOffsetY = bbox.height / 2;

    // Rotate the offset vector to world coordinates
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    const worldOffsetX = localOffsetX * cos - localOffsetY * sin;
    const worldOffsetY = localOffsetX * sin + localOffsetY * cos;

    // Center point = origin point + rotated offset
    return {
        x: bbox.x + worldOffsetX,
        y: bbox.y + worldOffsetY,
        width: bbox.width,
        height: bbox.height,
        rotation: rotation
    };
};

/**
 * Converts OBB coordinates from center point to origin point (top-left corner).
 * This is needed when displaying backend data which uses center point coordinates.
 *
 * @param bbox Bounding box with center point (x, y) and dimensions (width, height, rotation)
 * @returns Bounding box with origin point coordinates
 */
export const centerToOrigin = (bbox: { x: number; y: number; width: number; height: number; rotation?: number }) => {
    const rotation = bbox.rotation || 0;
    const rad = rotation * Math.PI / 180;

    // Calculate the offset vector from center to origin in local (unrotated) coordinates
    // The origin is at the corner, so offset is -(width/2, height/2) in local space
    const localOffsetX = -bbox.width / 2;
    const localOffsetY = -bbox.height / 2;

    // Rotate the offset vector to world coordinates
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    const worldOffsetX = localOffsetX * cos - localOffsetY * sin;
    const worldOffsetY = localOffsetX * sin + localOffsetY * cos;

    // Origin point = center point + rotated offset
    return {
        x: bbox.x + worldOffsetX,
        y: bbox.y + worldOffsetY,
        width: bbox.width,
        height: bbox.height,
        rotation: rotation
    };
};

/**
 * Finalizes the OBB rectangle, ensuring:
 * 1. Height is positive by shifting the origin if necessary
 * 2. The "width" edge is always more horizontal (|rotation| <= 45°), so text labels appear on the top edge
 *
 * @param rect The raw OBB rectangle (height might be negative).
 * @returns The finalized OBB rectangle with positive dimensions and normalized rotation.
 */
export const finalizeObbRect = (rect: Rect) => {
    let finalRect = {...rect};

    // Step 1: Ensure height is positive
    if (finalRect.h < 0) {
        const rad = (finalRect.rotation || 0) * Math.PI / 180;
        const shiftX = -Math.sin(rad) * finalRect.h;
        const shiftY = Math.cos(rad) * finalRect.h;

        finalRect.x += shiftX;
        finalRect.y += shiftY;
        finalRect.h = Math.abs(finalRect.h);
    }

    // Step 2: Ensure the "width" edge is more horizontal (|rotation| <= 45°)
    // If |rotation| > 45°, swap width and height, and adjust rotation by ±90°
    let rotation = finalRect.rotation || 0;
    let width = finalRect.w;
    let height = finalRect.h;
    let x = finalRect.x;
    let y = finalRect.y;

    if (Math.abs(rotation) > 45) {
        // Swap width and height
        const temp = width;
        width = height;
        height = temp;

        // Adjust rotation: if rotation > 45°, subtract 90°; if < -45°, add 90°
        if (rotation > 45) {
            rotation -= 90;
        } else {
            rotation += 90;
        }

        // Recalculate origin point after rotation change
        // The new origin should be at the corner that keeps the box in the same position
        const oldRad = (finalRect.rotation || 0) * Math.PI / 180;

        // Move origin to the corner that will become the new top-left after swapping
        // When we rotate by -90° (or +90°), we need to shift the origin
        if (finalRect.rotation! > 45) {
            // Original rotation > 45°, we subtract 90°
            // New origin is at the old origin shifted by the height vector (perpendicular to old width)
            x = finalRect.x - Math.sin(oldRad) * finalRect.h;
            y = finalRect.y + Math.cos(oldRad) * finalRect.h;
        } else {
            // Original rotation < -45°, we add 90°
            // New origin is at the old origin shifted by the width vector
            x = finalRect.x + Math.cos(oldRad) * finalRect.w;
            y = finalRect.y + Math.sin(oldRad) * finalRect.w;
        }
    }

    return {
        x,
        y,
        width,
        height,
        rotation
    };
};
