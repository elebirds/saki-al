import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    App,
    Alert,
    Button,
    Card,
    Collapse,
    Descriptions,
    Divider,
    Dropdown,
    Empty,
    Form,
    Input,
    Modal,
    Popconfirm,
    Progress,
    Select,
    Slider,
    Statistic,
    Spin,
    Table,
    Tag,
    Typography,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {useAuthStore} from '../../../store/authStore';
import RoundConsolePanel from './components/RoundConsolePanel';
import {
    getMetricBySource,
    getSummaryMetricsBySource,
    normalizeFinalMetricSource,
    pickPreviewMetric,
} from './runtimeMetricView';
import {ROUND_WS_RECONNECT_DELAYS, buildRoundEventsWsUrl} from './runtimeRoundWs';
import {formatDateTime} from './runtimeTime';
import {isLoopDeletable} from './loopLifecycle';
import {resolvePredictionTargetModel} from './predictionModelSelection';
import {
    Loop,
    LoopSnapshotRead,
    LoopGateResponse,
    RoundSelectionRead,
    SnapshotInitRequest,
    SnapshotUpdateRequest,
    LoopSummary,
    RuntimeRound,
    RuntimeRoundEvent,
    PredictionRead,
} from '../../../types';
import {mergeRuntimeRoundEvents, normalizeRuntimeRoundEvent} from './runtimeEventFormatter';

const {Title, Text} = Typography;

const LOOP_LIFECYCLE_COLOR: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    stopping: 'warning',
    stopped: 'default',
    completed: 'success',
    failed: 'error',
};

const ROUND_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    completed: 'success',
    failed: 'error',
    cancelled: 'warning',
};

const LOOP_GATE_COLOR: Record<string, string> = {
    need_snapshot: 'default',
    need_labels: 'warning',
    can_start: 'processing',
    running: 'processing',
    paused: 'warning',
    stopping: 'warning',
    need_round_labels: 'warning',
    can_confirm: 'success',
    can_next_round: 'processing',
    can_retry: 'error',
    completed: 'success',
    stopped: 'default',
    failed: 'error',
};

const MANIFEST_LABEL: Record<string, string> = {
    train_seed: 'TRAIN_SEED',
    train_pool: 'TRAIN_POOL',
    val_anchor: 'VAL_ANCHOR',
    val_batch: 'VAL_BATCH',
    test_anchor: 'TEST_ANCHOR',
    test_batch: 'TEST_BATCH',
};

const PRIMARY_VIEW_LABEL: Record<string, string> = {
    train: 'Train',
    pool: 'Pool',
    val: 'Val',
    test: 'Test',
};

const PRIMARY_VIEW_DESC: Record<string, string> = {
    train: '当前可训练集合',
    pool: '候选池（隐藏标签）',
    val: '当前有效验证集',
    test: 'Anchor Test（固定口径）',
};

const PRIMARY_VIEW_COLOR: Record<string, string> = {
    train: '#1f9d55',
    pool: '#d89c00',
    val: '#1677ff',
    test: '#13a8a8',
};

const FINAL_METRIC_SOURCE_LABEL: Record<'eval' | 'train' | 'other' | 'none', string> = {
    eval: 'Eval(Test)',
    train: 'Train',
    other: 'Other Step',
    none: 'None',
};

const FALLBACK_POLL_MS = 30000;
const WS_REFRESH_THROTTLE_MS = 5000;
const MAX_CONSOLE_EVENT_BUFFER = 20000;

const shouldRefreshLoopByRoundEvent = (raw: unknown): boolean => {
    if (!raw || typeof raw !== 'object') return false;
    const row = raw as Record<string, unknown>;
    const eventType = String(row.eventType ?? row.event_type ?? '').trim().toLowerCase();
    return eventType === 'status' || eventType === 'artifact';
};

const SNAPSHOT_INIT_DEFAULTS: SnapshotInitRequest = {
    trainSeedRatio: 0.05,
    valRatio: 0.1,
    testRatio: 0.1,
    valPolicy: 'anchor_only',
};

const SNAPSHOT_UPDATE_DEFAULTS: SnapshotUpdateRequest = {
    mode: 'append_all_to_pool',
    batchTestRatio: 0.1,
    batchValRatio: 0.1,
};

const buildRoundProgressSummary = (round: RuntimeRound): { percent: number; text: string } => {
    const counts = round.stepCounts || {};
    const total = Object.values(counts).reduce((sum, item) => sum + Number(item || 0), 0);
    if (!total) return {percent: 0, text: '0/0'};
    const done = ['succeeded', 'failed', 'cancelled', 'skipped']
        .reduce((sum, key) => sum + Number((counts as Record<string, number>)[key] || 0), 0);
    const running = Number((counts as Record<string, number>).running || 0)
        + Number((counts as Record<string, number>).binding_device || 0)
        + Number((counts as Record<string, number>).probing_runtime || 0)
        + Number((counts as Record<string, number>).syncing_env || 0)
        + Number((counts as Record<string, number>).dispatching || 0)
        + Number((counts as Record<string, number>).retrying || 0);
    const percent = Math.max(0, Math.min(100, Number(((done / total) * 100).toFixed(2))));
    return {percent, text: `${done}/${total} 完成 · ${running} 运行中`};
};

const formatGateHint = (gateInfo: LoopGateResponse | null): string => {
    if (!gateInfo) return '暂无 Gate 决策信息。';
    const gate = gateInfo.gate;
    const meta = gateInfo.gateMeta || {};
    const num = (...keys: string[]): number => {
        for (const key of keys) {
            if (meta[key] !== undefined && meta[key] !== null) {
                return Number(meta[key] || 0);
            }
        }
        return 0;
    };
    if (gate === 'need_snapshot') return '需要先初始化 Snapshot，才能开始当前循环。';
    if (gate === 'need_labels') return `Round 0 就绪未完成，仍缺 ${num('gapCount', 'gap_count')} 个标注。`;
    if (gate === 'need_round_labels') {
        return `本轮 Query 仍需补标：缺失 ${num('missingCount', 'missing_count')} / 已选 ${num('selectedCount', 'selected_count')}（达标 ${num('revealedCount', 'revealed_count')}/${num('minRequired', 'min_required')}）。`;
    }
    if (gate === 'can_confirm') {
        return `本轮已满足确认条件（${num('revealedCount', 'revealed_count')}/${num('minRequired', 'min_required')}），可执行 Confirm Reveal。`;
    }
    if (gate === 'can_next_round') return '本轮已确认，可启动下一轮。';
    if (gate === 'can_retry') return '最新失败轮可重试。';
    if (gate === 'running') return '当前 Loop 正在执行中。';
    if (gate === 'paused') return '当前 Loop 已暂停，可恢复。';
    if (gate === 'stopping') return '当前 Loop 正在停止中，请等待收敛。';
    if (gate === 'completed') return 'Loop 已完成。';
    if (gate === 'stopped') return 'Loop 已停止（终态，不可重启）。';
    if (gate === 'failed') return 'Loop 已失败，请查看失败轮详情。';
    return `当前 Gate：${gate}`;
};

const ProjectLoopDetail: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const {message: messageApi} = App.useApp();
    const token = useAuthStore((state) => state.token);
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');
    const [loading, setLoading] = useState(true);
    const [controlLoading, setControlLoading] = useState(false);
    const [deleteLoading, setDeleteLoading] = useState(false);
    const [cleaningRound, setCleaningRound] = useState<number | null>(null);
    const [loop, setLoop] = useState<Loop | null>(null);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [rounds, setRounds] = useState<RuntimeRound[]>([]);
    const [gateInfo, setGateInfo] = useState<LoopGateResponse | null>(null);
    const [snapshotInfo, setSnapshotInfo] = useState<LoopSnapshotRead | null>(null);
    const [predictions, setPredictions] = useState<PredictionRead[]>([]);
    const [predictionLoading, setPredictionLoading] = useState(false);
    const [predictionSubmitting, setPredictionSubmitting] = useState(false);
    const [applyingPredictionId, setApplyingPredictionId] = useState<string>('');
    const [predictionScopeOpen, setPredictionScopeOpen] = useState(false);
    const [predictionScopeStatus, setPredictionScopeStatus] = useState<'all' | 'unlabeled' | 'labeled' | 'draft'>('all');
    const [snapshotInitOpen, setSnapshotInitOpen] = useState(false);
    const [snapshotUpdateOpen, setSnapshotUpdateOpen] = useState(false);
    const [selectionAdjustOpen, setSelectionAdjustOpen] = useState(false);
    const [selectionLoading, setSelectionLoading] = useState(false);
    const [selectionSubmitting, setSelectionSubmitting] = useState(false);
    const [selectionData, setSelectionData] = useState<RoundSelectionRead | null>(null);
    const [selectionRoundId, setSelectionRoundId] = useState<string>('');
    const [snapshotSubmitting, setSnapshotSubmitting] = useState(false);
    const [wsConnected, setWsConnected] = useState(false);
    const [latestRoundConsoleEvents, setLatestRoundConsoleEvents] = useState<RuntimeRoundEvent[]>([]);
    const [isPageVisible, setIsPageVisible] = useState<boolean>(() => {
        if (typeof document === 'undefined') return true;
        return document.visibilityState !== 'hidden';
    });
    const [initForm] = Form.useForm<SnapshotInitRequest & { sampleIdsText?: string }>();
    const [updateForm] = Form.useForm<SnapshotUpdateRequest & { sampleIdsText?: string }>();
    const [selectionForm] = Form.useForm<{
        includeSampleIdsText?: string;
        excludeSampleIdsText?: string;
        reason?: string;
    }>();
    const wsCursorRef = useRef<string | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const wsRetryTimerRef = useRef<number | null>(null);
    const wsRetryCountRef = useRef<number>(0);
    const wsClosedRef = useRef<boolean>(false);
    const wsLastRefreshAtRef = useRef<number>(0);
    const wsRefreshInFlightRef = useRef<boolean>(false);
    const latestRoundConsoleEventsRef = useRef<RuntimeRoundEvent[]>([]);
    const updateMode = Form.useWatch('mode', updateForm);
    const latestRound = useMemo(() => {
        if (!rounds || rounds.length === 0) return null;
        return [...rounds].sort((left, right) => {
            if (Number(left.roundIndex || 0) !== Number(right.roundIndex || 0)) {
                return Number(right.roundIndex || 0) - Number(left.roundIndex || 0);
            }
            return Number(right.attemptIndex || 0) - Number(left.attemptIndex || 0);
        })[0] || null;
    }, [rounds]);

    const summaryTrainMetricPreview = useMemo(
        () => pickPreviewMetric(getSummaryMetricsBySource(summary, 'train')),
        [summary],
    );
    const summaryEvalMetricPreview = useMemo(
        () => pickPreviewMetric(getSummaryMetricsBySource(summary, 'eval')),
        [summary],
    );
    const summaryFinalMetricPreview = useMemo(
        () => pickPreviewMetric(getSummaryMetricsBySource(summary, 'final')),
        [summary],
    );
    const summaryFinalMetricSource = useMemo(
        () => normalizeFinalMetricSource(summary?.metricsLatestSource),
        [summary?.metricsLatestSource],
    );

    useEffect(() => {
        latestRoundConsoleEventsRef.current = latestRoundConsoleEvents;
    }, [latestRoundConsoleEvents]);

    useEffect(() => {
        latestRoundConsoleEventsRef.current = [];
        setLatestRoundConsoleEvents([]);
    }, [latestRound?.id]);

    const refreshLoopData = useCallback(async () => {
        if (!loopId || !projectId) return;
        const [loopRow, summaryRow, roundRows] = await Promise.all([
            api.getLoopById(loopId),
            api.getLoopSummary(loopId),
            api.getLoopRounds(loopId, 100),
        ]);
        setLoop(loopRow);
        setSummary(summaryRow);
        setRounds(roundRows);
        const gateRow = await api.getLoopGate(loopId).catch(() => null);
        setGateInfo(gateRow);
        if (loopRow.mode === 'active_learning' || loopRow.mode === 'simulation') {
            const snapshotRow = await api.getLoopSnapshot(loopId).catch(() => null);
            setSnapshotInfo(snapshotRow);
        } else {
            setSnapshotInfo(null);
        }
        const predictionRows = await api.listPredictions(projectId, 50).catch(() => []);
        setPredictions(predictionRows);
    }, [loopId, projectId]);

    const loadData = useCallback(async () => {
        if (!canManageLoops) return;
        setLoading(true);
        try {
            await refreshLoopData();
        } catch (error: any) {
            messageApi.error(error?.message || '加载 Loop 详情失败');
        } finally {
            setLoading(false);
        }
    }, [refreshLoopData, canManageLoops]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

    useEffect(() => {
        if (typeof document === 'undefined') return;
        const onVisibilityChange = () => setIsPageVisible(document.visibilityState !== 'hidden');
        document.addEventListener('visibilitychange', onVisibilityChange);
        return () => document.removeEventListener('visibilitychange', onVisibilityChange);
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
        const latestRoundId = latestRound?.id;
        if (!canManageLoops || !loopId) return;
        if (latestRoundId && wsConnected) return;
        const timer = window.setInterval(() => {
            void refreshLoopData().catch(() => undefined);
        }, FALLBACK_POLL_MS);
        return () => window.clearInterval(timer);
    }, [canManageLoops, loopId, latestRound?.id, wsConnected, refreshLoopData]);

    useEffect(() => {
        const latestRoundId = latestRound?.id;
        if (!canManageLoops || !latestRoundId || !token) {
            setWsConnected(false);
            wsCursorRef.current = null;
            wsRetryCountRef.current = 0;
            latestRoundConsoleEventsRef.current = [];
            setLatestRoundConsoleEvents([]);
            return;
        }
        let cancelled = false;

        wsClosedRef.current = false;
        wsRetryCountRef.current = 0;
        wsCursorRef.current = null;
        latestRoundConsoleEventsRef.current = [];
        setLatestRoundConsoleEvents([]);

        const triggerRefresh = () => {
            if (!isPageVisible) return;
            const now = Date.now();
            if (wsRefreshInFlightRef.current) return;
            if (now - wsLastRefreshAtRef.current < WS_REFRESH_THROTTLE_MS) return;
            wsLastRefreshAtRef.current = now;
            wsRefreshInFlightRef.current = true;
            void refreshLoopData()
                .catch(() => undefined)
                .finally(() => {
                    wsRefreshInFlightRef.current = false;
                });
        };

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

        const syncRoundCursor = async () => {
            const response = await api.getRoundEvents(latestRoundId, {
                afterCursor: wsCursorRef.current || undefined,
                limit: 5000,
            });
            if (cancelled) return;
            wsCursorRef.current = response.nextAfterCursor ?? wsCursorRef.current;
            const incoming = (response.items || []).filter((item) => Boolean(item.taskId));
            if (incoming.length > 0) {
                const merged = mergeRuntimeRoundEvents(
                    latestRoundConsoleEventsRef.current,
                    incoming,
                    MAX_CONSOLE_EVENT_BUFFER,
                );
                latestRoundConsoleEventsRef.current = merged;
                setLatestRoundConsoleEvents(merged);
            }
            if (incoming.some((item) => shouldRefreshLoopByRoundEvent(item))) {
                triggerRefresh();
            }
        };

        const scheduleReconnect = () => {
            if (cancelled || wsClosedRef.current) return;
            const retry = wsRetryCountRef.current + 1;
            wsRetryCountRef.current = retry;
            const delay = ROUND_WS_RECONNECT_DELAYS[Math.min(retry - 1, ROUND_WS_RECONNECT_DELAYS.length - 1)];
            wsRetryTimerRef.current = window.setTimeout(async () => {
                wsRetryTimerRef.current = null;
                if (cancelled || wsClosedRef.current) return;
                if (retry >= 3) {
                    try {
                        await syncRoundCursor();
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
            const ws = new WebSocket(buildRoundEventsWsUrl(latestRoundId, token, {
                afterCursor: wsCursorRef.current || undefined,
            }));
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
            ws.onmessage = (event: MessageEvent<string>) => {
                try {
                    const parsed = JSON.parse(event.data || '{}') as unknown;
                    const normalized = normalizeRuntimeRoundEvent(parsed);
                    if (!normalized) return;
                    const merged = mergeRuntimeRoundEvents(
                        latestRoundConsoleEventsRef.current,
                        [normalized],
                        MAX_CONSOLE_EVENT_BUFFER,
                    );
                    latestRoundConsoleEventsRef.current = merged;
                    setLatestRoundConsoleEvents(merged);
                    if (shouldRefreshLoopByRoundEvent(normalized)) {
                        triggerRefresh();
                    }
                } catch {
                    // ignore malformed ws payload
                }
            };
        };

        const start = async () => {
            try {
                await syncRoundCursor();
            } catch {
                // ignore initial catch-up failure and rely on ws reconnect
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
    }, [canManageLoops, token, latestRound?.id, refreshLoopData, isPageVisible]);

    const executeLoopAction = useCallback(
        async (
            action?: string,
            payload: Record<string, any> = {},
            opts: { force?: boolean; refresh?: boolean } = {},
        ) => {
            if (!loopId) return null;
            setControlLoading(true);
            try {
                const submit = async (decisionToken?: string) => {
                    return await api.actLoop(loopId, {
                        action: action as any,
                        force: Boolean(opts.force),
                        decisionToken,
                        payload,
                    });
                };
                const isDecisionTokenStale = (error: any): boolean => {
                    const statusCode = Number(
                        error?.statusCode
                        ?? error?.originalError?.response?.status
                        ?? error?.response?.status
                        ?? 0,
                    );
                    const messageText = String(error?.message || '').toLowerCase();
                    return statusCode === 409 && messageText.includes('decision token is stale');
                };
                let result;
                try {
                    result = await submit(gateInfo?.decisionToken || undefined);
                } catch (error: any) {
                    if (!isDecisionTokenStale(error)) {
                        throw error;
                    }
                    const latestGate = await api.getLoopGate(loopId).catch(() => null);
                    if (!latestGate?.decisionToken) {
                        throw error;
                    }
                    setGateInfo(latestGate);
                    result = await submit(latestGate.decisionToken);
                }
                setGateInfo({
                    loopId: result.loopId,
                    gate: result.gate,
                    gateMeta: result.gateMeta || {},
                    primaryAction: result.primaryAction || null,
                    actions: result.actions || [],
                    decisionToken: result.decisionToken || '',
                    blockingReasons: result.blockingReasons || [],
                });
                const actionKeys = new Set((result.actions || []).map((item) => item.key));
                if (actionKeys.has('snapshot_init')) {
                    initForm.resetFields();
                    initForm.setFieldsValue(SNAPSHOT_INIT_DEFAULTS);
                    setSnapshotInitOpen(true);
                }
                if (result.executedAction) {
                    messageApi.success(result.message || `已执行 ${result.executedAction}`);
                } else {
                    messageApi.info(result.message || `当前网关无需执行：${result.gate}`);
                }
                if (opts.refresh !== false) {
                    await refreshLoopData();
                }
                return result;
            } catch (error: any) {
                messageApi.error(error?.message || 'Loop 动作执行失败');
                return null;
            } finally {
                setControlLoading(false);
            }
        },
        [loopId, gateInfo?.decisionToken, loop?.mode, refreshLoopData, messageApi],
    );

    const handleCleanupRoundPredictions = async (roundIndex: number) => {
        if (!loopId) return;
        setCleaningRound(roundIndex);
        try {
            const response = await api.cleanupRoundPredictions(loopId, roundIndex);
            messageApi.success(
                `已清理 Round ${roundIndex}：score-steps=${response.scoreSteps}，候选=${response.candidateRowsDeleted}，事件=${response.eventRowsDeleted}，指标=${response.metricRowsDeleted}`
            );
            await refreshLoopData();
        } catch (error: any) {
            messageApi.error(error?.message || '清理 Round 预测数据失败');
        } finally {
            setCleaningRound(null);
        }
    };

    const handleDeleteLoop = useCallback(async () => {
        if (!loopId || !projectId || !loop) return;
        if (!isLoopDeletable(loop.lifecycle)) {
            messageApi.warning(`当前生命周期 ${loop.lifecycle} 不允许删除`);
            return;
        }
        setDeleteLoading(true);
        try {
            await api.deleteLoop(loopId);
            messageApi.success('Loop 已删除');
            navigate(`/projects/${projectId}/loops`);
        } catch (error: any) {
            messageApi.error(error?.message || '删除 Loop 失败');
        } finally {
            setDeleteLoading(false);
        }
    }, [loopId, projectId, loop, messageApi, navigate]);

    const refreshPredictions = useCallback(async () => {
        if (!loopId || !projectId) return;
        setPredictionLoading(true);
        try {
            const rows = await api.listPredictions(projectId, 50);
            setPredictions(rows);
        } catch (error: any) {
            messageApi.error(error?.message || '加载 Prediction 失败');
        } finally {
            setPredictionLoading(false);
        }
    }, [loopId, projectId, messageApi]);

    const handleGeneratePrediction = useCallback(async (status: 'all' | 'unlabeled' | 'labeled' | 'draft') => {
        if (!loopId || !projectId) return;
        const targetRoundId = latestRound?.id;
        if (!targetRoundId || !loop) {
            messageApi.warning('当前没有可用 round 生成 Prediction');
            return;
        }
        const pluginId = String(latestRound?.pluginId || loop.modelArch || '').trim();
        if (!pluginId) {
            messageApi.warning('当前 round 缺少 plugin 信息，无法创建任务');
            return;
        }
        let targetModel = null;
        const latestModelId = String(loop.latestModelId || '').trim();
        if (latestModelId) {
            targetModel = await api.getModel(latestModelId).catch(() => null);
        }
        if (!targetModel) {
            const roundModels = await api.getProjectModels(projectId, {
                limit: 100,
                roundId: targetRoundId,
            }).catch(() => []);
            targetModel = resolvePredictionTargetModel(loop, latestRound, roundModels);
        }
        if (!targetModel) {
            const pluginModels = await api.getProjectModels(projectId, {
                limit: 100,
                pluginId,
            }).catch(() => []);
            targetModel = resolvePredictionTargetModel(loop, latestRound, pluginModels);
        }
        if (!targetModel?.id) {
            messageApi.warning('当前项目缺少可用模型，请先发布模型再创建 Prediction');
            return;
        }
        const branches = await api.getProjectBranches(projectId).catch(() => []);
        const targetBranch = branches.find((item) => item.id === loop.branchId);
        if (!targetBranch?.headCommitId) {
            messageApi.warning('无法解析目标分支或基线 Commit');
            return;
        }
        setPredictionSubmitting(true);
        try {
            const row = await api.createPrediction(projectId, {
                modelId: targetModel.id,
                artifactName: 'best.pt',
                targetBranchId: loop.branchId,
                baseCommitId: targetBranch.headCommitId,
                scopeType: 'sample_status',
                scopePayload: {status},
            });
            messageApi.success(`Prediction 已生成：${row.id}`);
            await refreshPredictions();
            setPredictionScopeOpen(false);
        } catch (error: any) {
            messageApi.error(error?.message || '生成 Prediction 失败');
        } finally {
            setPredictionSubmitting(false);
        }
    }, [loopId, projectId, latestRound?.id, latestRound?.pluginId, loop, refreshPredictions, messageApi]);

    const handleApplyPrediction = useCallback(async (predictionId: string) => {
        if (!predictionId) return;
        setApplyingPredictionId(predictionId);
        try {
            const result = await api.applyPrediction(predictionId, {});
            messageApi.success(`已应用到 Draft：${result.appliedCount} 条`);
            await refreshPredictions();
        } catch (error: any) {
            messageApi.error(error?.message || '应用 Prediction 失败');
        } finally {
            setApplyingPredictionId('');
        }
    }, [refreshPredictions, messageApi]);

    const parseSampleIds = (raw?: string): string[] | undefined => {
        const text = String(raw || '').trim();
        if (!text) return undefined;
        const rows = text
            .split(/[\n,]+/g)
            .map((item) => item.trim())
            .filter((item) => !!item);
        return rows.length > 0 ? rows : undefined;
    };

    const loadRoundSelection = useCallback(
        async (roundId: string) => {
            setSelectionLoading(true);
            try {
                const row = await api.getRoundSelection(roundId);
                setSelectionData(row);
                const includeIds = row.overrides.filter((item) => item.op === 'include').map((item) => item.sampleId);
                const excludeIds = row.overrides.filter((item) => item.op === 'exclude').map((item) => item.sampleId);
                selectionForm.setFieldsValue({
                    includeSampleIdsText: includeIds.join('\n'),
                    excludeSampleIdsText: excludeIds.join('\n'),
                });
            } catch (error: any) {
                messageApi.error(error?.message || '加载 TopK 调整信息失败');
            } finally {
                setSelectionLoading(false);
            }
        },
        [selectionForm, messageApi],
    );

    const handleInitSnapshot = async () => {
        if (!loopId) return;
        try {
            const values = await initForm.validateFields();
            setSnapshotSubmitting(true);
            const payload: SnapshotInitRequest = {
                trainSeedRatio: values.trainSeedRatio,
                valRatio: values.valRatio,
                testRatio: values.testRatio,
                valPolicy: values.valPolicy,
                sampleIds: parseSampleIds((values as any).sampleIdsText),
            };
            await executeLoopAction('snapshot_init', payload, {refresh: true});
            messageApi.success('Snapshot 初始化成功');
            setSnapshotInitOpen(false);
            initForm.resetFields();
        } catch (error: any) {
            if (error?.errorFields) return;
            messageApi.error(error?.message || 'Snapshot 初始化失败');
        } finally {
            setSnapshotSubmitting(false);
        }
    };

    const handleUpdateSnapshot = async () => {
        if (!loopId) return;
        try {
            const values = await updateForm.validateFields();
            setSnapshotSubmitting(true);
            const payload: SnapshotUpdateRequest = {
                mode: values.mode,
                batchTestRatio: values.batchTestRatio,
                batchValRatio: values.batchValRatio,
                valPolicy: values.valPolicy,
                sampleIds: parseSampleIds((values as any).sampleIdsText),
            };
            await executeLoopAction('snapshot_update', payload, {refresh: true});
            messageApi.success('Snapshot 更新成功');
            setSnapshotUpdateOpen(false);
            updateForm.resetFields();
        } catch (error: any) {
            if (error?.errorFields) return;
            messageApi.error(error?.message || 'Snapshot 更新失败');
        } finally {
            setSnapshotSubmitting(false);
        }
    };

    const openSnapshotInitModal = () => {
        initForm.resetFields();
        initForm.setFieldsValue(SNAPSHOT_INIT_DEFAULTS);
        setSnapshotInitOpen(true);
    };

    const openSnapshotUpdateModal = () => {
        updateForm.resetFields();
        updateForm.setFieldsValue(SNAPSHOT_UPDATE_DEFAULTS);
        setSnapshotUpdateOpen(true);
    };

    const openSelectionAdjustModal = async () => {
        const latestRoundId = latestRound?.id;
        if (!latestRoundId) {
            messageApi.warning('当前没有可调整的 round');
            return;
        }
        setSelectionRoundId(latestRoundId);
        setSelectionData(null);
        selectionForm.resetFields();
        setSelectionAdjustOpen(true);
        await loadRoundSelection(latestRoundId);
    };

    const handleApplySelectionAdjust = async () => {
        if (!selectionRoundId) return;
        try {
            const values = await selectionForm.validateFields();
            setSelectionSubmitting(true);
            const includeSampleIds = parseSampleIds(values.includeSampleIdsText) || [];
            const excludeSampleIds = parseSampleIds(values.excludeSampleIdsText) || [];
            const result = await api.applyRoundSelection(selectionRoundId, {
                includeSampleIds,
                excludeSampleIds,
                reason: String(values.reason || '').trim() || undefined,
            });
            messageApi.success(
                `TopK 已更新：selected=${result.selectedCount}, include=${result.includeCount}, exclude=${result.excludeCount}`,
            );
            await loadRoundSelection(selectionRoundId);
            await refreshLoopData();
        } catch (error: any) {
            if (error?.errorFields) return;
            messageApi.error(error?.message || '应用 TopK 调整失败');
        } finally {
            setSelectionSubmitting(false);
        }
    };

    const handleResetSelectionAdjust = async () => {
        if (!selectionRoundId) return;
        setSelectionSubmitting(true);
        try {
            await api.resetRoundSelection(selectionRoundId);
            messageApi.success('TopK 调整已重置');
            await loadRoundSelection(selectionRoundId);
            await refreshLoopData();
        } catch (error: any) {
            messageApi.error(error?.message || '重置 TopK 调整失败');
        } finally {
            setSelectionSubmitting(false);
        }
    };

    const primaryAction = gateInfo?.primaryAction || null;

    const navigateToScopedAnnotate = async (actionPayload?: Record<string, any>) => {
        const meta = (gateInfo?.gateMeta as Record<string, any> | undefined) || {};
        const scope = (meta.annotationScope as Record<string, any> | undefined) || {};
        const payloadScope = (actionPayload?.annotationScope as Record<string, any> | undefined) || {};
        const roundId = String(
            payloadScope.roundId
            || payloadScope.round_id
            || scope.roundId
            || scope.round_id
            || actionPayload?.roundId
            || actionPayload?.round_id
            || meta.roundId
            || meta.round_id
            || '',
        );
        if (!projectId || !loopId || !roundId) {
            messageApi.warning('当前 Gate 未提供可标注的 Round 范围');
            return;
        }
        let branchName = 'master';
        if (loop?.branchId) {
            try {
                const branches = await api.getProjectBranches(projectId);
                const hit = branches.find((item) => item.id === loop.branchId);
                if (hit?.name) {
                    branchName = hit.name;
                }
            } catch {
                // ignore branch resolve errors and fallback to master
            }
        }
        const next = new URLSearchParams();
        next.set('branch', branchName);
        next.set('status', 'all');
        next.set('sort', 'createdAt:desc');
        next.set('page', '1');
        next.set('pageSize', '24');
        next.set('runtimeScope', 'round_missing_labels');
        next.set('runtimeLoopId', loopId);
        next.set('runtimeRoundId', roundId);
        next.set('runtimeBranchName', branchName);
        navigate(`/projects/${projectId}/samples?${next.toString()}`);
    };

    const handleContinue = async () => {
        if (primaryAction?.key === 'snapshot_init') {
            openSnapshotInitModal();
            return;
        }
        if (primaryAction?.key === 'snapshot_update') {
            openSnapshotUpdateModal();
            return;
        }
        if (primaryAction?.key === 'selection_adjust') {
            await openSelectionAdjustModal();
            return;
        }
        if (primaryAction?.key === 'annotate') {
            await navigateToScopedAnnotate(primaryAction.payload || {});
            return;
        }
        await executeLoopAction(primaryAction?.key || undefined);
    };

    const continueLabel = primaryAction ? `Continue · ${primaryAction.label}` : 'Continue';
    const continueDisabled = !primaryAction || !primaryAction.runnable;
    const canDeleteLoop = Boolean(loop && isLoopDeletable(loop.lifecycle));
    const advancedActionItems = (gateInfo?.actions || [])
        .filter((item) => item.key !== primaryAction?.key)
        .map((item) => ({
            key: item.key,
            label: item.label,
            disabled: !item.runnable,
            onClick: () => {
                if (item.key === 'snapshot_init') {
                    openSnapshotInitModal();
                    return;
                }
                if (item.key === 'snapshot_update') {
                    openSnapshotUpdateModal();
                    return;
                }
                if (item.key === 'selection_adjust') {
                    void openSelectionAdjustModal();
                    return;
                }
                if (item.key === 'annotate') {
                    void navigateToScopedAnnotate(item.payload || {});
                    return;
                }
                void executeLoopAction(item.key);
            },
            danger: item.key === 'stop',
        }));

    const primaryView = snapshotInfo?.primaryView || {
        train: {count: 0, semantics: 'effective_train' as const},
        pool: {count: 0, semantics: 'hidden_label_pool' as const},
        val: {count: 0, semantics: 'effective_val' as const},
        test: {count: 0, semantics: 'anchor_test' as const},
    };

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!canManageLoops) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" showIcon message="暂无权限访问 Loop 页面"/>
            </Card>
        );
    }

    if (!loop) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="Loop 不存在或无权限访问"/>
            </Card>
        );
    }
    const loopExecutionConfig = (loop.config?.execution || {}) as Record<string, any>;
    const preferredExecutorId = String(
        loopExecutionConfig.preferredExecutorId || loopExecutionConfig.preferred_executor_id || '',
    ).trim();

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>返回概览</Button>
                            <Title level={4} className="!mb-0">{loop.name}</Title>
                            <Tag color={LOOP_LIFECYCLE_COLOR[loop.lifecycle] || 'default'}>{loop.lifecycle}</Tag>
                            <Tag>{loop.phase}</Tag>
                            <Tag color={wsConnected ? 'success' : 'default'}>
                                {wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'}
                            </Tag>
                        </div>
                        <Text type="secondary">Loop ID: {loop.id}</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/config`)}>
                            配置
                        </Button>
                        <Button onClick={() => navigate('/runtime/executors')}>执行器状态</Button>
                        <Button
                            type="primary"
                            loading={controlLoading}
                            onClick={handleContinue}
                            disabled={continueDisabled}
                        >
                            {continueLabel}
                        </Button>
                        <Dropdown
                            menu={{
                                items: advancedActionItems.map((item) => ({
                                    key: item.key,
                                    label: item.label,
                                    disabled: item.disabled,
                                    danger: item.danger,
                                })),
                                onClick: ({key}) => {
                                    const match = advancedActionItems.find((item) => item.key === key);
                                    if (match && !match.disabled) {
                                        match.onClick();
                                    }
                                },
                            }}
                            trigger={['click']}
                        >
                            <Button>高级操作</Button>
                        </Dropdown>
                        <Popconfirm
                            title="删除当前 Loop？"
                            description="该操作不可恢复，会清理该 Loop 的运行时派生数据。"
                            okText="确认删除"
                            cancelText="取消"
                            okButtonProps={{danger: true, loading: deleteLoading}}
                            onConfirm={() => void handleDeleteLoop()}
                            disabled={!canDeleteLoop || deleteLoading}
                        >
                            <Button danger loading={deleteLoading} disabled={!canDeleteLoop}>
                                删除 Loop
                            </Button>
                        </Popconfirm>
                    </div>
                </div>
            </Card>

            {latestRound ? (
                <RoundConsolePanel
                    className="!border-github-border !bg-github-panel"
                    title={`最新 Round 动态控制台 · #${latestRound.roundIndex} / A${latestRound.attemptIndex || 1}`}
                    wsConnected={wsConnected}
                    events={latestRoundConsoleEvents}
                    onClearBuffer={() => {
                        latestRoundConsoleEventsRef.current = [];
                        setLatestRoundConsoleEvents([]);
                    }}
                    emptyDescription="最新 Round 暂无日志"
                    exportFilePrefix={`loop-${loop.id}-latest-round-${latestRound.roundIndex}`}
                />
            ) : (
                <Card className="!border-github-border !bg-github-panel" title="最新 Round 动态控制台">
                    <Empty description="当前暂无 Round，无法展示实时控制台"/>
                </Card>
            )}

            <Card className="!border-github-border !bg-github-panel" title="Loop 摘要">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="模式">{loop.mode}</Descriptions.Item>
                    <Descriptions.Item label="Gate">
                        {loop.gate ? <Tag color={LOOP_GATE_COLOR[loop.gate] || 'default'}>{loop.gate}</Tag> : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="绑定 Executor">{preferredExecutorId || '自动调度'}</Descriptions.Item>
                    <Descriptions.Item label="Rounds 总数">{summary?.roundsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Attempts 总数">{summary?.attemptsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Rounds 成功">{summary?.roundsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 总数">{summary?.stepsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 成功">{summary?.stepsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="最新 Train 终态">{summaryTrainMetricPreview}</Descriptions.Item>
                    <Descriptions.Item label="最新 Eval(Test)">{summaryEvalMetricPreview}</Descriptions.Item>
                    <Descriptions.Item label="最新 Final(对外)">
                        <div className="flex items-center gap-2">
                            <Tag color={summaryFinalMetricSource === 'eval' ? 'blue' : (summaryFinalMetricSource === 'train' ? 'green' : 'default')}>
                                {`source: ${FINAL_METRIC_SOURCE_LABEL[summaryFinalMetricSource]}`}
                            </Tag>
                            <span>{summaryFinalMetricPreview}</span>
                        </div>
                    </Descriptions.Item>
                </Descriptions>
                {preferredExecutorId ? (
                    <Alert
                        className="!mt-3"
                        type="info"
                        showIcon
                        message={`已固定绑定 Executor: ${preferredExecutorId}`}
                        description="严格绑定：该 Executor 不可用时，DISPATCHABLE 步骤会保持 READY 等待，不会自动回退到其他机器。"
                    />
                ) : null}
            </Card>

            {loop.mode === 'active_learning' ? (
                <Card className="!border-github-border !bg-github-panel" title="Active Learning 面板">
                    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_1fr]">
                        <div className="flex flex-col gap-3 rounded-lg border border-github-border/80 bg-github-bg p-4">
                            <div className="flex flex-wrap items-center gap-2">
                                <Tag color={LOOP_GATE_COLOR[gateInfo?.gate || loop.gate || ''] || 'default'}>
                                    {gateInfo?.gate || loop.gate || '-'}
                                </Tag>
                                {gateInfo?.primaryAction ? <Tag color="blue">下一步: {gateInfo.primaryAction.label}</Tag> : null}
                            </div>
                            <Text type="secondary">{formatGateHint(gateInfo)}</Text>
                            <div className="flex flex-wrap items-center gap-2">
                                {(gateInfo?.actions || []).map((action) => (
                                    <Tag key={action.key} color={action.runnable ? 'blue' : 'default'}>
                                        {action.label}
                                    </Tag>
                                ))}
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            {(['train', 'pool', 'val', 'test'] as const).map((key) => (
                                <Card
                                    key={key}
                                    size="small"
                                    className="!border-github-border/80 !bg-github-bg"
                                    styles={{
                                        header: {
                                            borderBottom: `2px solid ${PRIMARY_VIEW_COLOR[key]}`,
                                        },
                                    }}
                                    title={<span className="font-semibold">{PRIMARY_VIEW_LABEL[key]}</span>}
                                >
                                    <Statistic value={Number(primaryView[key]?.count || 0)} valueStyle={{fontSize: 24}} />
                                    <Text type="secondary" className="text-xs">
                                        {PRIMARY_VIEW_DESC[key]}
                                    </Text>
                                </Card>
                            ))}
                        </div>
                    </div>
                </Card>
            ) : null}

            {(loop.mode === 'active_learning' || loop.mode === 'simulation') ? (
                <Card className="!border-github-border !bg-github-panel" title="Snapshot 概览">
                    {snapshotInfo?.active ? (
                        <div className="flex flex-col gap-3">
                            <Descriptions size="small" column={4}>
                                <Descriptions.Item label="Active Version">{snapshotInfo.active.versionIndex}</Descriptions.Item>
                                <Descriptions.Item label="Update Mode">{snapshotInfo.active.updateMode}</Descriptions.Item>
                                <Descriptions.Item label="Val Policy">{snapshotInfo.active.valPolicy}</Descriptions.Item>
                                <Descriptions.Item label="样本总数">{snapshotInfo.active.sampleCount}</Descriptions.Item>
                            </Descriptions>
                            <Collapse
                                size="small"
                                items={[
                                    {
                                        key: 'advanced',
                                        label: '查看技术细节（Advanced）',
                                        children: (
                                            <div className="flex flex-col gap-3">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Tag>bootstrapSeed: {snapshotInfo.advancedView?.bootstrapSeed ?? 0}</Tag>
                                                    <Tag color="green">revealedFromPool: {snapshotInfo.advancedView?.revealedFromPool ?? 0}</Tag>
                                                    <Tag color="gold">poolHidden: {snapshotInfo.advancedView?.poolHidden ?? 0}</Tag>
                                                    <Tag color="blue">valAnchor: {snapshotInfo.advancedView?.valAnchor ?? 0}</Tag>
                                                    <Tag color="blue">valBatch: {snapshotInfo.advancedView?.valBatch ?? 0}</Tag>
                                                    <Tag color="cyan">testAnchor: {snapshotInfo.advancedView?.testAnchor ?? 0}</Tag>
                                                    <Tag color="cyan">testBatch: {snapshotInfo.advancedView?.testBatch ?? 0}</Tag>
                                                    <Tag color="purple">testComposite: {snapshotInfo.advancedView?.testComposite ?? 0}</Tag>
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    {Object.entries(snapshotInfo.advancedView?.manifest || {}).map(([key, value]) => (
                                                        <Tag key={key}>
                                                            {MANIFEST_LABEL[key] || key}: {Number(value || 0)}
                                                        </Tag>
                                                    ))}
                                                </div>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                            <Divider className="!my-1" />
                            <Text strong>历史版本（最近 5 个）</Text>
                            <Table
                                size="small"
                                rowKey={(row) => row.id}
                                dataSource={(snapshotInfo.history || []).slice(-5).reverse()}
                                pagination={false}
                                columns={[
                                    {title: 'Version', dataIndex: 'versionIndex', width: 90},
                                    {title: 'Mode', dataIndex: 'updateMode', width: 180},
                                    {title: 'Val', dataIndex: 'valPolicy', width: 170},
                                    {title: 'Samples', dataIndex: 'sampleCount', width: 110},
                                    {
                                        title: 'Manifest',
                                        dataIndex: 'manifestHash',
                                        render: (value: string) => String(value || '').slice(0, 12),
                                    },
                                ]}
                            />
                        </div>
                    ) : (
                        <Alert
                            type="info"
                            showIcon
                            message="当前尚未初始化 Snapshot"
                            description="请先执行“初始化 Snapshot”，再开始本模式循环。"
                        />
                    )}
                </Card>
            ) : null}

            <Card
                className="!border-github-border !bg-github-panel"
                title="Prediction（循环外预测辅助标注）"
                extra={(
                    <div className="flex items-center gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/prediction-tasks`)}>
                            任务页
                        </Button>
                        <Button onClick={() => void refreshPredictions()} loading={predictionLoading}>
                            刷新
                        </Button>
                        <Button type="primary" onClick={() => setPredictionScopeOpen(true)} loading={predictionSubmitting}>
                            创建任务（最新 Round）
                        </Button>
                    </div>
                )}
            >
                <Table
                    size="small"
                    rowKey={(row) => row.id}
                    dataSource={predictions}
                    pagination={{pageSize: 6, showSizeChanger: false}}
                    columns={[
                        {
                            title: 'ID',
                            dataIndex: 'id',
                            render: (value: string) => <Text code>{`${value.slice(0, 8)}...`}</Text>,
                        },
                        {
                            title: '状态',
                            dataIndex: 'status',
                            width: 140,
                            render: (value: string) => <Tag>{value}</Tag>,
                        },
                        {
                            title: '来源',
                            width: 220,
                            render: (_: unknown, row: PredictionRead) => (
                                <Text type="secondary">
                                    {row.modelId ? `model:${row.modelId.slice(0, 8)}...` : '-'}
                                </Text>
                            ),
                        },
                        {
                            title: '条目数',
                            dataIndex: 'totalItems',
                            width: 100,
                        },
                        {
                            title: '创建时间',
                            dataIndex: 'createdAt',
                            width: 180,
                            render: (value: string) => formatDateTime(value),
                        },
                        {
                            title: '操作',
                            width: 180,
                            render: (_: unknown, row: PredictionRead) => (
                                <Button
                                    size="small"
                                    onClick={() => void handleApplyPrediction(row.id)}
                                    loading={applyingPredictionId === row.id}
                                    disabled={!['ready', 'applied'].includes(String(row.status || '').toLowerCase())}
                                >
                                    应用到 Draft
                                </Button>
                            ),
                        },
                    ]}
                />
            </Card>

            <Modal
                title="生成 Prediction"
                open={predictionScopeOpen}
                onCancel={() => setPredictionScopeOpen(false)}
                onOk={() => void handleGeneratePrediction(predictionScopeStatus)}
                okText="生成"
                confirmLoading={predictionSubmitting}
            >
                <div className="mb-2 text-github-muted">请选择样本范围（样本级）：</div>
                <Select
                    className="w-full"
                    value={predictionScopeStatus}
                    onChange={(value) => setPredictionScopeStatus(value as 'all' | 'unlabeled' | 'labeled' | 'draft')}
                    options={[
                        {label: '全部样本', value: 'all'},
                        {label: '仅未标注', value: 'unlabeled'},
                        {label: '仅已标注', value: 'labeled'},
                        {label: '仅草稿样本', value: 'draft'},
                    ]}
                />
            </Modal>

            <Card className="!border-github-border !bg-github-panel" title="当前 Loop 的 Rounds">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={rounds}
                    pagination={{pageSize: 8}}
                    columns={[
                        {
                            title: 'Round/Attempt',
                            width: 140,
                            render: (_v: unknown, row: RuntimeRound) => `#${row.roundIndex} · A${row.attemptIndex || 1}`,
                        },
                        {
                            title: '状态',
                            dataIndex: 'state',
                            width: 140,
                            render: (_value: string, row: RuntimeRound) => (
                                <div className="flex items-center gap-2">
                                    <Tag color={ROUND_STATE_COLOR[row.state] || 'default'}>{row.state}</Tag>
                                    {row.awaitingConfirm ? <Tag color="gold">awaiting_confirm</Tag> : null}
                                </div>
                            ),
                        },
                        {title: '插件', dataIndex: 'pluginId'},
                        {
                            title: '策略',
                            render: (_v: unknown, row: RuntimeRound) => row.resolvedParams?.sampling?.strategy || '-',
                        },
                        {
                            title: 'Steps',
                            width: 180,
                            render: (_v: unknown, row: RuntimeRound) => JSON.stringify(row.stepCounts || {}),
                        },
                        {
                            title: '进度摘要',
                            width: 260,
                            render: (_v: unknown, row: RuntimeRound) => {
                                const summaryRow = buildRoundProgressSummary(row);
                                return (
                                    <div className="flex w-full flex-col gap-1">
                                        <Progress percent={summaryRow.percent} size="small"/>
                                        <Text type="secondary">{summaryRow.text}</Text>
                                    </div>
                                );
                            },
                        },
                        {
                            title: 'Train 终态',
                            width: 180,
                            render: (_v: unknown, row: RuntimeRound) => pickPreviewMetric(getMetricBySource(row, 'train')),
                        },
                        {
                            title: 'Eval(Test)',
                            width: 180,
                            render: (_v: unknown, row: RuntimeRound) => pickPreviewMetric(getMetricBySource(row, 'eval')),
                        },
                        {
                            title: 'Final',
                            width: 220,
                            render: (_v: unknown, row: RuntimeRound) => {
                                const source = normalizeFinalMetricSource(row.finalMetricsSource);
                                return (
                                    <div className="flex flex-col gap-1">
                                        <Tag color={source === 'eval' ? 'blue' : (source === 'train' ? 'green' : 'default')}>
                                            {`source: ${FINAL_METRIC_SOURCE_LABEL[source]}`}
                                        </Tag>
                                        <span>{pickPreviewMetric(getMetricBySource(row, 'final'))}</span>
                                    </div>
                                );
                            },
                        },
                        {
                            title: '操作',
                            width: 280,
                            render: (_v: unknown, row: RuntimeRound) => (
                                <div className="flex items-center gap-2">
                                    <Button size="small" onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/rounds/${row.id}`)}>
                                        查看详情
                                    </Button>
                                    <Popconfirm
                                        title={`清理 Round ${row.roundIndex} 的中间预测数据？`}
                                        description="仅清理 SCORE 中间候选/事件/指标，不影响已选 TopK 与最终制品。"
                                        okText="确认清理"
                                        cancelText="取消"
                                        onConfirm={() => handleCleanupRoundPredictions(row.roundIndex)}
                                    >
                                        <Button
                                            size="small"
                                            danger
                                            loading={cleaningRound === row.roundIndex}
                                            disabled={cleaningRound !== null && cleaningRound !== row.roundIndex}
                                        >
                                            清理预测
                                        </Button>
                                    </Popconfirm>
                                </div>
                            ),
                        },
                    ]}
                />
            </Card>

            <Modal
                title="调整 TopK 选样（include/exclude）"
                open={selectionAdjustOpen}
                onCancel={() => setSelectionAdjustOpen(false)}
                onOk={handleApplySelectionAdjust}
                okText="应用调整"
                okButtonProps={{loading: selectionSubmitting}}
                destroyOnHidden
                width={980}
                footer={[
                    <Button
                        key="reset"
                        onClick={handleResetSelectionAdjust}
                        disabled={selectionSubmitting || selectionLoading || !selectionRoundId}
                    >
                        重置覆写
                    </Button>,
                    <Button key="cancel" onClick={() => setSelectionAdjustOpen(false)}>
                        关闭
                    </Button>,
                    <Button
                        key="apply"
                        type="primary"
                        loading={selectionSubmitting}
                        onClick={handleApplySelectionAdjust}
                        disabled={selectionLoading || !selectionRoundId}
                    >
                        应用调整
                    </Button>,
                ]}
            >
                {selectionLoading ? (
                    <div className="flex min-h-[180px] items-center justify-center">
                        <Spin />
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag>TopK: {selectionData?.topk ?? '-'}</Tag>
                            <Tag>ReviewPool: {selectionData?.reviewPoolSize ?? '-'}</Tag>
                            <Tag>Selected: {selectionData?.selectedCount ?? '-'}</Tag>
                            <Tag>Include: {selectionData?.includeCount ?? '-'}</Tag>
                            <Tag>Exclude: {selectionData?.excludeCount ?? '-'}</Tag>
                        </div>
                        <Form form={selectionForm} layout="vertical">
                            <Form.Item name="includeSampleIdsText" label="Include Sample IDs">
                                <Input.TextArea rows={3} placeholder="按逗号或换行分隔，仅允许来自 score pool 的样本" />
                            </Form.Item>
                            <Form.Item name="excludeSampleIdsText" label="Exclude Sample IDs">
                                <Input.TextArea rows={3} placeholder="按逗号或换行分隔，将从当前 TopK 中排除" />
                            </Form.Item>
                            <Form.Item name="reason" label="Reason（可选）">
                                <Input placeholder="记录此次人工调整原因" />
                            </Form.Item>
                        </Form>
                        <Divider className="!my-2" />
                        <Text strong>当前生效 TopK 预览</Text>
                        <Table
                            size="small"
                            rowKey={(row) => row.sampleId}
                            dataSource={selectionData?.effectiveSelected || []}
                            pagination={false}
                            scroll={{y: 260}}
                            columns={[
                                { title: 'Rank', dataIndex: 'rank', width: 80 },
                                { title: 'Sample ID', dataIndex: 'sampleId' },
                                {
                                    title: 'Score',
                                    dataIndex: 'score',
                                    width: 120,
                                    render: (value: number) => Number(value || 0).toFixed(6),
                                },
                            ]}
                        />
                    </div>
                )}
            </Modal>

            <Modal
                title="初始化 Snapshot"
                open={snapshotInitOpen}
                onCancel={() => setSnapshotInitOpen(false)}
                onOk={handleInitSnapshot}
                okButtonProps={{loading: snapshotSubmitting}}
                destroyOnHidden
            >
                <Form form={initForm} layout="vertical">
                    <Form.Item name="trainSeedRatio" label="Train Seed Ratio">
                        <Slider min={0} max={1} step={0.01} tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(2) : '')}}/>
                    </Form.Item>
                    <Form.Item name="valRatio" label="Val Ratio">
                        <Slider min={0} max={1} step={0.01} tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(2) : '')}}/>
                    </Form.Item>
                    <Form.Item name="testRatio" label="Test Ratio">
                        <Slider min={0} max={1} step={0.01} tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(2) : '')}}/>
                    </Form.Item>
                    <Form.Item name="valPolicy" label="Val Policy">
                        <Select
                            allowClear
                            options={[
                                {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                            ]}
                        />
                    </Form.Item>
                    <Form.Item name="sampleIdsText" label="Sample IDs（可选）">
                        <Input.TextArea rows={4} placeholder="按逗号或换行分隔，不填则使用项目全集"/>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title="更新 Snapshot"
                open={snapshotUpdateOpen}
                onCancel={() => setSnapshotUpdateOpen(false)}
                onOk={handleUpdateSnapshot}
                okButtonProps={{loading: snapshotSubmitting}}
                destroyOnHidden
            >
                <Form form={updateForm} layout="vertical">
                    <Form.Item name="mode" label="Update Mode">
                        <Select
                            allowClear
                            options={[
                                {label: 'APPEND_ALL_TO_POOL', value: 'append_all_to_pool'},
                                {label: 'APPEND_SPLIT', value: 'append_split'},
                            ]}
                        />
                    </Form.Item>
                    <Form.Item name="valPolicy" label="Val Policy（可选覆盖）">
                        <Select
                            allowClear
                            options={[
                                {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                            ]}
                        />
                    </Form.Item>
                    {updateMode === 'append_split' ? (
                        <>
                            <Form.Item name="batchTestRatio" label="Batch Test Ratio">
                                <Slider min={0} max={1} step={0.01} tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(2) : '')}}/>
                            </Form.Item>
                            <Form.Item name="batchValRatio" label="Batch Val Ratio">
                                <Slider min={0} max={1} step={0.01} tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(2) : '')}}/>
                            </Form.Item>
                        </>
                    ) : null}
                    <Form.Item name="sampleIdsText" label="Sample IDs（可选）">
                        <Input.TextArea rows={4} placeholder="按逗号或换行分隔，不填则自动取新增样本"/>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectLoopDetail;
