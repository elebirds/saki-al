import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Alert, App, Button, Card, Descriptions, Empty, Space, Spin, Table, Tag, Typography} from 'antd';
import {ArrowLeftOutlined, ReloadOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {
    PredictionDetailRead,
    PredictionRead,
    RuntimeRoundEvent,
    TaskArtifactRead,
} from '../../../types';
import RoundConsolePanel from './components/RoundConsolePanel';
import TaskArtifactTableCard, {TaskArtifactTableRow} from './components/TaskArtifactTableCard';
import {mergeRuntimeRoundEvents} from './runtimeEventFormatter';
import {formatDateTime} from './runtimeTime';
import {buildArtifactKey} from './roundDetail/transforms';

const statusColor: Record<string, string> = {
    queued: 'default',
    running: 'processing',
    materializing: 'processing',
    ready: 'success',
    applied: 'success',
    failed: 'error',
};

const taskStatusColor: Record<string, string> = {
    pending: 'default',
    ready: 'processing',
    dispatching: 'processing',
    syncing_env: 'processing',
    probing_runtime: 'processing',
    binding_device: 'processing',
    running: 'processing',
    retrying: 'warning',
    succeeded: 'success',
    failed: 'error',
    cancelled: 'default',
    skipped: 'default',
};

const ACTIVE_TASK_STATUSES = new Set([
    'pending',
    'ready',
    'dispatching',
    'syncing_env',
    'probing_runtime',
    'binding_device',
    'running',
    'retrying',
]);

const ACTIVE_PREDICTION_STATUSES = new Set(['queued', 'running', 'materializing']);

const toTaskConsoleEvent = (task: PredictionRead, event: any): RuntimeRoundEvent => ({
    ...event,
    taskId: String(task.taskId || ''),
    taskIndex: 1,
    taskType: 'predict',
    stage: 'custom',
});

const toTaskArtifactRow = (taskId: string, item: TaskArtifactRead): TaskArtifactTableRow => {
    const meta = item && typeof item.meta === 'object' ? item.meta : {};
    const sizeValue = Number((meta as any).size ?? (meta as any).file_size ?? (meta as any).fileSize ?? 0);
    const createdAtRaw = (meta as any).createdAt ?? (meta as any).created_at ?? null;
    return {
        key: buildArtifactKey(taskId, item.name),
        taskId,
        name: String(item.name || ''),
        kind: String(item.kind || ''),
        uri: String(item.uri || ''),
        size: Number.isFinite(sizeValue) && sizeValue > 0 ? sizeValue : null,
        createdAt: typeof createdAtRaw === 'string' ? createdAtRaw : null,
    };
};

const ProjectPredictionTaskDetail: React.FC = () => {
    const {t} = useTranslation();
    const {message: messageApi} = App.useApp();
    const navigate = useNavigate();
    const {projectId, predictionId} = useParams<{ projectId: string; predictionId: string }>();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [applying, setApplying] = useState(false);
    const [consoleLoading, setConsoleLoading] = useState(false);
    const [consoleConnected, setConsoleConnected] = useState(false);
    const [detail, setDetail] = useState<PredictionDetailRead | null>(null);
    const [taskArtifacts, setTaskArtifacts] = useState<TaskArtifactRead[]>([]);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});
    const artifactUrlsRef = useRef<Record<string, string>>({});
    const [taskConsoleEvents, setTaskConsoleEvents] = useState<RuntimeRoundEvent[]>([]);
    const taskAfterSeqRef = useRef<number>(0);
    const pollingRef = useRef(false);

    useEffect(() => {
        artifactUrlsRef.current = artifactUrls;
    }, [artifactUrls]);

    const resolveArtifactUrl = useCallback(async (row: TaskArtifactTableRow): Promise<string | null> => {
        const taskId = String(row.taskId || '').trim();
        const artifactName = String(row.name || '').trim();
        if (!taskId || !artifactName) return null;
        const key = buildArtifactKey(taskId, artifactName);
        const cached = artifactUrlsRef.current[key];
        if (cached) return cached;
        const directUri = String(row.uri || '').trim();
        if (directUri.startsWith('http://') || directUri.startsWith('https://')) {
            setArtifactUrls((prev) => ({...prev, [key]: directUri}));
            return directUri;
        }
        const download = await api.getTaskArtifactDownloadUrl(taskId, artifactName, 2);
        const url = String(download.downloadUrl || '').trim();
        if (!url) return null;
        setArtifactUrls((prev) => ({...prev, [key]: url}));
        return url;
    }, []);

    const loadTaskConsoleEvents = useCallback(async (task: PredictionRead, reset: boolean) => {
        const taskId = String(task.taskId || '').trim();
        if (!taskId) return;
        const afterSeq = reset ? 0 : Number(taskAfterSeqRef.current || 0);
        if (reset) setConsoleLoading(true);
        try {
            const response = await api.getTaskEvents(taskId, {
                afterSeq,
                limit: 5000,
                includeFacets: false,
            });
            const incoming = (response.items || []).map((item) => toTaskConsoleEvent(task, item));
            if (reset) {
                setTaskConsoleEvents(incoming);
            } else if (incoming.length > 0) {
                setTaskConsoleEvents((prev) => mergeRuntimeRoundEvents(prev, incoming, 20000));
            }
            const next = Number(response.nextAfterSeq ?? afterSeq ?? 0);
            taskAfterSeqRef.current = Number.isFinite(next) && next >= 0 ? next : afterSeq;
            setConsoleConnected(true);
        } catch {
            setConsoleConnected(false);
        } finally {
            if (reset) setConsoleLoading(false);
        }
    }, []);

    const loadDetail = useCallback(async (silent: boolean, resetConsole: boolean) => {
        if (!projectId || !predictionId) return null;
        if (!silent) setLoading(true);
        if (silent) setRefreshing(true);
        try {
            const detailRow = await api.getPredictionDetail(predictionId, 2000);
            setDetail(detailRow);

            const taskId = String(detailRow.prediction.taskId || '').trim();
            if (taskId) {
                const artifactResponse = await api.getTaskArtifacts(taskId);
                const artifacts = artifactResponse.artifacts || [];
                setTaskArtifacts(artifacts);
            } else {
                setTaskArtifacts([]);
            }

            if (resetConsole) {
                taskAfterSeqRef.current = 0;
                setTaskConsoleEvents([]);
                if (taskId) {
                    await loadTaskConsoleEvents(detailRow.prediction, true);
                }
            }
            return detailRow;
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.detail.messages.loadFailed'));
            return null;
        } finally {
            if (!silent) setLoading(false);
            if (silent) setRefreshing(false);
        }
    }, [projectId, predictionId, messageApi, t, loadTaskConsoleEvents]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadDetail(false, true);
    }, [canManageLoops, loadDetail]);

    useEffect(() => {
        if (!detail?.prediction) return;
        const taskState = String(detail.prediction.taskStatus || '').toLowerCase();
        const predictionState = String(detail.prediction.status || '').toLowerCase();
        const shouldPoll = ACTIVE_TASK_STATUSES.has(taskState) || ACTIVE_PREDICTION_STATUSES.has(predictionState);
        if (!shouldPoll) return;
        const timer = window.setInterval(() => {
            if (pollingRef.current) return;
            pollingRef.current = true;
            void (async () => {
                try {
                    const latest = await loadDetail(true, false);
                    if (latest?.prediction) {
                        await loadTaskConsoleEvents(latest.prediction, false);
                    }
                } finally {
                    pollingRef.current = false;
                }
            })();
        }, 3000);
        return () => window.clearInterval(timer);
    }, [detail?.prediction, loadDetail, loadTaskConsoleEvents]);

    const onApplyPrediction = useCallback(async () => {
        if (!detail?.prediction?.id) return;
        try {
            setApplying(true);
            const result = await api.applyPrediction(detail.prediction.id, {});
            messageApi.success(t('project.predictionTasks.messages.applySuccess', {count: result.appliedCount}));
            await loadDetail(true, false);
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.messages.applyFailed'));
        } finally {
            setApplying(false);
        }
    }, [detail?.prediction?.id, api, messageApi, t, loadDetail]);

    const artifactRows = useMemo<TaskArtifactTableRow[]>(() => {
        const taskId = String(detail?.prediction?.taskId || '').trim();
        if (!taskId) return [];
        return taskArtifacts.map((item) => toTaskArtifactRow(taskId, item));
    }, [detail?.prediction?.taskId, taskArtifacts]);

    if (!canManageLoops) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" showIcon message="暂无权限访问 Prediction 页面"/>
            </Card>
        );
    }

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!detail?.prediction) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description={t('project.predictionTasks.detail.empty')}/>
            </Card>
        );
    }

    const prediction = detail.prediction;
    const predictionStatus = String(prediction.status || '').toLowerCase();
    const taskStatus = String(prediction.taskStatus || '').toLowerCase();

    return (
        <div className="p-6 space-y-4">
            <Space className="w-full justify-between">
                <Space>
                    <Button icon={<ArrowLeftOutlined/>} onClick={() => navigate(`/projects/${projectId}/prediction-tasks`)}>
                        {t('common.back')}
                    </Button>
                    <Typography.Title level={4} className="!mb-0">
                        {t('project.predictionTasks.detail.title')}
                    </Typography.Title>
                </Space>
                <Space>
                    <Button icon={<ReloadOutlined/>} loading={refreshing} onClick={() => void loadDetail(true, false)}>
                        {t('project.predictionTasks.refresh')}
                    </Button>
                    <Button
                        type="primary"
                        loading={applying}
                        disabled={!['ready', 'applied'].includes(predictionStatus)}
                        onClick={() => void onApplyPrediction()}
                    >
                        {t('project.predictionTasks.actions.apply')}
                    </Button>
                </Space>
            </Space>

            <Card className="!border-github-border !bg-github-panel" title={t('project.predictionTasks.detail.summaryTitle')}>
                <Descriptions column={3} size="small" bordered>
                    <Descriptions.Item label="Prediction ID">
                        <Typography.Text code>{prediction.id}</Typography.Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="Task ID">
                        <Typography.Text code>{prediction.taskId}</Typography.Text>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('project.predictionTasks.table.status')}>
                        <Tag color={statusColor[predictionStatus] || 'default'}>{predictionStatus || '-'}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="Task 状态">
                        <Tag color={taskStatusColor[taskStatus] || 'default'}>{taskStatus || '-'}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="Plugin">{prediction.pluginId || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Model">
                        <Typography.Text code>{prediction.modelId}</Typography.Text>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('project.predictionTasks.table.totalItems')}>
                        {Number(prediction.totalItems || 0)}
                    </Descriptions.Item>
                    <Descriptions.Item label="范围">
                        {String((prediction.scopePayload || {}).status || prediction.scopeType || '-')}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('project.predictionTasks.table.error')}>
                        {prediction.lastError || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="创建时间">{formatDateTime(prediction.createdAt)}</Descriptions.Item>
                    <Descriptions.Item label="更新时间">{formatDateTime(prediction.updatedAt)}</Descriptions.Item>
                    <Descriptions.Item label="Base Commit">
                        <Typography.Text code>{prediction.baseCommitId || '-'}</Typography.Text>
                    </Descriptions.Item>
                </Descriptions>
            </Card>

            <TaskArtifactTableCard
                title={t('project.predictionTasks.detail.artifactsTitle')}
                emptyDescription={t('project.predictionTasks.detail.artifactsEmpty')}
                rows={artifactRows}
                artifactUrls={artifactUrls}
                resolveArtifactUrl={resolveArtifactUrl}
            />

            <Card className="!border-github-border !bg-github-panel" title={t('project.predictionTasks.detail.itemsTitle')}>
                <Table
                    size="small"
                    rowKey={(row: any) => `${row.sampleId}-${row.rank}`}
                    dataSource={detail.items || []}
                    pagination={{pageSize: 20}}
                    columns={[
                        {title: '#', dataIndex: 'rank', width: 80},
                        {
                            title: 'Sample ID',
                            dataIndex: 'sampleId',
                            width: 280,
                            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
                        },
                        {
                            title: 'Label ID',
                            dataIndex: 'labelId',
                            width: 280,
                            render: (value?: string | null) => (value ? <Typography.Text code>{value}</Typography.Text> : '-'),
                        },
                        {
                            title: 'Score',
                            dataIndex: 'score',
                            width: 100,
                            render: (value: number) => Number(value || 0).toFixed(4),
                        },
                        {
                            title: 'Confidence',
                            dataIndex: 'confidence',
                            width: 120,
                            render: (value: number) => Number(value || 0).toFixed(4),
                        },
                    ]}
                />
            </Card>

            <RoundConsolePanel
                title={t('project.predictionTasks.detail.consoleTitle')}
                wsConnected={consoleConnected && !consoleLoading}
                events={taskConsoleEvents}
                onClearBuffer={() => {
                    taskAfterSeqRef.current = 0;
                    setTaskConsoleEvents([]);
                    if (prediction.taskId) {
                        void loadTaskConsoleEvents(prediction, true);
                    }
                }}
                emptyDescription={t('project.predictionTasks.detail.consoleEmpty')}
                exportFilePrefix={`prediction-task-${prediction.taskId}`}
                maxHeight={520}
            />
        </div>
    );
};

export default ProjectPredictionTaskDetail;
