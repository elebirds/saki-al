const CONFIDENCE_VISIBLE_SOURCES = new Set([
    'model',
    'confirmed_model',
    'auto',
    'system',
    'fedo_mapping',
]);

export function isConfidenceVisibleSource(source: unknown): boolean {
    if (source === null || source === undefined) return false;
    const normalized = String(source).trim().toLowerCase();
    return CONFIDENCE_VISIBLE_SOURCES.has(normalized);
}

export function normalizeConfidence(value: unknown): number | null {
    const num = Number(value);
    if (!Number.isFinite(num)) return null;
    if (num < 0 || num > 1) return null;
    return num;
}

export function formatConfidence(value: unknown): string | null {
    const normalized = normalizeConfidence(value);
    if (normalized === null) return null;
    return normalized.toFixed(2);
}
