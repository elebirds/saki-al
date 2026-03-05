import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {DeploymentUnitOutlined, FilterOutlined, SearchOutlined} from '@ant-design/icons';
import {Button, Card, Drawer, Input, Segmented, Select, Switch, Tag} from 'antd';
import {useTranslation} from 'react-i18next';

import {RuntimeRoundEvent} from '../../../../types';
import {buildRuntimeEventSearchText, formatRuntimeEventMessage, isRuntimeEventError} from '../runtimeEventFormatter';
import {formatDateTime} from '../runtimeTime';

type StageOption = {
    label: string;
    value: string;
};

type RoundConsolePanelProps = {
    className?: string;
    title: React.ReactNode;
    wsConnected: boolean;
    events: RuntimeRoundEvent[];
    stageValue?: string;
    stageOptions?: StageOption[];
    onStageChange?: (value: string) => void;
    onClearBuffer?: () => void;
    emptyDescription?: string;
    exportFilePrefix?: string;
    maxHeight?: number;
};

const DEFAULT_LOG_TAIL = 500;

const EVENT_TYPE_COLOR: Record<string, string> = {
    log: 'default',
    status: 'blue',
    progress: 'cyan',
    metric: 'green',
    artifact: 'purple',
    worker: 'gold',
};

const LEVEL_COLOR_CLASS: Record<string, string> = {
    TRACE: 'text-slate-400',
    DEBUG: 'text-cyan-300',
    INFO: 'text-blue-300',
    WARNING: 'text-amber-300',
    WARN: 'text-amber-300',
    ERROR: 'text-red-300',
    CRITICAL: 'text-fuchsia-300',
    FATAL: 'text-fuchsia-300',
};

const LEVEL_TAG_COLOR: Record<string, string> = {
    TRACE: 'default',
    DEBUG: 'cyan',
    INFO: 'blue',
    WARNING: 'warning',
    WARN: 'warning',
    ERROR: 'error',
    CRITICAL: 'magenta',
    FATAL: 'magenta',
};

const buildEventFacetsFromItems = (items: RuntimeRoundEvent[]) => {
    const eventTypes: Record<string, number> = {};
    const levels: Record<string, number> = {};
    const tags: Record<string, number> = {};
    items.forEach((item) => {
        const eventType = String(item.eventType || '').trim();
        if (eventType) eventTypes[eventType] = Number(eventTypes[eventType] || 0) + 1;
        const level = String(item.level || '').trim().toUpperCase();
        if (level) levels[level] = Number(levels[level] || 0) + 1;
        (item.tags || []).forEach((tag) => {
            const text = String(tag || '').trim();
            if (!text) return;
            tags[text] = Number(tags[text] || 0) + 1;
        });
    });
    return {eventTypes, levels, tags};
};

type ConsoleEventBlock = {
    key: string;
    taskId: string;
    taskIndex: number;
    taskType: string;
    epoch: number | null;
    totalEpochs: number | null;
    events: RuntimeRoundEvent[];
    grouped: boolean;
};

const EPOCH_FROM_PROGRESS_RE = /^\s*(\d+)\s*\/\s*(\d+)/;
const EPOCH_FROM_HEADER_RE = /(?:^|\n)\s*epoch\s+(\d+)\s*\(\s*(\d+)\s*\/\s*(\d+)\s*\)/i;
const EPOCH_FROM_TRAIN_ROW_RE = /(?:^|\n)\s*(\d+)\s*\/\s*(\d+)\b/m;
const TRAIN_ROW_HINT_RE = /\b(?:gpu_mem|box_loss|cls_loss|dfl_loss|instances|size)\b/i;

const asEpoch = (value: unknown): number | null => {
    const epoch = Number(value);
    if (!Number.isFinite(epoch) || epoch <= 0) return null;
    return Math.floor(epoch);
};

type EpochHint = {
    epoch: number | null;
    total: number | null;
};

const parseEpochFromLogMessage = (message: string): EpochHint => {
    const text = String(message || '');
    if (!text.trim()) return {epoch: null, total: null};
    const headerMatch = text.match(EPOCH_FROM_HEADER_RE);
    if (headerMatch) {
        return {
            epoch: asEpoch(headerMatch[1]),
            total: asEpoch(headerMatch[3]),
        };
    }
    const progressMatch = text.match(EPOCH_FROM_PROGRESS_RE);
    if (progressMatch) {
        return {
            epoch: asEpoch(progressMatch[1]),
            total: asEpoch(progressMatch[2]),
        };
    }
    if (TRAIN_ROW_HINT_RE.test(text)) {
        const trainRowMatch = text.match(EPOCH_FROM_TRAIN_ROW_RE);
        if (trainRowMatch) {
            return {
                epoch: asEpoch(trainRowMatch[1]),
                total: asEpoch(trainRowMatch[2]),
            };
        }
    }
    return {epoch: null, total: null};
};

const resolveEventSource = (event: RuntimeRoundEvent, payload: Record<string, any>): string => {
    const meta = payload.meta && typeof payload.meta === 'object'
        ? (payload.meta as Record<string, any>)
        : {};
    return String(event.source ?? meta.source ?? '').trim().toLowerCase();
};

const buildLogMessageCandidates = (event: RuntimeRoundEvent, payload: Record<string, any>): string[] => {
    const seen = new Set<string>();
    const items: string[] = [];
    const push = (raw: unknown) => {
        const text = String(raw ?? '');
        if (!text.trim()) return;
        if (seen.has(text)) return;
        seen.add(text);
        items.push(text);
    };
    push(event.messageText);
    push(event.rawMessage);
    push(payload.raw_message);
    push(payload.rawMessage);
    push(payload.message);
    return items;
};

const inferEventEpoch = (
    event: RuntimeRoundEvent,
    lastEpochByStep: Map<string, number>,
    lastTotalByStep: Map<string, number>,
): EpochHint => {
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const params = event.messageParams && typeof event.messageParams === 'object' ? event.messageParams : {};
    const direct = asEpoch(payload.epoch ?? (params as any).epoch);
    const directTotal = asEpoch(
        payload.total_steps
        ?? payload.totalSteps
        ?? (params as any).total_steps
        ?? (params as any).totalSteps,
    );
    if (directTotal != null) lastTotalByStep.set(event.taskId, directTotal);
    if (direct != null) {
        lastEpochByStep.set(event.taskId, direct);
        return {
            epoch: direct,
            total: directTotal ?? lastTotalByStep.get(event.taskId) ?? null,
        };
    }
    if (event.eventType === 'log') {
        const source = resolveEventSource(event, payload);
        const candidates = buildLogMessageCandidates(event, payload);
        for (const message of candidates) {
            const parsedHint = parseEpochFromLogMessage(message);
            if (parsedHint.total != null) lastTotalByStep.set(event.taskId, parsedHint.total);
            if (parsedHint.epoch == null) continue;
            lastEpochByStep.set(event.taskId, parsedHint.epoch);
            return {
                epoch: parsedHint.epoch,
                total: parsedHint.total ?? lastTotalByStep.get(event.taskId) ?? null,
            };
        }
        if (source !== 'worker_stdio') {
            const remembered = lastEpochByStep.get(event.taskId);
            if (remembered != null) {
                return {
                    epoch: remembered,
                    total: lastTotalByStep.get(event.taskId) ?? null,
                };
            }
        }
    }
    return {epoch: null, total: lastTotalByStep.get(event.taskId) ?? null};
};

const buildConsoleBlocks = (events: RuntimeRoundEvent[]): ConsoleEventBlock[] => {
    if (events.length === 0) return [];
    const lastEpochByStep = new Map<string, number>();
    const lastTotalByStep = new Map<string, number>();
    const annotated = events.map((event) => ({
        event,
        hint: inferEventEpoch(event, lastEpochByStep, lastTotalByStep),
    }));

    const blocks: ConsoleEventBlock[] = [];
    let index = 0;
    while (index < annotated.length) {
        const seed = annotated[index];
        const seedEvent = seed.event;
        const seedEpoch = seed.hint.epoch;
        let seedTotalEpochs = seed.hint.total;
        const seedStepId = String(seedEvent.taskId || '');
        const seedStepIndex = Number(seedEvent.taskIndex || 0);
        const seedStepType = String(seedEvent.taskType || 'custom');

        if (seedEpoch == null) {
            blocks.push({
                key: `${seedStepId}:${seedEvent.seq}:single`,
                taskId: seedStepId,
                taskIndex: seedStepIndex,
                taskType: seedStepType,
                epoch: null,
                totalEpochs: null,
                events: [seedEvent],
                grouped: false,
            });
            index += 1;
            continue;
        }

        const groupedEvents: RuntimeRoundEvent[] = [seedEvent];
        let cursor = index + 1;
        while (cursor < annotated.length) {
            const item = annotated[cursor];
            const event = item.event;
            if (String(event.taskId || '') !== seedStepId) break;
            if (!['progress', 'metric', 'log'].includes(String(event.eventType || '').toLowerCase())) break;
            if (item.hint.epoch !== seedEpoch) break;
            if (seedTotalEpochs == null && item.hint.total != null) seedTotalEpochs = item.hint.total;
            groupedEvents.push(event);
            cursor += 1;
        }

        const hasSemantic = groupedEvents.some((item) => item.eventType === 'progress' || item.eventType === 'metric');
        const hasLog = groupedEvents.some((item) => item.eventType === 'log');
        if (groupedEvents.length >= 2 && hasSemantic && hasLog) {
            blocks.push({
                key: `${seedStepId}:epoch:${seedEpoch}:${groupedEvents[0].seq}`,
                taskId: seedStepId,
                taskIndex: seedStepIndex,
                taskType: seedStepType,
                epoch: seedEpoch,
                totalEpochs: seedTotalEpochs,
                events: groupedEvents,
                grouped: true,
            });
            index = cursor;
            continue;
        }

        blocks.push({
            key: `${seedStepId}:${seedEvent.seq}:single`,
            taskId: seedStepId,
            taskIndex: seedStepIndex,
            taskType: seedStepType,
            epoch: seedEpoch,
            totalEpochs: seedTotalEpochs,
            events: [seedEvent],
            grouped: false,
        });
        index += 1;
    }
    return blocks;
};

const RoundConsolePanel: React.FC<RoundConsolePanelProps> = ({
    className,
    title,
    wsConnected,
    events,
    stageValue,
    stageOptions,
    onStageChange,
    onClearBuffer,
    emptyDescription = '暂无命中日志',
    exportFilePrefix = 'round-console',
    maxHeight = 560,
}) => {
    const {t} = useTranslation();

    const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
    const [eventLevelFilter, setEventLevelFilter] = useState<string[]>([]);
    const [eventTagFilter, setEventTagFilter] = useState<string[]>([]);
    const [eventQueryText, setEventQueryText] = useState<string>('');
    const [onlyErrors, setOnlyErrors] = useState<boolean>(false);
    const [autoScrollLogs, setAutoScrollLogs] = useState<boolean>(true);
    const [logTailLimit, setLogTailLimit] = useState<number>(DEFAULT_LOG_TAIL);
    const [rawEvent, setRawEvent] = useState<RuntimeRoundEvent | null>(null);
    const logScrollRef = useRef<HTMLDivElement | null>(null);

    const eventFacets = useMemo(() => buildEventFacetsFromItems(events), [events]);
    const stageNavOptions = useMemo(
        () => (stageOptions || []).map((item) => ({label: String(item.label), value: String(item.value)})),
        [stageOptions],
    );

    const getDisplayMessage = useCallback(
        (event: RuntimeRoundEvent) => formatRuntimeEventMessage(event, {translator: t, withStepPrefix: false}),
        [t],
    );

    const visibleEvents = useMemo(() => {
        const eventTypeSet = new Set((eventTypeFilter || []).map((item) => String(item).toLowerCase()));
        const levelSet = new Set((eventLevelFilter || []).map((item) => String(item).toUpperCase()));
        const tagSet = new Set((eventTagFilter || []).map((item) => String(item).toLowerCase()));
        const query = eventQueryText.trim().toLowerCase();

        let rows = events.filter((item) => {
            const level = String(item.level || '').toUpperCase();
            const eventType = String(item.eventType || '').toLowerCase();
            if (eventTypeSet.size > 0 && !eventTypeSet.has(eventType)) return false;
            if (levelSet.size > 0 && !levelSet.has(level)) return false;
            if (tagSet.size > 0) {
                const rowTags = (item.tags || []).map((tag) => String(tag).toLowerCase());
                if (!rowTags.some((tag) => tagSet.has(tag))) return false;
            }
            const messageText = getDisplayMessage(item);
            if (query) {
                const haystack = buildRuntimeEventSearchText(item, messageText);
                if (!haystack.includes(query)) return false;
            }
            if (onlyErrors && !isRuntimeEventError(item)) return false;
            return true;
        });

        if (logTailLimit > 0 && rows.length > logTailLimit) rows = rows.slice(rows.length - logTailLimit);
        return rows;
    }, [events, eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText, onlyErrors, logTailLimit, getDisplayMessage]);

    const consoleBlocks = useMemo(() => buildConsoleBlocks(visibleEvents), [visibleEvents]);

    useEffect(() => {
        if (!autoScrollLogs) return;
        const container = logScrollRef.current;
        if (!container) return;
        container.scrollTop = container.scrollHeight;
    }, [visibleEvents.length, autoScrollLogs]);

    const handleClearLogs = useCallback(() => {
        onClearBuffer?.();
    }, [onClearBuffer]);

    const handleResetFilters = useCallback(() => {
        setEventTypeFilter([]);
        setEventLevelFilter([]);
        setEventTagFilter([]);
        setEventQueryText('');
        setOnlyErrors(false);
        setLogTailLimit(DEFAULT_LOG_TAIL);
    }, []);

    const handleExportLogs = useCallback(() => {
        if (visibleEvents.length === 0) return;
        const lines = visibleEvents.map((item) => {
            const level = String(item.level || item.status || item.eventType || '').trim();
            const message = getDisplayMessage(item);
            const taskTag = `task#${Number(item.taskIndex || 0)} ${String(item.taskType || 'custom')}`;
            return `[${item.ts}] #${item.seq} [${level}] [${taskTag}] ${message}`;
        });
        const content = lines.join('\n');
        const blob = new Blob([content], {type: 'text/plain;charset=utf-8'});
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${exportFilePrefix}-logs.txt`;
        anchor.click();
        window.URL.revokeObjectURL(url);
    }, [visibleEvents, exportFilePrefix, getDisplayMessage]);

    const showStageSelector = Boolean(stageNavOptions.length > 0 && onStageChange);
    const useSegmentedStageNav = Boolean(showStageSelector && stageNavOptions.length <= 6);

    const hasActiveFilters = Boolean(
        eventTypeFilter.length > 0
        || eventLevelFilter.length > 0
        || eventTagFilter.length > 0
        || Boolean(eventQueryText.trim())
        || onlyErrors
        || logTailLimit !== DEFAULT_LOG_TAIL,
    );

    return (
        <>
            <Card
                className={className}
                title={title}
            >
                <div className="flex flex-col gap-3">
                    <div className="relative overflow-hidden rounded-lg border border-github-border/80 bg-github-panel">
                        <div
                            className="pointer-events-none absolute inset-0 opacity-80"
                            style={{
                                background: 'radial-gradient(1000px 220px at -8% -30%, rgba(56, 139, 253, 0.20), transparent 60%), radial-gradient(700px 220px at 105% 0%, rgba(47, 129, 247, 0.14), transparent 68%)',
                            }}
                        />
                        <div className="relative flex flex-col gap-3 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="flex items-center gap-1 text-xs text-github-muted">
                                    <SearchOutlined/>
                                    检索
                                </span>
                                <Input.Search
                                    allowClear
                                    className="min-w-[280px] flex-1"
                                    placeholder="搜索 message/payload"
                                    value={eventQueryText}
                                    onChange={(event) => setEventQueryText(String(event.target.value || ''))}
                                />

                                <div className="ml-auto flex items-center gap-2">
                                    <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WS 实时' : 'WS 断开'}</Tag>
                                    <Button size="small" onClick={handleClearLogs}>清屏</Button>
                                    <Button size="small" onClick={handleResetFilters} disabled={!hasActiveFilters}>
                                        重置筛选
                                    </Button>
                                    <Button size="small" onClick={handleExportLogs} disabled={visibleEvents.length === 0}>
                                        导出
                                    </Button>
                                </div>
                            </div>

                            {showStageSelector ? (
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="flex items-center gap-1 text-xs text-github-muted">
                                        <DeploymentUnitOutlined/>
                                        阶段
                                    </span>
                                    {useSegmentedStageNav ? (
                                        <Segmented
                                            options={stageNavOptions}
                                            value={stageValue}
                                            onChange={(value) => onStageChange?.(String(value || 'all'))}
                                        />
                                    ) : (
                                        <Select
                                            className="w-[220px]"
                                            options={stageNavOptions}
                                            value={stageValue}
                                            onChange={(value) => onStageChange?.(String(value || 'all'))}
                                        />
                                    )}
                                </div>
                            ) : null}

                            <div className="flex flex-wrap items-center gap-2">
                                <span className="flex items-center gap-1 text-xs text-github-muted">
                                    <FilterOutlined/>
                                    过滤
                                </span>
                                <Select
                                    mode="multiple"
                                    allowClear
                                    className="w-[180px]"
                                    placeholder="事件类型"
                                    value={eventTypeFilter}
                                    options={Object.entries(eventFacets.eventTypes || {}).map(([name, count]) => ({
                                        label: `${name} (${count})`,
                                        value: name,
                                    }))}
                                    onChange={(values) => setEventTypeFilter(values)}
                                />
                                <Select
                                    mode="multiple"
                                    allowClear
                                    className="w-[180px]"
                                    placeholder="日志级别"
                                    value={eventLevelFilter}
                                    options={Object.entries(eventFacets.levels || {}).map(([name, count]) => ({
                                        label: `${name} (${count})`,
                                        value: name,
                                    }))}
                                    onChange={(values) => setEventLevelFilter(values)}
                                />
                                <Select
                                    mode="multiple"
                                    allowClear
                                    className="w-[220px]"
                                    placeholder="业务标签"
                                    value={eventTagFilter}
                                    options={Object.entries(eventFacets.tags || {})
                                        .sort((left, right) => Number(right[1]) - Number(left[1]))
                                        .slice(0, 200)
                                        .map(([name, count]) => ({
                                            label: `${name} (${count})`,
                                            value: name,
                                        }))}
                                    onChange={(values) => setEventTagFilter(values)}
                                />
                                <Select
                                    value={logTailLimit}
                                    className="w-[120px]"
                                    options={[
                                        {label: '尾部 200', value: 200},
                                        {label: '尾部 500', value: 500},
                                        {label: '尾部 1000', value: 1000},
                                        {label: '全部', value: 0},
                                    ]}
                                    onChange={(value) => setLogTailLimit(Number(value || 0))}
                                />

                                <span className="inline-flex items-center gap-1 rounded border border-github-border bg-github-panel px-2 py-1">
                                    <Switch size="small" checked={onlyErrors} onChange={setOnlyErrors}/>
                                    <span className="text-xs text-github-muted">仅错误</span>
                                </span>
                                <span className="inline-flex items-center gap-1 rounded border border-github-border bg-github-panel px-2 py-1">
                                    <Switch size="small" checked={autoScrollLogs} onChange={setAutoScrollLogs}/>
                                    <span className="text-xs text-github-muted">自动滚动</span>
                                </span>

                                <Tag>{`显示 ${visibleEvents.length} / 缓冲 ${events.length}`}</Tag>
                            </div>
                        </div>
                    </div>

                    <div
                        ref={logScrollRef}
                        className="overflow-auto rounded border border-github-border bg-slate-950 p-2"
                        style={{maxHeight}}
                    >
                        {visibleEvents.length === 0 ? (
                            <div className="py-8 text-center text-xs text-slate-400">{emptyDescription}</div>
                        ) : (
                            <div className="space-y-1 font-mono text-xs">
                                {consoleBlocks.map((block) => {
                                    if (!block.grouped || block.events.length <= 1) {
                                        const item = block.events[0];
                                        const levelKey = String(item.level || '').toUpperCase();
                                        const lineClass = LEVEL_COLOR_CLASS[levelKey] || 'text-slate-200';
                                        const messageText = getDisplayMessage(item);
                                        const lineCount = Number(item.lineCount || 1);
                                        return (
                                            <div
                                                key={block.key}
                                                className={`rounded px-2 py-1 ${lineClass} hover:bg-slate-900`}
                                            >
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="text-slate-400">{formatDateTime(item.ts)}</span>
                                                    <span className="text-slate-500">#{item.seq}</span>
                                                    <Tag color={EVENT_TYPE_COLOR[item.eventType] || 'default'} className="!m-0">{item.eventType}</Tag>
                                                    <Tag color="geekblue" className="!m-0">{`task#${Number(item.taskIndex || 0)} ${String(item.taskType || 'custom')}`}</Tag>
                                                    {item.level ? (
                                                        <Tag color={LEVEL_TAG_COLOR[levelKey] || 'blue'} className="!m-0">{item.level}</Tag>
                                                    ) : null}
                                                    {item.source ? <Tag className="!m-0">{item.source}</Tag> : null}
                                                    {lineCount > 1 ? <Tag className="!m-0">{`${lineCount} lines`}</Tag> : null}
                                                    {(item.tags || []).slice(0, 4).map((tag, tagIdx) => (
                                                        <Tag key={`${item.taskId}-${item.ts}-${item.seq}-${tag}-${tagIdx}`} className="!m-0">{tag}</Tag>
                                                    ))}
                                                    <Button
                                                        size="small"
                                                        type="text"
                                                        className="!h-5 !px-1 text-slate-300"
                                                        onClick={() => setRawEvent(item)}
                                                    >
                                                        查看原始
                                                    </Button>
                                                </div>
                                                <div className="mt-1 whitespace-pre-wrap break-all">{messageText || '-'}</div>
                                            </div>
                                        );
                                    }

                                    return (
                                        <div
                                            key={block.key}
                                            className="rounded border border-slate-700/70 bg-slate-900/40 px-2 py-2"
                                        >
                                            <div className="mb-1 flex flex-wrap items-center gap-2 text-slate-300">
                                                <Tag color="geekblue" className="!m-0">{`task#${block.taskIndex} ${block.taskType}`}</Tag>
                                                {block.epoch != null ? (
                                                    <Tag color="processing" className="!m-0">
                                                        {block.totalEpochs != null
                                                            ? `epoch ${block.epoch} (${block.epoch}/${block.totalEpochs})`
                                                            : `epoch ${block.epoch}`}
                                                    </Tag>
                                                ) : null}
                                                <Tag className="!m-0">{`${block.events.length} events`}</Tag>
                                                <span className="text-slate-500">
                                                    {formatDateTime(block.events[0]?.ts)}
                                                    {' ~ '}
                                                    {formatDateTime(block.events[block.events.length - 1]?.ts)}
                                                </span>
                                            </div>
                                            <div className="space-y-1">
                                                {block.events.map((item, idx) => {
                                                    const levelKey = String(item.level || '').toUpperCase();
                                                    const lineClass = LEVEL_COLOR_CLASS[levelKey] || 'text-slate-200';
                                                    const messageText = getDisplayMessage(item);
                                                    const lineCount = Number(item.lineCount || 1);
                                                    return (
                                                        <div
                                                            key={`${block.key}:${item.seq}:${idx}`}
                                                            className={`rounded px-2 py-1 ${lineClass} hover:bg-slate-900`}
                                                        >
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <span className="text-slate-400">{formatDateTime(item.ts)}</span>
                                                                <span className="text-slate-500">#{item.seq}</span>
                                                                <Tag color={EVENT_TYPE_COLOR[item.eventType] || 'default'} className="!m-0">{item.eventType}</Tag>
                                                                {item.level ? (
                                                                    <Tag color={LEVEL_TAG_COLOR[levelKey] || 'blue'} className="!m-0">{item.level}</Tag>
                                                                ) : null}
                                                                {item.source ? <Tag className="!m-0">{item.source}</Tag> : null}
                                                                {lineCount > 1 ? <Tag className="!m-0">{`${lineCount} lines`}</Tag> : null}
                                                                <Button
                                                                    size="small"
                                                                    type="text"
                                                                    className="!h-5 !px-1 text-slate-300"
                                                                    onClick={() => setRawEvent(item)}
                                                                >
                                                                    查看原始
                                                                </Button>
                                                            </div>
                                                            <div className="mt-1 whitespace-pre-wrap break-all">{messageText || '-'}</div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>
            </Card>

            <Drawer
                title="原始事件"
                open={Boolean(rawEvent)}
                width={720}
                onClose={() => setRawEvent(null)}
                destroyOnClose
            >
                {rawEvent ? (
                    <div className="space-y-4">
                        <div>
                            <div className="mb-1 text-xs text-slate-500">语义文案</div>
                            <pre className="rounded border border-github-border bg-github-bg p-2 whitespace-pre-wrap break-all">
                                {formatRuntimeEventMessage(rawEvent, {translator: t, withStepPrefix: false})}
                            </pre>
                        </div>
                        <div>
                            <div className="mb-1 text-xs text-slate-500">raw_message</div>
                            <pre className="rounded border border-github-border bg-github-bg p-2 whitespace-pre-wrap break-all">
                                {rawEvent.rawMessage || '-'}
                            </pre>
                        </div>
                        <div>
                            <div className="mb-1 text-xs text-slate-500">payload</div>
                            <pre className="rounded border border-github-border bg-github-bg p-2 whitespace-pre-wrap break-all">
                                {JSON.stringify(rawEvent.payload || {}, null, 2)}
                            </pre>
                        </div>
                    </div>
                ) : null}
            </Drawer>
        </>
    );
};

export default RoundConsolePanel;
