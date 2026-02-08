import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Form,
    Input,
    InputNumber,
    List,
    Modal,
    Progress,
    Radio,
    Select,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';

import {api} from '../../services/api';
import {useAuthStore} from '../../store/authStore';
import {
    ALLoop,
    AnnotationBatch,
    LoopCreateRequest,
    LoopRecoverMode,
    LoopRound,
    LoopSummary,
    ProjectBranch,
    ProjectModel,
    RuntimeJob,
    RuntimeJobEvent,
    RuntimeMetricPoint,
    RuntimeTopKCandidate,
} from '../../types';

const {Text, Paragraph} = Typography;

const JOB_STATUS_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    success: 'success',
    failed: 'error',
    cancelled: 'warning',
};

const LOOP_STATUS_COLOR: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    stopped: 'default',
    completed: 'success',
    failed: 'error',
};

const ROUND_STATUS_COLOR: Record<string, string> = {
    training: 'processing',
    annotation: 'warning',
    completed: 'success',
    completed_no_candidates: 'gold',
    failed: 'error',
};

const TERMINAL_STATUS = new Set(['success', 'failed', 'cancelled']);
const ROUND_COMPLETED_STATUS = new Set(['completed', 'completed_no_candidates']);

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const buildWsUrl = (jobId: string, afterSeq: number, token: string): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw;
    const suffix = `/jobs/${jobId}/events/ws?after_seq=${afterSeq}&token=${encodeURIComponent(token)}`;
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl.replace(/^http/, 'ws')}${suffix}`;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`;
    return `${protocol}//${window.location.host}${path}${suffix}`;
};

const eventToText = (event: RuntimeJobEvent): string => {
    if (event.eventType === 'log') {
        return `[${event.payload.level || 'INFO'}] ${event.payload.message || ''}`;
    }
    if (event.eventType === 'status') {
        return `状态 => ${event.payload.status || ''} ${event.payload.reason || ''}`.trim();
    }
    if (event.eventType === 'progress') {
        return `进度 epoch=${event.payload.epoch ?? '-'} step=${event.payload.step ?? '-'} / ${event.payload.totalSteps ?? '-'}`;
    }
    if (event.eventType === 'metric') {
        return `指标 ${JSON.stringify(event.payload.metrics || {})}`;
    }
    if (event.eventType === 'artifact') {
        return `制品 ${event.payload.name || ''} -> ${event.payload.uri || ''}`;
    }
    return `${event.eventType} ${JSON.stringify(event.payload || {})}`;
};

type LoopRecoverForm = {
    mode: LoopRecoverMode;
    pluginId?: string;
    queryStrategy?: string;
    paramsJson?: string;
    resourcesJson?: string;
};

const ProjectLoops: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const token = useAuthStore((state) => state.token);

    const [loops, setLoops] = useState<ALLoop[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [datasetIds, setDatasetIds] = useState<string[]>([]);
    const [jobs, setJobs] = useState<RuntimeJob[]>([]);
    const [rounds, setRounds] = useState<LoopRound[]>([]);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [models, setModels] = useState<ProjectModel[]>([]);

    const [selectedLoopId, setSelectedLoopId] = useState<string>();
    const [selectedJobId, setSelectedJobId] = useState<string>();

    const [jobDetail, setJobDetail] = useState<RuntimeJob | null>(null);
    const [metricPoints, setMetricPoints] = useState<RuntimeMetricPoint[]>([]);
    const [topk, setTopk] = useState<RuntimeTopKCandidate[]>([]);
    const [events, setEvents] = useState<RuntimeJobEvent[]>([]);
    const [artifactsCount, setArtifactsCount] = useState<number>(0);
    const [wsConnected, setWsConnected] = useState<boolean>(false);
    const eventCursorRef = useRef<number>(0);

    const [loadingMeta, setLoadingMeta] = useState<boolean>(true);
    const [loadingJob, setLoadingJob] = useState<boolean>(false);
    const [createLoopLoading, setCreateLoopLoading] = useState<boolean>(false);
    const [startJobLoading, setStartJobLoading] = useState<boolean>(false);
    const [stopJobLoading, setStopJobLoading] = useState<boolean>(false);
    const [loopControlLoading, setLoopControlLoading] = useState<boolean>(false);
    const [recoverOpen, setRecoverOpen] = useState<boolean>(false);
    const [recoverLoading, setRecoverLoading] = useState<boolean>(false);
    const [batchCreateLoading, setBatchCreateLoading] = useState<boolean>(false);
    const [modelLoading, setModelLoading] = useState<boolean>(false);

    const [createLoopForm] = Form.useForm<LoopCreateRequest>();
    const [createJobForm] = Form.useForm<{
        pluginId: string;
        mode: string;
        jobType: string;
        queryStrategy: string;
        topk: number;
        epochs: number;
        batchSize: number;
        resourcesGpuCount: number;
    }>();
    const [recoverForm] = Form.useForm<LoopRecoverForm>();
    const recoverMode = Form.useWatch('mode', recoverForm) || 'retry_same_params';

    const selectedLoop = useMemo(
        () => loops.find((item) => item.id === selectedLoopId),
        [loops, selectedLoopId],
    );
    const selectedBranch = useMemo(
        () => branches.find((item) => item.id === selectedLoop?.branchId),
        [branches, selectedLoop?.branchId],
    );
    const latestFailedJob = useMemo(
        () => jobs.find((item) => item.status === 'failed') || null,
        [jobs],
    );

    const metricNames = useMemo(() => {
        const names = new Set<string>();
        metricPoints.forEach((item) => names.add(item.metricName));
        return Array.from(names);
    }, [metricPoints]);

    const metricChartData = useMemo(() => {
        const rows = new Map<number, Record<string, number>>();
        metricPoints.forEach((point) => {
            const stepKey = Number(point.step || 0);
            const current = rows.get(stepKey) || {step: stepKey};
            current[point.metricName] = Number(point.metricValue);
            rows.set(stepKey, current);
        });
        return Array.from(rows.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
    }, [metricPoints]);

    const topkDataSource = useMemo(() => {
        return topk.map((item, idx) => ({
            rank: idx + 1,
            sampleId: item.sampleId,
            score: item.score,
            extra: item.extra || {},
            predictionSnapshot: item.predictionSnapshot || {},
        }));
    }, [topk]);

    const gotoBatchSamples = useCallback((batch: AnnotationBatch, branchName?: string) => {
        if (!projectId) return;
        const datasetId = datasetIds[0];
        if (!datasetId) {
            message.error('项目未绑定数据集，无法跳转标注');
            return;
        }
        const params = new URLSearchParams();
        params.set('datasetId', datasetId);
        params.set('branch', branchName || selectedBranch?.name || 'master');
        params.set('batchId', batch.id);
        params.set('status', 'all');
        params.set('sort', 'createdAt:desc');
        params.set('page', '1');
        params.set('pageSize', '24');
        navigate(`/projects/${projectId}/samples?${params.toString()}`);
    }, [projectId, datasetIds, selectedBranch?.name, navigate]);

    const loadJobs = useCallback(async (loopId: string, preferredJobId?: string) => {
        const list = await api.getLoopJobs(loopId, 100);
        setJobs(list);
        const nextJobId = preferredJobId || list[0]?.id;
        setSelectedJobId(nextJobId);
        return nextJobId;
    }, []);

    const loadLoopRoundSummary = useCallback(async (loopId: string) => {
        try {
            const [roundRows, summaryData] = await Promise.all([
                api.getLoopRounds(loopId, 500),
                api.getLoopSummary(loopId),
            ]);
            setRounds(roundRows);
            setSummary(summaryData);
        } catch {
            setRounds([]);
            setSummary(null);
        }
    }, []);

    const loadModels = useCallback(async () => {
        if (!projectId) return;
        try {
            const rows = await api.getProjectModels(projectId, 200);
            setModels(rows);
        } catch {
            setModels([]);
        }
    }, [projectId]);

    const loadJobDashboard = useCallback(async (jobId: string) => {
        setLoadingJob(true);
        try {
            const [job, points, candidates, artifacts, initialEvents] = await Promise.all([
                api.getJob(jobId),
                api.getJobMetricSeries(jobId, 5000),
                api.getJobSamplingTopK(jobId, 200),
                api.getJobArtifacts(jobId),
                api.getJobEvents(jobId, 0),
            ]);
            setJobDetail(job);
            setMetricPoints(points);
            setTopk(candidates);
            setArtifactsCount(artifacts.artifacts.length);
            setEvents(initialEvents);
            eventCursorRef.current = initialEvents.reduce((max, item) => Math.max(max, item.seq), 0);
            setJobs((prev) => prev.map((item) => (item.id === job.id ? job : item)));
        } catch (error: any) {
            message.error(error?.message || '加载任务详情失败');
        } finally {
            setLoadingJob(false);
        }
    }, []);

    const loadMeta = useCallback(async () => {
        if (!projectId) return;
        setLoadingMeta(true);
        try {
            const [loopList, branchList, dsIds] = await Promise.all([
                api.getProjectLoops(projectId),
                api.getProjectBranches(projectId),
                api.getProjectDatasets(projectId),
            ]);
            setLoops(loopList);
            setBranches(branchList);
            setDatasetIds(dsIds);
            await loadModels();

            if (branchList.length > 0 && !createLoopForm.getFieldValue('branchId')) {
                createLoopForm.setFieldValue('branchId', branchList[0].id);
            }

            const loopId = selectedLoopId && loopList.find((item) => item.id === selectedLoopId)
                ? selectedLoopId
                : loopList[0]?.id;
            setSelectedLoopId(loopId);

            if (!loopId) {
                setJobs([]);
                setRounds([]);
                setSummary(null);
                setSelectedJobId(undefined);
                setJobDetail(null);
                setMetricPoints([]);
                setTopk([]);
                setEvents([]);
                setArtifactsCount(0);
                return;
            }

            await loadLoopRoundSummary(loopId);
            const jobId = await loadJobs(loopId);
            if (jobId) {
                await loadJobDashboard(jobId);
            } else {
                setSelectedJobId(undefined);
                setJobDetail(null);
                setMetricPoints([]);
                setTopk([]);
                setEvents([]);
                setArtifactsCount(0);
            }
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 信息失败');
        } finally {
            setLoadingMeta(false);
        }
    }, [
        projectId,
        selectedLoopId,
        createLoopForm,
        loadModels,
        loadLoopRoundSummary,
        loadJobs,
        loadJobDashboard,
    ]);

    useEffect(() => {
        createJobForm.setFieldsValue({
            pluginId: 'yolo_det_v1',
            mode: 'active_learning',
            jobType: 'train_detection',
            queryStrategy: 'aug_iou_disagreement_v1',
            topk: 200,
            epochs: 30,
            batchSize: 16,
            resourcesGpuCount: 1,
        });
        void loadMeta();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [projectId]);

    useEffect(() => {
        if (!selectedJobId) return;
        const timer = setInterval(async () => {
            try {
                const [newEvents, job] = await Promise.all([
                    api.getJobEvents(selectedJobId, eventCursorRef.current),
                    api.getJob(selectedJobId),
                ]);
                if (newEvents.length > 0) {
                    setEvents((prev) => {
                        const merged = [...prev, ...newEvents];
                        const dedup = new Map<number, RuntimeJobEvent>();
                        merged.forEach((item) => dedup.set(item.seq, item));
                        return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
                    });
                    eventCursorRef.current = Math.max(
                        eventCursorRef.current,
                        ...newEvents.map((item) => item.seq),
                    );
                }
                setJobDetail(job);
                setJobs((prev) => prev.map((item) => (item.id === job.id ? job : item)));

                if (newEvents.some((item) => item.eventType === 'metric') || job.status === 'running') {
                    const points = await api.getJobMetricSeries(selectedJobId, 5000);
                    setMetricPoints(points);
                }
                if (TERMINAL_STATUS.has(job.status)) {
                    const [candidates, artifacts] = await Promise.all([
                        api.getJobSamplingTopK(selectedJobId, 200),
                        api.getJobArtifacts(selectedJobId),
                    ]);
                    setTopk(candidates);
                    setArtifactsCount(artifacts.artifacts.length);
                    if (selectedLoopId) {
                        await loadLoopRoundSummary(selectedLoopId);
                    }
                    await loadModels();
                }
            } catch {
                // ignore polling errors
            }
        }, 3000);
        return () => clearInterval(timer);
    }, [selectedJobId, selectedLoopId, loadLoopRoundSummary, loadModels]);

    useEffect(() => {
        if (!selectedJobId || !token) return;
        const ws = new WebSocket(buildWsUrl(selectedJobId, eventCursorRef.current, token));
        ws.onopen = () => setWsConnected(true);
        ws.onclose = () => setWsConnected(false);
        ws.onerror = () => setWsConnected(false);
        ws.onmessage = (event: MessageEvent<string>) => {
            try {
                const payload = JSON.parse(event.data || '{}') as RuntimeJobEvent;
                if (!payload || typeof payload.seq !== 'number') return;
                setEvents((prev) => {
                    const merged = [...prev, payload];
                    const dedup = new Map<number, RuntimeJobEvent>();
                    merged.forEach((item) => dedup.set(item.seq, item));
                    return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq);
                });
                eventCursorRef.current = Math.max(eventCursorRef.current, payload.seq);
            } catch {
                // ignore malformed ws payload
            }
        };
        return () => {
            ws.close();
            setWsConnected(false);
        };
    }, [selectedJobId, token]);

    const handleLoopChange = async (value: string) => {
        setSelectedLoopId(value);
        setSelectedJobId(undefined);
        setJobDetail(null);
        setMetricPoints([]);
        setTopk([]);
        setEvents([]);
        setArtifactsCount(0);
        try {
            await loadLoopRoundSummary(value);
            const jobId = await loadJobs(value);
            if (jobId) {
                await loadJobDashboard(jobId);
            }
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 任务失败');
        }
    };

    const handleJobChange = async (value: string) => {
        setSelectedJobId(value);
        await loadJobDashboard(value);
    };

    const handleCreateLoop = async (values: LoopCreateRequest) => {
        if (!projectId) return;
        setCreateLoopLoading(true);
        try {
            const created = await api.createProjectLoop(projectId, values);
            message.success('Loop 创建成功');
            await loadMeta();
            setSelectedLoopId(created.id);
            await loadLoopRoundSummary(created.id);
        } catch (error: any) {
            message.error(error?.message || 'Loop 创建失败');
        } finally {
            setCreateLoopLoading(false);
        }
    };

    const handleLoopControl = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
        if (!selectedLoop) return;
        if (action === 'start' && selectedLoop.status === 'failed') {
            recoverForm.setFieldsValue({
                mode: 'retry_same_params',
                pluginId: latestFailedJob?.pluginId || selectedLoop.modelArch,
                queryStrategy: latestFailedJob?.queryStrategy || selectedLoop.queryStrategy,
                paramsJson: JSON.stringify(latestFailedJob?.params || {}, null, 2),
                resourcesJson: JSON.stringify(latestFailedJob?.resources || {}, null, 2),
            });
            setRecoverOpen(true);
            return;
        }
        setLoopControlLoading(true);
        try {
            if (action === 'start') await api.startLoop(selectedLoop.id);
            if (action === 'pause') await api.pauseLoop(selectedLoop.id);
            if (action === 'resume') await api.resumeLoop(selectedLoop.id);
            if (action === 'stop') await api.stopLoop(selectedLoop.id);
            message.success(`Loop 已${action === 'start' ? '启动' : action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '停止'}`);
            await loadMeta();
        } catch (error: any) {
            message.error(error?.message || 'Loop 控制失败');
        } finally {
            setLoopControlLoading(false);
        }
    };

    const handleRecoverLoop = async () => {
        if (!selectedLoop) return;
        try {
            const values = await recoverForm.validateFields();
            const mode = values.mode || 'retry_same_params';
            const payload: {
                mode: LoopRecoverMode;
                overrides?: {
                    pluginId?: string;
                    queryStrategy?: string;
                    params?: Record<string, any>;
                    resources?: Record<string, any>;
                };
            } = {mode};

            if (mode === 'rerun_with_overrides') {
                const overrides: Record<string, any> = {};
                if (values.pluginId?.trim()) overrides.pluginId = values.pluginId.trim();
                if (values.queryStrategy?.trim()) overrides.queryStrategy = values.queryStrategy.trim();

                if (values.paramsJson?.trim()) {
                    const parsed = JSON.parse(values.paramsJson);
                    if (parsed && typeof parsed !== 'object') {
                        throw new Error('params 必须是 JSON 对象');
                    }
                    overrides.params = parsed || {};
                }
                if (values.resourcesJson?.trim()) {
                    const parsed = JSON.parse(values.resourcesJson);
                    if (parsed && typeof parsed !== 'object') {
                        throw new Error('resources 必须是 JSON 对象');
                    }
                    overrides.resources = parsed || {};
                }
                payload.overrides = overrides;
            }

            setRecoverLoading(true);
            await api.recoverLoop(selectedLoop.id, payload);
            setRecoverOpen(false);
            message.success('恢复任务已创建并开始派发');
            await loadMeta();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || '恢复 Loop 失败');
        } finally {
            setRecoverLoading(false);
        }
    };

    const handleStartJob = async () => {
        if (!projectId || !selectedLoop) {
            message.warning('请先选择一个 Loop');
            return;
        }
        if (!selectedBranch?.headCommitId) {
            message.error('该 Loop 绑定分支没有可用的 head commit，无法启动任务');
            return;
        }

        const values = createJobForm.getFieldsValue();
        setStartJobLoading(true);
        try {
            const created = await api.createLoopJob(
                selectedLoop.id,
                {
                    projectId,
                    sourceCommitId: selectedBranch.headCommitId,
                    pluginId: values.pluginId,
                    mode: values.mode,
                    jobType: values.jobType,
                    queryStrategy: values.queryStrategy,
                    params: {
                        epochs: values.epochs,
                        batch: values.batchSize,
                        topk: values.topk,
                    },
                    resources: {
                        gpuCount: values.resourcesGpuCount,
                    },
                },
                true,
            );
            message.success('任务已创建并尝试派发');
            const nextJobId = await loadJobs(selectedLoop.id, created.id);
            if (nextJobId) {
                setSelectedJobId(nextJobId);
                await loadJobDashboard(nextJobId);
            }
        } catch (error: any) {
            message.error(error?.message || '创建任务失败');
        } finally {
            setStartJobLoading(false);
        }
    };

    const handleStopJob = async () => {
        if (!selectedJobId) return;
        setStopJobLoading(true);
        try {
            const resp = await api.stopJob(selectedJobId, 'user requested stop');
            message.info(`停止命令已提交，状态：${resp.status}`);
            await loadJobDashboard(selectedJobId);
        } catch (error: any) {
            message.error(error?.message || '停止任务失败');
        } finally {
            setStopJobLoading(false);
        }
    };

    const handleCreateBatchFromJob = async () => {
        if (!selectedJobId) return;
        setBatchCreateLoading(true);
        try {
            const batch = await api.createAnnotationBatchFromJob(selectedJobId, 200);
            message.success(`批次已创建：${batch.id.slice(0, 8)}...`);
            gotoBatchSamples(batch, selectedBranch?.name);
            if (selectedLoopId) await loadLoopRoundSummary(selectedLoopId);
        } catch (error: any) {
            message.error(error?.message || '创建标注批次失败');
        } finally {
            setBatchCreateLoading(false);
        }
    };

    const handleRegisterModelFromJob = async () => {
        if (!projectId || !selectedJobId) return;
        setModelLoading(true);
        try {
            const job = jobDetail || await api.getJob(selectedJobId);
            const model = await api.registerModelFromJob(projectId, {
                jobId: selectedJobId,
                name: `${selectedLoop?.name || 'loop'}-r${job.roundIndex || job.iteration}`,
                versionTag: `r${job.roundIndex || job.iteration}`,
                status: 'candidate',
            });
            message.success(`模型已注册：${model.name}`);
            await loadModels();
            await loadMeta();
        } catch (error: any) {
            message.error(error?.message || '模型注册失败');
        } finally {
            setModelLoading(false);
        }
    };

    const handlePromoteModel = async (modelId: string) => {
        setModelLoading(true);
        try {
            await api.promoteModel(modelId, 'production');
            message.success('模型已晋升为 production');
            await loadModels();
            await loadMeta();
        } catch (error: any) {
            message.error(error?.message || '模型晋升失败');
        } finally {
            setModelLoading(false);
        }
    };

    const handleDownloadModel = async (model: ProjectModel) => {
        setModelLoading(true);
        try {
            const artifactName = model.artifacts?.['best.pt'] ? 'best.pt' : Object.keys(model.artifacts || {})[0];
            if (!artifactName) {
                message.error('该模型无可下载制品');
                return;
            }
            const data = await api.getModelArtifactDownloadUrl(model.id, artifactName, 2);
            window.open(data.downloadUrl, '_blank', 'noopener,noreferrer');
        } catch (error: any) {
            message.error(error?.message || '获取下载链接失败');
        } finally {
            setModelLoading(false);
        }
    };

    if (loadingMeta) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                    <div className="min-w-0 lg:col-span-7">
                        <div className="flex w-full flex-col gap-4">
                            <div className="flex flex-wrap items-center gap-2">
                                <Select
                                    className="min-w-[220px]"
                                    placeholder="选择 Loop"
                                    value={selectedLoopId}
                                    onChange={handleLoopChange}
                                    options={loops.map((item) => ({label: item.name, value: item.id}))}
                                />
                                <Select
                                    className="min-w-[260px]"
                                    placeholder="选择任务"
                                    value={selectedJobId}
                                    onChange={handleJobChange}
                                    options={jobs.map((item) => ({
                                        label: `round#${item.roundIndex || item.iteration} · ${item.status} · ${item.id.slice(0, 8)}`,
                                        value: item.id,
                                    }))}
                                />
                                <Button onClick={loadMeta}>刷新</Button>
                                <Button
                                    danger
                                    onClick={handleStopJob}
                                    loading={stopJobLoading}
                                    disabled={!jobDetail || jobDetail.status !== 'running'}
                                >
                                    停止任务
                                </Button>
                            </div>

                            {!selectedLoop ? (
                                <Alert type="info" showIcon message="当前项目还没有 Loop，请先在右侧创建。"/>
                            ) : (
                                <Alert
                                    type="info"
                                    showIcon
                                    message={
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span>当前 Loop：{selectedLoop.name}</span>
                                            <Tag color={LOOP_STATUS_COLOR[selectedLoop.status] || 'default'}>
                                                {selectedLoop.status}
                                            </Tag>
                                        </div>
                                    }
                                    description={
                                        <>
                                            <div>策略：{selectedLoop.queryStrategy}</div>
                                            <div>分支：{selectedBranch?.name || selectedLoop.branchId}</div>
                                            <div>事件流：{wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接（HTTP 轮询中）'}</div>
                                            <div>轮次控制：max_rounds={selectedLoop.maxRounds} topk={selectedLoop.queryBatchSize}</div>
                                        </>
                                    }
                                />
                            )}

                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    type="primary"
                                    loading={loopControlLoading}
                                    onClick={() => handleLoopControl('start')}
                                    disabled={!selectedLoop || selectedLoop.status === 'running'}
                                >
                                    Start Loop
                                </Button>
                                <Button
                                    loading={loopControlLoading}
                                    onClick={() => handleLoopControl('pause')}
                                    disabled={!selectedLoop || selectedLoop.status !== 'running'}
                                >
                                    Pause Loop
                                </Button>
                                <Button
                                    loading={loopControlLoading}
                                    onClick={() => handleLoopControl('resume')}
                                    disabled={!selectedLoop || (selectedLoop.status !== 'paused' && selectedLoop.status !== 'draft')}
                                >
                                    Resume Loop
                                </Button>
                                <Button
                                    danger
                                    loading={loopControlLoading}
                                    onClick={() => handleLoopControl('stop')}
                                    disabled={!selectedLoop || selectedLoop.status === 'stopped' || selectedLoop.status === 'completed'}
                                >
                                    Stop Loop
                                </Button>
                            </div>

                            <Form form={createJobForm} layout="inline">
                                <Form.Item name="pluginId" label="插件">
                                    <Input className="w-[160px]"/>
                                </Form.Item>
                                <Form.Item name="mode" label="模式">
                                    <Select
                                        className="w-[150px]"
                                        options={[
                                            {label: '主动学习', value: 'active_learning'},
                                            {label: '模拟训练', value: 'simulation'},
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item name="jobType" label="任务类型">
                                    <Input className="w-[150px]"/>
                                </Form.Item>
                                <Form.Item name="queryStrategy" label="采样策略">
                                    <Select
                                        className="w-[260px]"
                                        options={[
                                            {label: 'aug_iou_disagreement_v1', value: 'aug_iou_disagreement_v1'},
                                            {label: 'uncertainty_1_minus_max_conf', value: 'uncertainty_1_minus_max_conf'},
                                            {label: 'random_baseline', value: 'random_baseline'},
                                            {label: 'plugin_native_strategy', value: 'plugin_native_strategy'},
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item name="epochs" label="epochs">
                                    <InputNumber min={1} max={500}/>
                                </Form.Item>
                                <Form.Item name="batchSize" label="batch">
                                    <InputNumber min={1} max={2048}/>
                                </Form.Item>
                                <Form.Item name="topk" label="topk">
                                    <InputNumber min={1} max={5000}/>
                                </Form.Item>
                                <Form.Item name="resourcesGpuCount" label="gpu">
                                    <InputNumber min={0} max={16}/>
                                </Form.Item>
                            </Form>

                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    type="primary"
                                    loading={startJobLoading}
                                    onClick={handleStartJob}
                                    disabled={!selectedLoop}
                                >
                                    启动任务
                                </Button>
                                <Button
                                    loading={batchCreateLoading}
                                    onClick={handleCreateBatchFromJob}
                                    disabled={!selectedJobId}
                                >
                                    生成标注批次并跳转
                                </Button>
                                <Button
                                    loading={modelLoading}
                                    onClick={handleRegisterModelFromJob}
                                    disabled={!selectedJobId}
                                >
                                    从当前任务注册模型
                                </Button>
                            </div>
                        </div>
                    </div>

                    <div className="min-w-0 lg:col-span-5">
                        <Card
                            size="small"
                            title="创建 Loop"
                            className="!border-github-border !bg-github-panel"
                        >
                            <Form form={createLoopForm} layout="vertical" onFinish={handleCreateLoop}>
                                <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入 loop 名称'}]}>
                                    <Input placeholder="例如：fedo-yolo-aug-iou"/>
                                </Form.Item>
                                <Form.Item name="branchId" label="绑定分支" rules={[{required: true, message: '请选择分支'}]}>
                                    <Select options={branches.map((item) => ({label: item.name, value: item.id}))}/>
                                </Form.Item>
                                <Form.Item name="queryStrategy" label="默认采样策略" initialValue="aug_iou_disagreement_v1">
                                    <Input/>
                                </Form.Item>
                                <Form.Item name="modelArch" label="模型架构/插件" initialValue="yolo_det_v1">
                                    <Input/>
                                </Form.Item>
                                <Form.Item name="maxRounds" label="最大轮次" initialValue={5}>
                                    <InputNumber min={1} max={100} className="w-full"/>
                                </Form.Item>
                                <Form.Item name="queryBatchSize" label="每轮 TopK" initialValue={200}>
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                                <Form.Item name="minSeedLabeled" label="最小 seed 标注量" initialValue={100}>
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                                <Form.Item name="minNewLabelsPerRound" label="每轮最小新增标注" initialValue={120}>
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                                <Button type="dashed" htmlType="submit" loading={createLoopLoading}>
                                    创建 Loop
                                </Button>
                            </Form>
                        </Card>
                    </div>
                </div>
            </Card>

            {selectedLoop ? (
                <Card className="!border-github-border !bg-github-panel" title="Loop 统计摘要">
                    <Descriptions size="small" column={4}>
                        <Descriptions.Item label="状态">
                            <Tag color={LOOP_STATUS_COLOR[selectedLoop.status] || 'default'}>{selectedLoop.status}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="总轮次">{summary?.roundsTotal ?? rounds.length}</Descriptions.Item>
                        <Descriptions.Item label="完成轮次">{summary?.roundsCompleted ?? rounds.filter((x) => ROUND_COMPLETED_STATUS.has(x.status)).length}</Descriptions.Item>
                        <Descriptions.Item label="累计选样">{summary?.selectedTotal ?? rounds.reduce((acc, x) => acc + x.selectedCount, 0)}</Descriptions.Item>
                        <Descriptions.Item label="累计标注">{summary?.labeledTotal ?? rounds.reduce((acc, x) => acc + x.labeledCount, 0)}</Descriptions.Item>
                        <Descriptions.Item label="最新 mAP50">{Number(summary?.metricsLatest?.map50 || 0).toFixed(4)}</Descriptions.Item>
                        <Descriptions.Item label="最近任务">{selectedLoop.lastJobId ? <Text code>{selectedLoop.lastJobId}</Text> : '-'}</Descriptions.Item>
                        <Descriptions.Item label="最近模型">{selectedLoop.latestModelId ? <Text code>{selectedLoop.latestModelId}</Text> : '-'}</Descriptions.Item>
                    </Descriptions>
                    {selectedLoop.lastError ? (
                        <Alert type="error" showIcon className="mt-3" message={selectedLoop.lastError}/>
                    ) : null}
                </Card>
            ) : null}

            <Card className="!border-github-border !bg-github-panel" title="Round 时间线">
                {rounds.length === 0 ? (
                    <Empty description="暂无轮次记录"/>
                ) : (
                    <Table
                        size="small"
                        rowKey={(item) => item.id}
                        pagination={{pageSize: 8}}
                        dataSource={rounds}
                        columns={[
                            {title: 'Round', dataIndex: 'roundIndex', width: 90},
                            {
                                title: '状态',
                                dataIndex: 'status',
                                width: 120,
                                render: (value: string) => <Tag color={ROUND_STATUS_COLOR[value] || 'default'}>{value}</Tag>,
                            },
                            {title: '源 Commit', dataIndex: 'sourceCommitId', render: (v: string) => <Text code>{String(v).slice(0, 8)}</Text>},
                            {title: '选样数', dataIndex: 'selectedCount', width: 100},
                            {title: '已标注', dataIndex: 'labeledCount', width: 100},
                            {
                                title: 'mAP50',
                                render: (_value: unknown, row: LoopRound) => Number(row.metrics?.map50 || 0).toFixed(4),
                                width: 100,
                            },
                            {
                                title: '批次',
                                render: (_value: unknown, row: LoopRound) => {
                                    if (!row.annotationBatchId) return '-';
                                    return (
                                        <Button
                                            size="small"
                                            onClick={async () => {
                                                try {
                                                    const batch = await api.getAnnotationBatch(row.annotationBatchId as string);
                                                    gotoBatchSamples(batch, selectedBranch?.name);
                                                } catch (error: any) {
                                                    message.error(error?.message || '加载批次失败');
                                                }
                                            }}
                                        >
                                            打开批次
                                        </Button>
                                    );
                                },
                                width: 140,
                            },
                            {title: '开始', dataIndex: 'startedAt', render: (v: string | null) => formatDateTime(v)},
                            {title: '结束', dataIndex: 'endedAt', render: (v: string | null) => formatDateTime(v)},
                        ]}
                    />
                )}
            </Card>

            {!selectedJobId ? (
                <Card className="!border-github-border !bg-github-panel">
                    <Empty description="当前 Loop 还没有任务"/>
                </Card>
            ) : loadingJob ? (
                <Card className="!border-github-border !bg-github-panel">
                    <div className="flex h-[320px] items-center justify-center">
                        <Spin/>
                    </div>
                </Card>
            ) : (
                <>
                    <Card className="!border-github-border !bg-github-panel" title="任务概览">
                        <Descriptions size="small" column={3}>
                            <Descriptions.Item label="任务 ID">
                                <Text code>{jobDetail?.id || '-'}</Text>
                            </Descriptions.Item>
                            <Descriptions.Item label="状态">
                                <Tag color={JOB_STATUS_COLOR[jobDetail?.status || 'pending']}>
                                    {jobDetail?.status || '-'}
                                </Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="执行器">
                                {jobDetail?.assignedExecutorId || '-'}
                            </Descriptions.Item>
                            <Descriptions.Item label="插件">{jobDetail?.pluginId || '-'}</Descriptions.Item>
                            <Descriptions.Item label="round">{jobDetail?.roundIndex || jobDetail?.iteration || '-'}</Descriptions.Item>
                            <Descriptions.Item label="采样策略">{jobDetail?.queryStrategy || '-'}</Descriptions.Item>
                            <Descriptions.Item label="开始时间">{formatDateTime(jobDetail?.startedAt)}</Descriptions.Item>
                            <Descriptions.Item label="结束时间">{formatDateTime(jobDetail?.endedAt)}</Descriptions.Item>
                            <Descriptions.Item label="制品数量">{artifactsCount}</Descriptions.Item>
                            <Descriptions.Item label="验证集降级">
                                {(Number(jobDetail?.metrics?.valDegraded || 0) > 0.5)
                                    ? <Tag color="warning">是</Tag>
                                    : <Tag color="default">否</Tag>}
                            </Descriptions.Item>
                        </Descriptions>
                        {jobDetail?.lastError ? (
                            <Alert type="error" showIcon className="mt-3" message={jobDetail.lastError}/>
                        ) : null}
                        <Paragraph className="!mb-0 !mt-3">
                            <Text type="secondary">超参：{JSON.stringify(jobDetail?.params || {})}</Text>
                        </Paragraph>
                    </Card>

                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                        <div className="min-w-0 lg:col-span-7">
                            <Card className="!border-github-border !bg-github-panel" title="训练曲线">
                                {metricChartData.length === 0 ? (
                                    <Empty description="暂无指标曲线"/>
                                ) : (
                                    <div className="h-[320px]">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <LineChart data={metricChartData}>
                                                <CartesianGrid strokeDasharray="3 3"/>
                                                <XAxis dataKey="step"/>
                                                <YAxis/>
                                                <Tooltip/>
                                                {metricNames.map((name, idx) => (
                                                    <Line
                                                        key={name}
                                                        type="monotone"
                                                        dataKey={name}
                                                        dot={false}
                                                        stroke={['#1677ff', '#52c41a', '#faad14', '#13c2c2', '#eb2f96'][idx % 5]}
                                                        strokeWidth={2}
                                                    />
                                                ))}
                                            </LineChart>
                                        </ResponsiveContainer>
                                    </div>
                                )}
                            </Card>
                        </div>
                        <div className="min-w-0 lg:col-span-5">
                            <Card className="!border-github-border !bg-github-panel" title="实时日志（最新 200 条）">
                                <List
                                    size="small"
                                    dataSource={events.slice(-200)}
                                    locale={{emptyText: '暂无日志'}}
                                    className="max-h-[320px] overflow-auto"
                                    renderItem={(item) => (
                                        <List.Item className="!items-start">
                                            <div className="w-full">
                                                <div className="text-xs text-github-muted">
                                                    #{item.seq} · {formatDateTime(item.ts)}
                                                </div>
                                                <div className="font-mono text-xs whitespace-pre-wrap break-all">
                                                    {eventToText(item)}
                                                </div>
                                            </div>
                                        </List.Item>
                                    )}
                                />
                            </Card>
                        </div>
                    </div>

                    <Card className="!border-github-border !bg-github-panel" title="TopK 候选样本">
                        <Table
                            size="small"
                            pagination={{pageSize: 10, showSizeChanger: false}}
                            dataSource={topkDataSource}
                            rowKey={(item) => item.sampleId}
                            columns={[
                                {title: '#', dataIndex: 'rank', width: 60},
                                {
                                    title: 'Sample ID',
                                    dataIndex: 'sampleId',
                                    render: (value: string) => <Text code>{value}</Text>,
                                },
                                {
                                    title: 'Score',
                                    dataIndex: 'score',
                                    width: 220,
                                    render: (value: number) => (
                                        <div className="flex w-full flex-col gap-0.5">
                                            <Progress percent={Math.max(0, Math.min(100, Number((value * 100).toFixed(2))))}/>
                                            <Text type="secondary">{value.toFixed(6)}</Text>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Detail',
                                    dataIndex: 'extra',
                                    render: (value: Record<string, any>) => (
                                        <Text type="secondary">{JSON.stringify(value || {})}</Text>
                                    ),
                                },
                            ]}
                        />
                    </Card>
                </>
            )}

            <Card className="!border-github-border !bg-github-panel" title="模型制品">
                {models.length === 0 ? (
                    <Empty description="暂无模型记录"/>
                ) : (
                    <Table
                        size="small"
                        rowKey={(item) => item.id}
                        dataSource={models}
                        pagination={{pageSize: 8}}
                        columns={[
                            {title: '名称', dataIndex: 'name'},
                            {title: '版本', dataIndex: 'versionTag', width: 120},
                            {title: '状态', dataIndex: 'status', width: 120, render: (v: string) => <Tag>{v}</Tag>},
                            {title: '插件', dataIndex: 'pluginId', width: 140},
                            {
                                title: '父模型',
                                width: 120,
                                render: (_value: unknown, row: ProjectModel) => (
                                    row.parentModelId ? <Text code>{row.parentModelId.slice(0, 8)}</Text> : '-'
                                ),
                            },
                            {
                                title: 'mAP50',
                                width: 100,
                                render: (_value: unknown, row: ProjectModel) => Number(row.metrics?.map50 || 0).toFixed(4),
                            },
                            {title: '创建时间', dataIndex: 'createdAt', render: (v: string) => formatDateTime(v)},
                            {
                                title: '操作',
                                width: 240,
                                render: (_value: unknown, row: ProjectModel) => (
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Button size="small" loading={modelLoading} onClick={() => handleDownloadModel(row)}>
                                            下载制品
                                        </Button>
                                        <Button
                                            size="small"
                                            type="primary"
                                            loading={modelLoading}
                                            disabled={row.status === 'production'}
                                            onClick={() => handlePromoteModel(row.id)}
                                        >
                                            晋升生产
                                        </Button>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
            </Card>

            <Modal
                title="失败后恢复"
                open={recoverOpen}
                onCancel={() => setRecoverOpen(false)}
                onOk={handleRecoverLoop}
                confirmLoading={recoverLoading}
                okText="确认恢复"
                destroyOnClose
            >
                <Form form={recoverForm} layout="vertical">
                    <Form.Item name="mode" label="恢复模式" initialValue="retry_same_params">
                        <Radio.Group>
                            <Radio value="retry_same_params">快速重试（沿用参数）</Radio>
                            <Radio value="rerun_with_overrides">按新参数重跑（同轮新建 job）</Radio>
                        </Radio.Group>
                    </Form.Item>
                    {recoverMode === 'rerun_with_overrides' ? (
                        <>
                            <Form.Item name="pluginId" label="插件 ID">
                                <Input placeholder="例如：yolo_det_v1"/>
                            </Form.Item>
                            <Form.Item name="queryStrategy" label="采样策略">
                                <Input placeholder="例如：aug_iou_disagreement"/>
                            </Form.Item>
                            <Form.Item name="paramsJson" label="params(JSON)">
                                <Input.TextArea rows={6}/>
                            </Form.Item>
                            <Form.Item name="resourcesJson" label="resources(JSON)">
                                <Input.TextArea rows={4}/>
                            </Form.Item>
                        </>
                    ) : null}
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectLoops;
