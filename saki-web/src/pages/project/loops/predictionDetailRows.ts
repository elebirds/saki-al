import type {PredictionItemRead} from '../../../types';

export interface PredictionDetailDisplayRow {
    key: string;
    sampleId: string;
    rank: number;
    boxIndex: number;
    score: number;
    confidence: number;
    labelId?: string | null;
    classIndex: number | null;
    className: string;
    geometryType: 'rect' | 'obb' | '';
}

function asRecord(value: unknown): Record<string, any> {
    return value && typeof value === 'object' ? (value as Record<string, any>) : {};
}

function asPredictionEntries(meta: Record<string, any>): Record<string, any>[] {
    for (const key of ['base_predictions', 'predictions'] as const) {
        const value = meta[key];
        if (Array.isArray(value)) {
            return value
                .filter((item): item is Record<string, any> => Boolean(item && typeof item === 'object'))
                .map((item) => ({...item}));
        }
    }
    return [];
}

function geometryTypeOf(geometry: Record<string, any>): 'rect' | 'obb' | '' {
    if (geometry.obb && typeof geometry.obb === 'object') return 'obb';
    if (geometry.rect && typeof geometry.rect === 'object') return 'rect';
    return '';
}

export function expandPredictionDetailItems(items: PredictionItemRead[]): PredictionDetailDisplayRow[] {
    const rows: PredictionDetailDisplayRow[] = [];

    for (const item of items || []) {
        const sampleId = String(item.sampleId || '').trim();
        const rank = Number(item.rank || 0);
        const score = Number(item.score || 0);
        const fallbackGeometry = asRecord(item.geometry);
        const fallbackGeometryType = geometryTypeOf(fallbackGeometry);
        const meta = asRecord(item.meta);
        const entries = asPredictionEntries(meta);

        if (entries.length === 0) {
            rows.push({
                key: `${sampleId}-${rank}-1-fallback`,
                sampleId,
                rank,
                boxIndex: 1,
                score,
                confidence: Number(item.confidence || 0),
                labelId: item.labelId ?? null,
                classIndex: null,
                className: '',
                geometryType: fallbackGeometryType,
            });
            continue;
        }

        entries.forEach((entry, index) => {
            const geometry = asRecord(entry.geometry);
            const classIndexRaw = entry.class_index;
            const classIndex = Number.isInteger(classIndexRaw) ? Number(classIndexRaw) : (
                Number.isFinite(Number(classIndexRaw)) ? Number(classIndexRaw) : null
            );
            rows.push({
                key: `${sampleId}-${rank}-${index + 1}-${String(entry.class_name || '')}-${String(classIndex ?? 'na')}`,
                sampleId,
                rank,
                boxIndex: index + 1,
                score,
                confidence: Number(entry.confidence ?? item.confidence ?? 0),
                labelId: (entry.label_id as string | null | undefined) ?? item.labelId ?? null,
                classIndex,
                className: String(entry.class_name || '').trim(),
                geometryType: geometryTypeOf(geometry),
            });
        });
    }

    return rows;
}
