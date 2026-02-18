import {centerToOrigin, originToCenter} from './canvasUtils';
import {AnnotationDraftItem, AnnotationDraftPayload, AnnotationGeometry, AnnotationRead, AnnotationType} from '../types';

export interface CanvasBBoxData {
    x: number;
    y: number;
    width: number;
    height: number;
    rotation?: number;
}

function toNumber(value: unknown, fallback = 0): number {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
}

function normalizeBBoxData(data?: Record<string, any>): CanvasBBoxData {
    const raw = data || {};
    const bbox: CanvasBBoxData = {
        x: toNumber(raw.x, 0),
        y: toNumber(raw.y, 0),
        width: toNumber(raw.width, 0),
        height: toNumber(raw.height, 0),
    };
    if (raw.rotation !== undefined && raw.rotation !== null) {
        bbox.rotation = toNumber(raw.rotation, 0);
    }
    return bbox;
}

function getObbAngleDegCcw(obb: Record<string, any> | undefined): number {
    if (!obb) return 0;
    if (obb.angleDegCcw !== undefined && obb.angleDegCcw !== null) {
        return toNumber(obb.angleDegCcw, 0);
    }
    if (obb.angle_deg_ccw !== undefined && obb.angle_deg_ccw !== null) {
        return toNumber(obb.angle_deg_ccw, 0);
    }
    return 0;
}

export function geometryToCanvasData(
    type: AnnotationType,
    geometry?: AnnotationGeometry
): CanvasBBoxData {
    if (geometry?.rect) {
        return {
            x: toNumber(geometry.rect.x, 0),
            y: toNumber(geometry.rect.y, 0),
            width: toNumber(geometry.rect.width, 0),
            height: toNumber(geometry.rect.height, 0),
        };
    }

    if (geometry?.obb) {
        const origin = centerToOrigin({
            x: toNumber(geometry.obb.cx, 0),
            y: toNumber(geometry.obb.cy, 0),
            width: toNumber(geometry.obb.width, 0),
            height: toNumber(geometry.obb.height, 0),
            rotation: getObbAngleDegCcw(geometry.obb as Record<string, any>),
        });
        return {
            x: origin.x,
            y: origin.y,
            width: origin.width,
            height: origin.height,
            rotation: origin.rotation,
        };
    }

    const empty: CanvasBBoxData = {
        x: 0,
        y: 0,
        width: 0,
        height: 0,
    };
    if (type === 'obb') {
        empty.rotation = 0;
    }
    return empty;
}

export function canvasDataToGeometry(type: AnnotationType, data?: Record<string, any>): AnnotationGeometry {
    const bbox = normalizeBBoxData(data);

    if (type === 'obb') {
        const center = originToCenter({
            x: bbox.x,
            y: bbox.y,
            width: bbox.width,
            height: bbox.height,
            rotation: toNumber(bbox.rotation, 0),
        });
        return {
            obb: {
                cx: center.x,
                cy: center.y,
                width: center.width,
                height: center.height,
                angle_deg_ccw: toNumber(center.rotation, 0),
            },
        };
    }

    return {
        rect: {
            x: bbox.x,
            y: bbox.y,
            width: bbox.width,
            height: bbox.height,
        },
    };
}

export function resolveAnnotationView(annotation: { attrs?: Record<string, any> }): string | undefined {
    return annotation.attrs?.view;
}

export function hydrateDraftItem<T extends AnnotationDraftItem>(item: T): T {
    return {
        ...item,
        attrs: item.attrs ?? {},
    };
}

export function hydrateDraftPayload(payload: AnnotationDraftPayload | null): AnnotationDraftPayload | null {
    if (!payload) return null;
    return {
        ...payload,
        annotations: (payload.annotations || []).map((item) => hydrateDraftItem(item)),
        meta: payload.meta || {},
    };
}

export function hydrateAnnotationRead(item: AnnotationRead): AnnotationRead {
    return {
        ...item,
        attrs: item.attrs ?? {},
    };
}

export function attrsFromAnnotationLike(annotation: {
    attrs?: Record<string, any>;
}): Record<string, any> {
    return annotation.attrs ?? {};
}
