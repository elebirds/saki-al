import {
    Annotation,
    ANNOTATION_TYPE_OBB,
    ANNOTATION_TYPE_RECT,
    AnnotationType,
    DualViewAnnotation,
    isDetectionAnnotationType,
} from '../types';

type SidebarAnnotation = Partial<Annotation> & Partial<DualViewAnnotation> & Record<string, any>;

type SpatialAnchor = {
    x: number;
    y: number;
};

function toFiniteNumber(value: unknown): number | null {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function resolveRectAnchorFromGeometry(annotation: SidebarAnnotation): SpatialAnchor | null {
    const rect = annotation.geometry?.rect;
    if (rect) {
        const x = toFiniteNumber(rect.x);
        const y = toFiniteNumber(rect.y);
        if (x !== null && y !== null) {
            return {x, y};
        }
    }

    const obb = annotation.geometry?.obb;
    if (obb) {
        const cx = toFiniteNumber(obb.cx);
        const cy = toFiniteNumber(obb.cy);
        const w = toFiniteNumber(obb.width);
        const h = toFiniteNumber(obb.height);
        if (cx !== null && cy !== null && w !== null && h !== null) {
            return {x: cx - w / 2, y: cy - h / 2};
        }
    }

    return null;
}

function resolveRectAnchorFromPrimary(annotation: SidebarAnnotation): SpatialAnchor | null {
    const bbox = annotation.primary?.bbox;
    if (!bbox) return null;
    const x = toFiniteNumber(bbox.x);
    const y = toFiniteNumber(bbox.y);
    if (x !== null && y !== null) {
        return {x, y};
    }
    return null;
}

function formatNumber(value: unknown): string {
    const num = Number(value);
    if (!Number.isFinite(num)) return '-';
    if (Math.abs(num) >= 1000) return num.toFixed(0);
    if (Math.abs(num) >= 100) return num.toFixed(1);
    return num.toFixed(2);
}

export function resolveSidebarAnnotationType(annotation: SidebarAnnotation): AnnotationType | undefined {
    if (isDetectionAnnotationType(annotation.type)) {
        return annotation.type;
    }
    if (annotation.geometry?.rect) return ANNOTATION_TYPE_RECT;
    if (annotation.geometry?.obb) return ANNOTATION_TYPE_OBB;
    if (isDetectionAnnotationType(annotation.primary?.type)) {
        return annotation.primary.type;
    }
    return undefined;
}

export function resolveSidebarAnnotationView(annotation: SidebarAnnotation): string | undefined {
    return annotation.attrs?.view;
}

export function formatSidebarGeometrySummary(annotation: SidebarAnnotation): string {
    if (annotation.geometry?.rect) {
        const {x, y, width, height} = annotation.geometry.rect;
        return `(${formatNumber(x)}, ${formatNumber(y)}) ${formatNumber(width)}×${formatNumber(height)}`;
    }

    if (annotation.geometry?.obb) {
        const obb = annotation.geometry.obb;
        const angle = obb.angle_deg_ccw ?? obb.angleDegCcw ?? 0;
        return `(${formatNumber(obb.cx)}, ${formatNumber(obb.cy)}) ${formatNumber(obb.width)}×${formatNumber(
            obb.height
        )} θ${formatNumber(angle)}°`;
    }

    if (annotation.primary?.bbox) {
        const bbox = annotation.primary.bbox;
        const type = annotation.primary.type || annotation.type;
        if (type === ANNOTATION_TYPE_OBB) {
            const cx = Number(bbox.x || 0) + Number(bbox.width || 0) / 2;
            const cy = Number(bbox.y || 0) + Number(bbox.height || 0) / 2;
            return `(${formatNumber(cx)}, ${formatNumber(cy)}) ${formatNumber(bbox.width)}×${formatNumber(
                bbox.height
            )} θ${formatNumber(bbox.rotation || 0)}°`;
        }
        return `(${formatNumber(bbox.x)}, ${formatNumber(bbox.y)}) ${formatNumber(bbox.width)}×${formatNumber(
            bbox.height
        )}`;
    }

    return '';
}

export function sortAnnotationsForSidebar<T extends SidebarAnnotation>(annotations: T[]): T[] {
    return [...annotations].sort((a, b) => {
        const posA = resolveRectAnchorFromGeometry(a) || resolveRectAnchorFromPrimary(a);
        const posB = resolveRectAnchorFromGeometry(b) || resolveRectAnchorFromPrimary(b);

        if (posA && posB) {
            const dy = posA.y - posB.y;
            if (Math.abs(dy) > 1e-3) return dy;
            const dx = posA.x - posB.x;
            if (Math.abs(dx) > 1e-3) return dx;
        } else if (posA && !posB) {
            return -1;
        } else if (!posA && posB) {
            return 1;
        }

        const labelA = String(a.labelName || a.labelId || '');
        const labelB = String(b.labelName || b.labelId || '');
        const labelOrder = labelA.localeCompare(labelB);
        if (labelOrder !== 0) return labelOrder;

        const typeOrder = String(resolveSidebarAnnotationType(a) || '').localeCompare(
            String(resolveSidebarAnnotationType(b) || '')
        );
        if (typeOrder !== 0) return typeOrder;

        return String(a.id || '').localeCompare(String(b.id || ''));
    });
}
