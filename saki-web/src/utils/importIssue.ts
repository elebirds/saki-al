import type {TFunction} from 'i18next';
import type {ImportIssue} from '../types';

export interface ImportIssueMessageView {
    message: string;
    rawMessage?: string;
}

function parseDetail(issue: ImportIssue): Record<string, unknown> {
    if (!issue.detail || typeof issue.detail !== 'object') return {};
    return issue.detail as Record<string, unknown>;
}

function toNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function toStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value.map((item) => String(item)).filter(Boolean);
}

export function localizeImportIssueMessage(t: TFunction, issue: ImportIssue): ImportIssueMessageView {
    const detail = parseDetail(issue);
    const rawMessage = String(issue.message || '').trim();
    const code = String(issue.code || '').trim();
    const key = `import.workspace.issueCode.${code}`;

    const translated = t(key, {
        defaultValue: '',
        code,
        path: issue.path || '',
        message: rawMessage,
        annotationType: String(detail.annotation_type || ''),
        count: toNumber(detail.count),
        enabledTypes: toStringArray(detail.enabled_types).join(', '),
        label: String(detail.label || ''),
    }).trim();

    if (translated) {
        const normalizedRaw = rawMessage && rawMessage !== translated ? rawMessage : undefined;
        return {
            message: translated,
            rawMessage: normalizedRaw,
        };
    }

    if (rawMessage) {
        return {message: rawMessage};
    }
    return {message: code || t('import.workspace.issueCode.UNKNOWN')};
}
