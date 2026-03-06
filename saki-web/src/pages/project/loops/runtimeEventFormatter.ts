import {RuntimeRoundEvent, RuntimeTaskEvent} from '../../../types';

export type RuntimeMessageTranslator = (key: string, params?: Record<string, any>) => string;

type RuntimeEventLike = RuntimeTaskEvent | RuntimeRoundEvent;

const SYSTEM_TAG_PREFIXES = ['event:', 'level:', 'status:', 'kind:'];
const ROUND_STAGES = new Set(['train', 'eval', 'score', 'select', 'custom']);
const TASK_TYPES = new Set(['train', 'eval', 'score', 'select', 'predict', 'custom']);

const ANSI_CSI_RE = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const ANSI_OSC_RE = /\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
const ANSI_SINGLE_RE = /\x1b[@-Z\\-_]/g;
const CONTROL_RE = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;

function asRecord(value: unknown): Record<string, any> {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, any>)
        : {};
}

function camelToSnake(text: string): string {
    return text.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

function snakeToCamel(text: string): string {
    return text.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

function normalizeLevel(value: unknown): string | null {
    const text = String(value ?? '').trim().toUpperCase();
    if (!text) return null;
    if (text === 'WARN') return 'WARNING';
    if (text === 'FATAL') return 'CRITICAL';
    return text;
}

function normalizeTagList(rawTags: unknown): string[] {
    if (!Array.isArray(rawTags)) return [];
    const tags: string[] = [];
    rawTags.forEach((item) => {
        const text = String(item ?? '').trim();
        if (!text) return;
        const lowered = text.toLowerCase();
        if (SYSTEM_TAG_PREFIXES.some((prefix) => lowered.startsWith(prefix))) return;
        if (!tags.includes(text)) tags.push(text);
    });
    return tags;
}

function normalizeMessageParams(rawParams: unknown): Record<string, any> {
    return asRecord(rawParams);
}

function expandMessageParams(params: Record<string, any>): Record<string, any> {
    const merged: Record<string, any> = {};
    Object.entries(asRecord(params)).forEach(([rawKey, value]) => {
        const key = String(rawKey || '').trim();
        if (!key) return;
        merged[key] = value;
        const snakeKey = camelToSnake(key);
        const camelKey = snakeToCamel(key);
        merged[snakeKey] = value;
        merged[camelKey] = value;
    });
    return merged;
}

function deriveStageFromTaskType(taskType: string): RuntimeRoundEvent['stage'] {
    const normalized = String(taskType || '').trim().toLowerCase();
    if (normalized === 'train') return 'train';
    if (normalized === 'eval') return 'eval';
    if (normalized === 'score') return 'score';
    if (normalized === 'select') return 'select';
    return 'custom';
}

function deriveFallbackMessage(eventType: string, payload: Record<string, any>, rawMessage: string): string {
    if (eventType === 'log') {
        const message = stripAnsiAndControl(String(payload.message ?? rawMessage ?? '')).replace(/\s+$/, '');
        return message;
    }
    if (eventType === 'status') {
        const status = String(payload.status ?? '').trim().toLowerCase();
        const reason = String(payload.reason ?? '').trim();
        if (status && reason) return `${status}: ${reason}`;
        return status || reason;
    }
    if (eventType === 'progress') {
        const epoch = Number(payload.epoch ?? 0);
        const step = Number(payload.step ?? 0);
        const totalSteps = Number(payload.total_steps ?? payload.totalSteps ?? 0);
        return `epoch ${epoch}, step ${step}/${totalSteps}`;
    }
    if (eventType === 'metric') {
        const metrics = asRecord(payload.metrics);
        const keys = Object.keys(metrics).filter((item) => String(item).trim());
        if (keys.length > 0) {
            const preview = keys.slice(0, 4).join(', ');
            return keys.length > 4 ? `metrics updated (${preview}...)` : `metrics updated (${preview})`;
        }
        return 'metrics updated';
    }
    if (eventType === 'artifact') {
        const name = String(payload.name ?? '').trim();
        const uri = String(payload.uri ?? '').trim();
        if (name && uri) return `${name} (${uri})`;
        return name || uri;
    }
    return '';
}

function translateRuntimeMessage(
    messageKey: string | null | undefined,
    messageParams: Record<string, any>,
    translator?: RuntimeMessageTranslator,
): string {
    if (!messageKey || !translator) return '';
    const translatedParams = expandMessageParams(messageParams || {});
    try {
        const translated = translator(messageKey, translatedParams);
        if (typeof translated === 'string' && translated && translated !== messageKey) return translated;
    } catch {
        return '';
    }
    return '';
}

export function stripAnsiAndControl(input: unknown): string {
    const value = String(input ?? '');
    return value
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .replace(ANSI_OSC_RE, '')
        .replace(ANSI_CSI_RE, '')
        .replace(ANSI_SINGLE_RE, '')
        .replace(CONTROL_RE, '');
}

export function normalizeRuntimeTaskEvent(raw: unknown): RuntimeTaskEvent {
    const row = asRecord(raw);
    const payload = asRecord(row.payload);
    const eventType = String(row.eventType ?? row.event_type ?? 'unknown').trim().toLowerCase();
    const level = normalizeLevel(row.level ?? payload.level);
    const statusText = String(row.status ?? payload.status ?? '').trim().toLowerCase();
    const status = statusText ? statusText : null;
    const kindText = String(row.kind ?? payload.kind ?? '').trim();
    const kind = kindText || null;

    const payloadMeta = asRecord(payload.meta);
    const sourceText = String(row.source ?? payloadMeta.source ?? '').trim();
    const groupText = String(row.groupId ?? row.group_id ?? payloadMeta.group_id ?? '').trim();

    const messageKeyText = String(
        row.messageKey
        ?? row.message_key
        ?? payload.message_key
        ?? '',
    ).trim();
    const messageKey = messageKeyText || null;
    const messageParams = normalizeMessageParams(
        row.messageParams
        ?? row.message_params
        ?? payload.message_args,
    );

    const rawMessage = stripAnsiAndControl(
        row.rawMessage
        ?? row.raw_message
        ?? payload.raw_message
        ?? payload.message
        ?? '',
    );
    const messageTextRaw = stripAnsiAndControl(row.messageText ?? row.message_text ?? '');
    const messageText = (
        eventType === 'log'
            ? messageTextRaw.replace(/\s+$/, '')
            : messageTextRaw.trim()
    ) || deriveFallbackMessage(eventType, payload, rawMessage);

    const lineCountRaw = Number(row.lineCount ?? row.line_count ?? payloadMeta.line_count ?? 1);
    const lineCount = Number.isFinite(lineCountRaw) && lineCountRaw > 0 ? Math.floor(lineCountRaw) : 1;

    return {
        seq: Number(row.seq ?? 0),
        ts: String(row.ts ?? new Date().toISOString()),
        eventType,
        payload,
        level,
        status,
        kind,
        tags: normalizeTagList(row.tags ?? payload.tags),
        messageKey,
        messageParams,
        messageText,
        rawMessage,
        source: sourceText || null,
        groupId: groupText || null,
        lineCount,
    };
}

export function normalizeRuntimeRoundEvent(raw: unknown): RuntimeRoundEvent | null {
    const row = asRecord(raw);
    const taskId = String(row.taskId ?? row.task_id ?? '').trim();
    if (!taskId) return null;

    const taskIndexRaw = Number(row.taskIndex ?? row.task_index ?? 0);
    const taskIndex = Number.isFinite(taskIndexRaw) && taskIndexRaw > 0 ? Math.floor(taskIndexRaw) : 0;
    if (taskIndex <= 0) return null;

    const taskTypeText = String(row.taskType ?? row.task_type ?? 'custom').trim().toLowerCase();
    const taskType = TASK_TYPES.has(taskTypeText) ? taskTypeText : 'custom';
    const stepId = String(row.stepId ?? row.step_id ?? '').trim() || undefined;

    const stageText = String(row.stage ?? '').trim().toLowerCase();
    const stage = ROUND_STAGES.has(stageText)
        ? (stageText as RuntimeRoundEvent['stage'])
        : deriveStageFromTaskType(taskType);

    const base = normalizeRuntimeTaskEvent(raw);

    return {
        ...base,
        taskId,
        taskIndex,
        taskType: taskType as RuntimeRoundEvent['taskType'],
        stepId,
        stage,
    };
}

export function mergeRuntimeRoundEvents(
    previous: RuntimeRoundEvent[],
    incoming: RuntimeRoundEvent[],
    maxBuffer: number = 20000,
): RuntimeRoundEvent[] {
    const merged = [...previous, ...incoming];
    const dedup = new Map<string, RuntimeRoundEvent>();
    merged.forEach((item) => {
        const key = `${item.taskId}:${Number(item.seq ?? 0)}`;
        dedup.set(key, item);
    });
    const rows = Array.from(dedup.values()).sort((left, right) => {
        const leftTs = Date.parse(String(left.ts ?? ''));
        const rightTs = Date.parse(String(right.ts ?? ''));
        if (Number.isFinite(leftTs) && Number.isFinite(rightTs) && leftTs !== rightTs) return leftTs - rightTs;
        if (Number(left.taskIndex ?? 0) !== Number(right.taskIndex ?? 0)) {
            return Number(left.taskIndex ?? 0) - Number(right.taskIndex ?? 0);
        }
        if (Number(left.seq ?? 0) !== Number(right.seq ?? 0)) return Number(left.seq ?? 0) - Number(right.seq ?? 0);
        return String(left.taskId ?? '').localeCompare(String(right.taskId ?? ''));
    });
    if (rows.length <= maxBuffer) return rows;
    return rows.slice(rows.length - maxBuffer);
}

export function formatRuntimeEventMessage(
    event: RuntimeEventLike,
    options?: {
        translator?: RuntimeMessageTranslator;
        withStepPrefix?: boolean;
    },
): string {
    const translated = translateRuntimeMessage(event.messageKey, event.messageParams || {}, options?.translator);
    const fallback = (
        String(event.eventType || '').toLowerCase() === 'log'
            ? stripAnsiAndControl(event.messageText || '').replace(/\s+$/, '')
            : stripAnsiAndControl(event.messageText || '').trim()
    )
        || deriveFallbackMessage(event.eventType, asRecord(event.payload), stripAnsiAndControl(event.rawMessage || ''));
    const content = translated || fallback || '-';

    const withStepPrefix = Boolean(options?.withStepPrefix);
    if (!withStepPrefix) return content;
    const maybeRound = event as Partial<RuntimeRoundEvent>;
    const taskIndex = Number(maybeRound.taskIndex ?? 0);
    const taskType = String(maybeRound.taskType ?? '').trim().toLowerCase();
    if (taskIndex > 0 && taskType) {
        return `[task#${taskIndex} ${taskType}] ${content}`;
    }
    return content;
}

export function buildRuntimeEventSearchText(event: RuntimeEventLike, messageText?: string): string {
    const message = String(messageText || '').trim();
    const raw = stripAnsiAndControl(event.rawMessage || '');
    const key = String(event.messageKey || '').trim();
    return `${message} ${raw} ${key} ${JSON.stringify(event.payload || {})}`.toLowerCase();
}

export function isRuntimeEventError(event: RuntimeEventLike): boolean {
    const level = String(event.level || '').trim().toUpperCase();
    const status = String(event.status || '').trim().toLowerCase();
    return ['ERROR', 'CRITICAL', 'FATAL'].includes(level) || ['failed', 'error', 'cancelled'].includes(status);
}
