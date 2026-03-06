import {Dispatch, SetStateAction, useCallback, useEffect, useRef, useState} from 'react';

import {
    RuntimeRoundArtifact,
    RuntimeRoundEvent,
    RuntimeStep,
    RuntimeTaskMetricPoint,
} from '../../../../types';
import {api} from '../../../../services/api';
import {mergeRuntimeRoundEvents, normalizeRuntimeRoundEvent} from '../runtimeEventFormatter';
import {ROUND_WS_RECONNECT_DELAYS, buildRoundEventsWsUrl} from '../runtimeRoundWs';
import {MAX_EVENT_BUFFER, ROUND_EVENT_SYNC_LIMIT} from './constants';
import {RoundStageKey} from './types';
import {
    buildArtifactFromRoundEvent,
    buildArtifactKey,
    extractMetricPointsFromEvent,
    isTerminalStepState,
    mergeMetricPoints,
    normalizeIncomingStepState,
} from './transforms';

interface UseRoundEventStreamOptions {
    canManageLoops: boolean;
    roundId?: string;
    token?: string | null;
    activeConsoleStages: RoundStageKey[];
    scheduleRoundMetaRefresh: () => void;
    ensureArtifactUrls: (items: RuntimeRoundArtifact[]) => Promise<void>;
    setSteps: Dispatch<SetStateAction<RuntimeStep[]>>;
    setTrainMetricPoints: Dispatch<SetStateAction<RuntimeTaskMetricPoint[]>>;
    setRoundArtifacts: Dispatch<SetStateAction<RuntimeRoundArtifact[]>>;
}

export const useRoundEventStream = ({
    canManageLoops,
    roundId,
    token,
    activeConsoleStages,
    scheduleRoundMetaRefresh,
    ensureArtifactUrls,
    setSteps,
    setTrainMetricPoints,
    setRoundArtifacts,
}: UseRoundEventStreamOptions) => {
    const [events, setEvents] = useState<RuntimeRoundEvent[]>([]);
    const [wsConnected, setWsConnected] = useState(false);

    const eventsRef = useRef<RuntimeRoundEvent[]>([]);
    const roundEventCursorRef = useRef<string | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const wsRetryTimerRef = useRef<number | null>(null);
    const wsRetryCountRef = useRef(0);
    const wsClosedRef = useRef(false);

    useEffect(() => {
        eventsRef.current = events;
    }, [events]);

    const clearEventsBuffer = useCallback(() => {
        eventsRef.current = [];
        setEvents([]);
    }, []);

    useEffect(() => {
        return () => {
            if (wsRetryTimerRef.current != null) {
                window.clearTimeout(wsRetryTimerRef.current);
                wsRetryTimerRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, []);

    useEffect(() => {
        if (!canManageLoops || !roundId || !token) {
            clearEventsBuffer();
            setWsConnected(false);
            roundEventCursorRef.current = null;
            wsRetryCountRef.current = 0;
            return;
        }

        let cancelled = false;
        wsClosedRef.current = false;
        wsRetryCountRef.current = 0;
        roundEventCursorRef.current = null;
        clearEventsBuffer();

        const closeSocket = () => {
            if (wsRetryTimerRef.current != null) {
                window.clearTimeout(wsRetryTimerRef.current);
                wsRetryTimerRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };

        const applyIncomingEvents = (incoming: RuntimeRoundEvent[]) => {
            if (incoming.length === 0 || cancelled) return;
            const merged = mergeRuntimeRoundEvents(eventsRef.current, incoming, MAX_EVENT_BUFFER);
            eventsRef.current = merged;
            setEvents(merged);

            const metricPoints = incoming.flatMap((item) => extractMetricPointsFromEvent(item));
            if (metricPoints.length > 0) {
                setTrainMetricPoints((prev) => mergeMetricPoints(prev, metricPoints));
            }

            const artifactRows = incoming
                .map((item) => buildArtifactFromRoundEvent(item))
                .filter((item): item is RuntimeRoundArtifact => Boolean(item));
            if (artifactRows.length > 0) {
                setRoundArtifacts((prev) => {
                    const rowMap = new Map<string, RuntimeRoundArtifact>();
                    prev.forEach((item) => {
                        const taskId = String(item.taskId || '').trim();
                        if (!taskId) return;
                        rowMap.set(buildArtifactKey(taskId, item.name), item);
                    });
                    artifactRows.forEach((item) => {
                        const taskId = String(item.taskId || '').trim();
                        if (!taskId) return;
                        rowMap.set(buildArtifactKey(taskId, item.name), item);
                    });
                    return Array.from(rowMap.values()).sort(
                        (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
                    );
                });
                void ensureArtifactUrls(artifactRows);
            }

            const statusRows = incoming.filter((item) => item.eventType === 'status');
            let shouldRefreshRoundMeta = false;
            if (statusRows.length > 0) {
                setSteps((prev) => {
                    if (!prev || prev.length === 0) return prev;
                    const indexMap = new Map(prev.map((item, idx) => [item.id, idx]));
                    const next = [...prev];
                    let changed = false;
                    statusRows.forEach((row) => {
                        const stepId = String(row.stepId || '').trim();
                        if (!stepId) return;
                        const idx = indexMap.get(stepId);
                        if (idx == null) return;
                        const current = next[idx];
                        if (!current) return;
                        const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
                        const normalizedState = normalizeIncomingStepState(payload.status ?? row.status);
                        if (!normalizedState) return;
                        const nextStartedAt = current.startedAt
                            || ([
                                'ready',
                                'dispatching',
                                'syncing_env',
                                'probing_runtime',
                                'binding_device',
                                'running',
                                'retrying',
                            ].includes(normalizedState)
                                ? String(payload.startedAt ?? payload.started_at ?? row.ts)
                                : current.startedAt);
                        const nextEndedAt = isTerminalStepState(normalizedState)
                            ? String(payload.endedAt ?? payload.ended_at ?? row.ts)
                            : current.endedAt;
                        const nextLastError = normalizedState === 'failed'
                            ? (String(payload.reason ?? payload.error ?? current.lastError ?? '').trim() || current.lastError)
                            : current.lastError;
                        if (
                            normalizedState === current.state
                            && nextStartedAt === current.startedAt
                            && nextEndedAt === current.endedAt
                            && nextLastError === current.lastError
                        ) {
                            return;
                        }
                        changed = true;
                        next[idx] = {
                            ...current,
                            state: normalizedState,
                            startedAt: nextStartedAt,
                            endedAt: nextEndedAt,
                            lastError: nextLastError,
                        };
                    });
                    if (!changed) return prev;
                    if (next.length > 0 && next.every((item) => isTerminalStepState(item.state))) {
                        shouldRefreshRoundMeta = true;
                    }
                    return next;
                });
            }

            if (shouldRefreshRoundMeta || statusRows.some((row) => {
                const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
                const state = normalizeIncomingStepState(payload.status ?? row.status);
                return state === 'failed' || state === 'cancelled';
            })) {
                scheduleRoundMetaRefresh();
            }
        };

        const syncRoundEvents = async () => {
            let afterCursor = roundEventCursorRef.current || undefined;
            let hasMore = true;
            let pageCount = 0;
            let nextCursor = roundEventCursorRef.current;
            const incoming: RuntimeRoundEvent[] = [];
            while (hasMore && pageCount < 20) {
                const response = await api.getRoundEvents(roundId, {
                    afterCursor,
                    limit: ROUND_EVENT_SYNC_LIMIT,
                    stages: activeConsoleStages.length > 0 ? activeConsoleStages : undefined,
                });
                const items = (response.items || []).filter((item) => Boolean(item.taskId));
                if (items.length > 0) {
                    incoming.push(...items);
                }
                nextCursor = response.nextAfterCursor ?? nextCursor ?? null;
                hasMore = Boolean(response.hasMore);
                afterCursor = response.nextAfterCursor || undefined;
                pageCount += 1;
            }
            if (cancelled) return;
            roundEventCursorRef.current = nextCursor ?? roundEventCursorRef.current;
            applyIncomingEvents(incoming);
        };

        const scheduleReconnect = () => {
            if (cancelled || wsClosedRef.current) return;
            const nextRetry = wsRetryCountRef.current + 1;
            wsRetryCountRef.current = nextRetry;
            const delay = ROUND_WS_RECONNECT_DELAYS[Math.min(nextRetry - 1, ROUND_WS_RECONNECT_DELAYS.length - 1)];
            wsRetryTimerRef.current = window.setTimeout(async () => {
                wsRetryTimerRef.current = null;
                if (cancelled || wsClosedRef.current) return;
                if (nextRetry >= 3) {
                    try {
                        await syncRoundEvents();
                    } catch {
                        // ignore catch-up failure and keep retrying ws
                    }
                }
                if (!cancelled && !wsClosedRef.current) {
                    connectSocket();
                }
            }, delay);
        };

        const connectSocket = () => {
            if (cancelled || wsClosedRef.current) return;
            closeSocket();
            const ws = new WebSocket(
                buildRoundEventsWsUrl(roundId, token, {
                    afterCursor: roundEventCursorRef.current || undefined,
                    stages: activeConsoleStages.length > 0 ? activeConsoleStages : undefined,
                }),
            );
            wsRef.current = ws;
            ws.onopen = () => {
                if (cancelled) return;
                wsRetryCountRef.current = 0;
                setWsConnected(true);
            };
            ws.onclose = () => {
                if (cancelled || wsClosedRef.current) return;
                setWsConnected(false);
                wsRef.current = null;
                scheduleReconnect();
            };
            ws.onerror = () => {
                if (cancelled) return;
                setWsConnected(false);
            };
            ws.onmessage = (messageEvent: MessageEvent<string>) => {
                try {
                    const raw = JSON.parse(messageEvent.data || '{}');
                    const item = normalizeRuntimeRoundEvent(raw);
                    if (!item) return;
                    applyIncomingEvents([item]);
                } catch {
                    // ignore malformed ws payload
                }
            };
        };

        const start = async () => {
            try {
                await syncRoundEvents();
            } catch {
                // ignore initial history sync failure and rely on ws reconnect
            }
            if (!cancelled && !wsClosedRef.current) {
                connectSocket();
            }
        };

        void start();
        return () => {
            cancelled = true;
            wsClosedRef.current = true;
            setWsConnected(false);
            closeSocket();
        };
    }, [
        activeConsoleStages,
        canManageLoops,
        clearEventsBuffer,
        ensureArtifactUrls,
        roundId,
        scheduleRoundMetaRefresh,
        setRoundArtifacts,
        setSteps,
        setTrainMetricPoints,
        token,
    ]);

    return {
        events,
        wsConnected,
        clearEventsBuffer,
    };
};
