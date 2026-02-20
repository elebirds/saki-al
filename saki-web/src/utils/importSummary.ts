import type {TFunction} from 'i18next';

const IMPORT_SUMMARY_KEY_ORDER = [
    'mode',
    'format_profile',
    'format',
    'branch_name',
    'target_dataset_mode',
    'dataset_id',
    'allow_duplicate_sample_names',
    'project_id',
    'image_candidates',
    'total_entries',
    'new_samples',
    'reused_samples',
    'skipped_non_image',
    'matched_samples',
    'matched_sample_keys',
    'total_annotations',
    'matched_annotations',
    'skipped_annotations',
    'unsupported_annotations',
    'unsupported_types',
] as const;

const IMPORT_SUMMARY_KEY_PRIORITY = new Map<string, number>(
    IMPORT_SUMMARY_KEY_ORDER.map((key, index) => [key, index]),
);

export function normalizeImportSummaryKey(rawKey: string): string {
    const key = rawKey.trim();
    if (!key) return rawKey;
    return key
        .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
        .replace(/([A-Z]+)([A-Z][a-z0-9]+)/g, '$1_$2')
        .replace(/[\s-]+/g, '_')
        .toLowerCase();
}

export function getOrderedImportSummaryEntries(
    summary?: Record<string, unknown> | null,
): Array<[string, unknown]> {
    return Object.entries(summary || {}).sort(([leftKey], [rightKey]) => {
        const leftNormalized = normalizeImportSummaryKey(leftKey);
        const rightNormalized = normalizeImportSummaryKey(rightKey);
        const leftPriority = IMPORT_SUMMARY_KEY_PRIORITY.get(leftNormalized) ?? Number.MAX_SAFE_INTEGER;
        const rightPriority = IMPORT_SUMMARY_KEY_PRIORITY.get(rightNormalized) ?? Number.MAX_SAFE_INTEGER;
        if (leftPriority !== rightPriority) {
            return leftPriority - rightPriority;
        }
        const normalizedCompare = leftNormalized.localeCompare(rightNormalized);
        if (normalizedCompare !== 0) return normalizedCompare;
        return leftKey.localeCompare(rightKey);
    });
}

export function localizeImportSummaryKey(t: TFunction, key: string): string {
    const normalizedKey = normalizeImportSummaryKey(key);
    const translated = t(`import.workspace.summaryKey.${normalizedKey}`, {defaultValue: ''}).trim();
    return translated || key;
}

export function formatImportSummaryValue(t: TFunction, key: string, value: unknown): string {
    const normalizedKey = normalizeImportSummaryKey(key);
    if (value === null || value === undefined) return '-';

    if (Array.isArray(value)) {
        if (value.length === 0) return '-';
        return value.map((item) => String(item)).join(', ');
    }

    if (typeof value === 'boolean') {
        return value ? t('common.yes') : t('common.no');
    }

    if (typeof value === 'number') {
        return Number.isFinite(value) ? String(value) : '-';
    }

    if (typeof value === 'string') {
        const text = value.trim();
        if (!text) return '-';

        if (normalizedKey === 'mode') {
            const modeText = t(`import.workspace.summaryValue.mode.${text}`, {defaultValue: ''}).trim();
            return modeText || text;
        }
        if (normalizedKey === 'target_dataset_mode') {
            const modeText = t(`import.workspace.summaryValue.targetDatasetMode.${text}`, {defaultValue: ''}).trim();
            return modeText || text;
        }
        if (normalizedKey === 'format' || normalizedKey === 'format_profile') {
            const formatText = t(`import.workspace.summaryValue.format.${text}`, {defaultValue: ''}).trim();
            return formatText || text.toUpperCase();
        }

        return text;
    }

    if (typeof value === 'object') {
        try {
            return JSON.stringify(value);
        } catch {
            return String(value);
        }
    }

    return String(value);
}
