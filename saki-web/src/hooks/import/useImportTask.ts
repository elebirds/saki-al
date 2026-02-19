import {useCallback, useMemo, useRef, useState} from 'react';
import {ImportProgressEvent, ImportTaskCreateResponse, ImportTaskState} from '../../types';
import {api} from '../../services/api';

interface UseImportTaskOptions {
    onEvent?: (event: ImportProgressEvent) => void;
    onComplete?: (events: ImportProgressEvent[]) => void;
    onError?: (error: string) => void;
}

const initialState: ImportTaskState = {
    taskId: undefined,
    lastSeq: 0,
    status: 'idle',
    events: [],
    phase: undefined,
    progress: {
        current: 0,
        total: 0,
    },
};

function makeInitialState(): ImportTaskState {
    return {
        ...initialState,
        events: [],
        progress: {...initialState.progress},
    };
}

function extractFailureMessage(event: ImportProgressEvent): string | null {
    const detail = event.detail || {};
    const failed = Boolean((detail as Record<string, unknown>).failed);
    if (!failed) return null;
    const detailError = (detail as Record<string, unknown>).error;
    if (typeof detailError === 'string' && detailError.trim()) {
        return detailError;
    }
    if (typeof event.message === 'string' && event.message.trim()) {
        return event.message;
    }
    return 'Import failed';
}

export function useImportTask(options: UseImportTaskOptions = {}) {
    const {onEvent, onComplete, onError} = options;
    const abortControllerRef = useRef<AbortController | null>(null);
    const eventsRef = useRef<ImportProgressEvent[]>([]);

    const [state, setState] = useState<ImportTaskState>(() => makeInitialState());

    const reset = useCallback(() => {
        eventsRef.current = [];
        setState(makeInitialState());
    }, []);

    const cancel = useCallback(() => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        setState((prev) => ({
            ...prev,
            status: 'error',
            error: 'Import cancelled',
        }));
    }, []);

    const pushEvent = useCallback((event: ImportProgressEvent) => {
        const normalizedEvent: ImportProgressEvent = {
            ...event,
            receivedAt: event.receivedAt || event.ts || new Date().toISOString(),
        };
        setState((prev) => {
            const nextEvents = [...prev.events, normalizedEvent];
            eventsRef.current = nextEvents;
            const nextState: ImportTaskState = {
                ...prev,
                events: nextEvents,
                progress: {...prev.progress},
            };

            if (typeof normalizedEvent.seq === 'number') {
                nextState.lastSeq = Math.max(Number(prev.lastSeq || 0), normalizedEvent.seq);
            }
            if (normalizedEvent.phase) nextState.phase = normalizedEvent.phase;
            if (typeof normalizedEvent.current === 'number') nextState.progress.current = normalizedEvent.current;
            if (typeof normalizedEvent.total === 'number') nextState.progress.total = normalizedEvent.total;

            if (normalizedEvent.event === 'start') {
                nextState.status = 'running';
                nextState.error = undefined;
            }
            if (normalizedEvent.event === 'complete') {
                const failureMessage = extractFailureMessage(normalizedEvent);
                if (failureMessage) {
                    nextState.status = 'error';
                    nextState.error = failureMessage;
                } else {
                    nextState.status = 'complete';
                }
            }

            return nextState;
        });
        onEvent?.(normalizedEvent);
    }, [onEvent]);

    const run = useCallback(async (
        executor: (signal?: AbortSignal) => Promise<ImportTaskCreateResponse>
    ) => {
        abortControllerRef.current = new AbortController();
        setState({
            ...makeInitialState(),
            status: 'running',
        });
        eventsRef.current = [];

        try {
            const task = await executor(abortControllerRef.current.signal);
            setState((prev) => ({
                ...prev,
                taskId: task.taskId,
            }));

            let cursor = 0;
            let retries = 0;
            while (true) {
                try {
                    await api.streamImportTaskEvents(
                        task.taskId,
                        cursor,
                        (event) => {
                            if (typeof event.seq === 'number') {
                                cursor = Math.max(cursor, event.seq);
                            }
                            pushEvent(event);
                        },
                        abortControllerRef.current?.signal,
                    );
                    break;
                } catch (error) {
                    if (error instanceof Error && error.name === 'AbortError') {
                        throw error;
                    }
                    retries += 1;
                    if (retries > 3) {
                        throw error;
                    }
                    await new Promise((resolve) => setTimeout(resolve, 1000 * retries));
                }
            }

            try {
                const latest = await api.getImportTaskStatus(task.taskId);
                if (latest.status === 'failed' || latest.status === 'canceled') {
                    const failureMessage = latest.error || 'Import failed';
                    setState((prev) => ({
                        ...prev,
                        status: 'error',
                        error: failureMessage,
                    }));
                    onError?.(failureMessage);
                    return;
                }
            } catch {
                // Ignore status polling failure and trust streamed events.
            }

            setState((prev) => {
                if (prev.status === 'error') return prev;
                return {
                    ...prev,
                    status: 'complete',
                };
            });

            onComplete?.(eventsRef.current);
        } catch (error) {
            if (error instanceof Error && error.name === 'AbortError') {
                return;
            }
            const errorMessage = error instanceof Error ? error.message : 'Import failed';
            setState((prev) => ({
                ...prev,
                status: 'error',
                error: errorMessage,
            }));
            onError?.(errorMessage);
        }
    }, [onComplete, onError, pushEvent]);

    const issues = useMemo(() => {
        return state.events.filter((event) => event.event === 'error' || event.event === 'warning');
    }, [state.events]);

    return {
        state,
        run,
        cancel,
        reset,
        issues,
        isRunning: state.status === 'running',
        isComplete: state.status === 'complete',
        isError: state.status === 'error',
    };
}

export default useImportTask;
