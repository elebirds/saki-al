import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {DeploymentUnitOutlined, FilterOutlined, SearchOutlined} from '@ant-design/icons';
import {Button, Card, Input, Segmented, Select, Switch, Tag} from 'antd';

import {RuntimeRoundEvent} from '../../../../types';

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

const ERROR_LEVELS = new Set(['ERROR', 'CRITICAL', 'FATAL']);
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
    DEBUG: 'text-slate-300',
    INFO: 'text-blue-300',
    WARNING: 'text-amber-300',
    WARN: 'text-amber-300',
    ERROR: 'text-red-300',
    CRITICAL: 'text-fuchsia-300',
    FATAL: 'text-fuchsia-300',
};

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const buildEventFacetsFromItems = (items: RuntimeRoundEvent[]) => {
    const eventTypes: Record<string, number> = {};
    const levels: Record<string, number> = {};
    const tags: Record<string, number> = {};
    items.forEach((item) => {
        const eventType = String(item.eventType || '').trim();
        if (eventType) eventTypes[eventType] = Number(eventTypes[eventType] || 0) + 1;
        const level = String(item.level || '').trim();
        if (level) levels[level] = Number(levels[level] || 0) + 1;
        (item.tags || []).forEach((tag) => {
            const text = String(tag || '').trim();
            if (!text) return;
            tags[text] = Number(tags[text] || 0) + 1;
        });
    });
    return {eventTypes, levels, tags};
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
    const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
    const [eventLevelFilter, setEventLevelFilter] = useState<string[]>([]);
    const [eventTagFilter, setEventTagFilter] = useState<string[]>([]);
    const [eventQueryText, setEventQueryText] = useState<string>('');
    const [onlyErrors, setOnlyErrors] = useState<boolean>(false);
    const [autoScrollLogs, setAutoScrollLogs] = useState<boolean>(true);
    const [logTailLimit, setLogTailLimit] = useState<number>(DEFAULT_LOG_TAIL);
    const logScrollRef = useRef<HTMLDivElement | null>(null);

    const eventFacets = useMemo(() => buildEventFacetsFromItems(events), [events]);
    const stageNavOptions = useMemo(
        () => (stageOptions || []).map((item) => ({label: String(item.label), value: String(item.value)})),
        [stageOptions],
    );

    const visibleEvents = useMemo(() => {
        const eventTypeSet = new Set((eventTypeFilter || []).map((item) => String(item).toLowerCase()));
        const levelSet = new Set((eventLevelFilter || []).map((item) => String(item).toUpperCase()));
        const tagSet = new Set((eventTagFilter || []).map((item) => String(item).toLowerCase()));
        const query = eventQueryText.trim().toLowerCase();
        let rows = events.filter((item) => {
            if (eventTypeSet.size > 0 && !eventTypeSet.has(String(item.eventType || '').toLowerCase())) return false;
            if (levelSet.size > 0 && !levelSet.has(String(item.level || '').toUpperCase())) return false;
            if (tagSet.size > 0) {
                const rowTags = (item.tags || []).map((tag) => String(tag).toLowerCase());
                if (!rowTags.some((tag) => tagSet.has(tag))) return false;
            }
            if (query) {
                const haystack = `${item.messageText || ''} ${JSON.stringify(item.payload || {})}`.toLowerCase();
                if (!haystack.includes(query)) return false;
            }
            if (onlyErrors) {
                const level = String(item.level || '').toUpperCase();
                const status = String(item.status || '').toLowerCase();
                if (!ERROR_LEVELS.has(level) && !['failed', 'error', 'cancelled'].includes(status)) return false;
            }
            return true;
        });
        if (logTailLimit > 0 && rows.length > logTailLimit) rows = rows.slice(rows.length - logTailLimit);
        return rows;
    }, [events, eventTypeFilter, eventLevelFilter, eventTagFilter, eventQueryText, onlyErrors, logTailLimit]);

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
            const tagText = (item.tags || []).join(',');
            return `[${item.ts}] #${item.seq} [${level}] [${tagText}] ${item.messageText || ''}`;
        });
        const content = lines.join('\n');
        const blob = new Blob([content], {type: 'text/plain;charset=utf-8'});
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${exportFilePrefix}-logs.txt`;
        anchor.click();
        window.URL.revokeObjectURL(url);
    }, [visibleEvents, exportFilePrefix]);

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
                                className="w-[160px]"
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
                                placeholder="Tag"
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
                            {visibleEvents.map((item, idx) => {
                                const levelKey = String(item.level || '').toUpperCase();
                                const lineClass = LEVEL_COLOR_CLASS[levelKey] || 'text-slate-200';
                                return (
                                    <div key={`${item.stepId}-${item.ts}-${item.seq}-${item.eventType}-${idx}`} className={`rounded px-2 py-1 ${lineClass} hover:bg-slate-900`}>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-slate-400">{formatDateTime(item.ts)}</span>
                                            <span className="text-slate-500">#{item.seq}</span>
                                            <Tag color={EVENT_TYPE_COLOR[item.eventType] || 'default'} className="!m-0">{item.eventType}</Tag>
                                            {item.level ? <Tag color={ERROR_LEVELS.has(String(item.level).toUpperCase()) ? 'error' : 'blue'} className="!m-0">{item.level}</Tag> : null}
                                            {(item.tags || []).slice(0, 4).map((tag, tagIdx) => (
                                                <Tag key={`${item.stepId}-${item.ts}-${item.seq}-${tag}-${tagIdx}`} className="!m-0">{tag}</Tag>
                                            ))}
                                        </div>
                                        <div className="mt-1 whitespace-pre-wrap break-all">{item.messageText || '-'}</div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </Card>
    );
};

export default RoundConsolePanel;
