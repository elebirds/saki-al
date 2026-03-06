import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button, Card, Form, Modal, Select, Slider, Space, Table, Tag, Typography, message} from 'antd';
import {PlusOutlined, ReloadOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {useParams} from 'react-router-dom';
import {api} from '../../../services/api';
import {
    CommitHistoryItem,
    PredictionCreateRequest,
    RuntimeRoundEvent,
    PredictionTaskRead,
    ProjectBranch,
    ProjectModel,
    RuntimePluginCatalogItem,
} from '../../../types';
import RoundConsolePanel from './components/RoundConsolePanel';
import {mergeRuntimeRoundEvents} from './runtimeEventFormatter';

const statusColor: Record<string, string> = {
    queued: 'default',
    running: 'processing',
    materializing: 'processing',
    ready: 'success',
    applied: 'success',
    failed: 'error',
};

type ScopeStatus = 'all' | 'unlabeled' | 'labeled' | 'draft';

interface TaskFormValues {
    pluginId: string;
    modelId?: string;
    artifactName?: string;
    targetBranchId: string;
    baseCommitId: string;
    predictConf?: number;
    scopeStatus: ScopeStatus;
}

const ProjectPredictionTasks: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const [messageApi, contextHolder] = message.useMessage();
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [createOpen, setCreateOpen] = useState(false);
    const [tasks, setTasks] = useState<PredictionTaskRead[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [models, setModels] = useState<ProjectModel[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [branchCommits, setBranchCommits] = useState<CommitHistoryItem[]>([]);
    const [selectedTaskId, setSelectedTaskId] = useState<string>('');
    const [taskConsoleEvents, setTaskConsoleEvents] = useState<RuntimeRoundEvent[]>([]);
    const [taskConsoleLoading, setTaskConsoleLoading] = useState(false);
    const taskAfterSeqRef = useRef<number>(0);
    const [form] = Form.useForm<TaskFormValues>();
    const pluginId = Form.useWatch('pluginId', form);
    const modelId = Form.useWatch('modelId', form);

    const predictPluginIds = useMemo(
        () => plugins
            .filter((item) => (item.supportedTaskTypes || []).map((v) => String(v).toLowerCase()).includes('predict'))
            .map((item) => item.pluginId),
        [plugins],
    );

    const pluginOptions = useMemo(() => {
        const fromModels = models.map((item) => String(item.pluginId || '').trim()).filter(Boolean);
        const merged = new Set<string>([...predictPluginIds, ...fromModels]);
        return Array.from(merged).sort((a, b) => a.localeCompare(b));
    }, [models, predictPluginIds]);

    const scopedModelOptions = useMemo(() => {
        if (!pluginId) return models;
        return models.filter((item) => String(item.pluginId || '') === String(pluginId));
    }, [models, pluginId]);

    const artifactOptions = useMemo(() => {
        const model = scopedModelOptions.find((item) => item.id === modelId);
        const names = model && model.artifacts && typeof model.artifacts === 'object'
            ? Object.keys(model.artifacts).filter((name) => Boolean(String(name || '').trim()))
            : [];
        const unique = Array.from(new Set<string>(names));
        if (unique.length === 0) {
            return [{value: 'best.pt', label: 'best.pt'}];
        }
        return unique.sort((a, b) => a.localeCompare(b)).map((name) => ({value: name, label: name}));
    }, [modelId, scopedModelOptions]);

    const commitOptions = useMemo(() => {
        return branchCommits.map((item) => {
            const hash = String(item.commitHash || '').slice(0, 8) || String(item.id || '').slice(0, 8);
            const message = String(item.message || '').trim() || '(no message)';
            return {
                value: item.id,
                label: `${hash}  ${message}`,
            };
        });
    }, [branchCommits]);

    const refresh = useCallback(async () => {
        if (!projectId) return;
        setLoading(true);
        try {
            const [taskRows, branchRows, modelRows, pluginCatalog] = await Promise.all([
                api.listPredictionTasks(projectId, 100),
                api.getProjectBranches(projectId),
                api.getProjectModels(projectId, 100).catch(() => []),
                api.getRuntimePlugins().catch(() => ({items: []})),
            ]);
            setTasks(taskRows);
            setBranches(branchRows);
            setModels(modelRows);
            setPlugins(Array.isArray(pluginCatalog?.items) ? pluginCatalog.items : []);
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.messages.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [api, projectId, messageApi, t]);

    const loadBranchCommits = useCallback(async (branchId?: string) => {
        if (!projectId) return;
        const branch = branches.find((item) => item.id === branchId);
        if (!branch?.headCommitId) {
            setBranchCommits([]);
            form.setFieldValue('baseCommitId', '');
            return;
        }
        try {
            const rows = await api.getCommitHistory(branch.headCommitId, 100);
            const commits = Array.isArray(rows) ? rows : [];
            setBranchCommits(commits);
            const current = String(form.getFieldValue('baseCommitId') || '').trim();
            const exists = commits.some((item) => item.id === current);
            if (!exists) {
                form.setFieldValue('baseCommitId', commits[0]?.id || branch.headCommitId);
            }
        } catch (_error) {
            const fallback: CommitHistoryItem[] = [{
                id: branch.headCommitId,
                commitHash: branch.headCommitId.slice(0, 8),
                message: branch.headCommitMessage || '(head commit)',
                authorType: 'system',
                createdAt: '',
            }];
            setBranchCommits(fallback);
            form.setFieldValue('baseCommitId', branch.headCommitId);
        }
    }, [api, branches, form, projectId]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    const onOpenCreate = useCallback(() => {
        const defaultBranch = branches[0];
        const defaultPluginId = String(models[0]?.pluginId || pluginOptions[0] || '').trim();
        const defaultModels = defaultPluginId
            ? models.filter((item) => String(item.pluginId || '').trim() === defaultPluginId)
            : models;
        form.setFieldsValue({
            pluginId: defaultPluginId,
            modelId: defaultModels[0]?.id,
            artifactName: 'best.pt',
            targetBranchId: defaultBranch?.id,
            baseCommitId: defaultBranch?.headCommitId,
            predictConf: 0.1,
            scopeStatus: 'all',
        });
        void loadBranchCommits(defaultBranch?.id);
        setCreateOpen(true);
    }, [branches, form, loadBranchCommits, models, pluginOptions]);

    const onPluginChanged = useCallback((nextPluginId?: string) => {
        const normalized = String(nextPluginId || '').trim();
        if (!normalized) return;
        const candidateModels = models.filter((item) => String(item.pluginId || '') === normalized);
        const currentModelId = String(form.getFieldValue('modelId') || '').trim();
        if (!candidateModels.some((item) => item.id === currentModelId)) {
            form.setFieldValue('modelId', candidateModels[0]?.id || undefined);
        }
    }, [form, models]);

    const onBranchChanged = useCallback((branchId?: string) => {
        void loadBranchCommits(branchId);
    }, [loadBranchCommits]);

    useEffect(() => {
        const current = String(form.getFieldValue('artifactName') || '').trim();
        const values = artifactOptions.map((item) => String(item.value || '').trim()).filter(Boolean);
        if (values.length === 0) {
            if (current !== 'best.pt') {
                form.setFieldValue('artifactName', 'best.pt');
            }
            return;
        }
        if (!values.includes(current)) {
            form.setFieldValue('artifactName', values[0]);
        }
    }, [artifactOptions, form]);

    useEffect(() => {
        const branchId = String(form.getFieldValue('targetBranchId') || '').trim() || branches[0]?.id;
        if (!branchId) return;
        void loadBranchCommits(branchId);
    }, [branches, form, loadBranchCommits]);

    const selectedTask = useMemo(
        () => tasks.find((item) => item.id === selectedTaskId) || null,
        [tasks, selectedTaskId],
    );

    const toTaskConsoleEvent = useCallback((task: PredictionTaskRead, event: any): RuntimeRoundEvent => ({
        ...event,
        taskId: String(task.taskId || ''),
        taskIndex: 1,
        taskType: 'predict',
        stage: 'custom',
    }), []);

    const loadTaskConsoleEvents = useCallback(async (task: PredictionTaskRead, reset: boolean) => {
        const taskId = String(task.taskId || '').trim();
        if (!taskId) return;
        const afterSeq = reset ? 0 : Number(taskAfterSeqRef.current || 0);
        if (reset) setTaskConsoleLoading(true);
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
        } catch (error: any) {
            if (reset) {
                messageApi.error(error?.message || '加载任务日志失败');
            }
        } finally {
            if (reset) setTaskConsoleLoading(false);
        }
    }, [messageApi, toTaskConsoleEvent]);

    useEffect(() => {
        if (!selectedTask) {
            setTaskConsoleEvents([]);
            taskAfterSeqRef.current = 0;
            return;
        }
        taskAfterSeqRef.current = 0;
        void loadTaskConsoleEvents(selectedTask, true);
    }, [selectedTask, loadTaskConsoleEvents]);

    useEffect(() => {
        if (!selectedTask) return;
        const activeStatuses = new Set([
            'pending',
            'ready',
            'dispatching',
            'syncing_env',
            'probing_runtime',
            'binding_device',
            'running',
            'retrying',
        ]);
        const status = String(selectedTask.taskStatus || selectedTask.status || '').toLowerCase();
        if (!activeStatuses.has(status)) return;
        const timer = window.setInterval(() => {
            void loadTaskConsoleEvents(selectedTask, false);
        }, 3000);
        return () => window.clearInterval(timer);
    }, [selectedTask, loadTaskConsoleEvents]);

    const onCreateTask = useCallback(async () => {
        if (!projectId) return;
        try {
            const values = await form.validateFields();
            const payload: PredictionCreateRequest = {
                modelId: String(values.modelId || ''),
                artifactName: values.artifactName || 'best.pt',
                targetBranchId: values.targetBranchId,
                baseCommitId: values.baseCommitId,
                predictConf: values.predictConf,
                scopeType: 'sample_status',
                scopePayload: {status: values.scopeStatus},
            };
            setSubmitting(true);
            await api.createPrediction(projectId, payload);
            messageApi.success(t('project.predictionTasks.messages.createSuccess'));
            setCreateOpen(false);
            await refresh();
        } catch (error: any) {
            if (error?.errorFields) return;
            messageApi.error(error?.message || t('project.predictionTasks.messages.createFailed'));
        } finally {
            setSubmitting(false);
        }
    }, [api, form, messageApi, projectId, refresh, t]);

    const onApply = useCallback(async (taskId: string) => {
        try {
            const result = await api.applyPrediction(taskId, {});
            messageApi.success(t('project.predictionTasks.messages.applySuccess', {count: result.appliedCount}));
            await refresh();
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.messages.applyFailed'));
        }
    }, [api, messageApi, refresh, t]);

    return (
        <div className="p-6 space-y-4">
            {contextHolder}
            <Space className="w-full justify-between">
                <Typography.Title level={4} className="!mb-0">Prediction Tasks</Typography.Title>
                <Space>
                    <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>{t('project.predictionTasks.refresh')}</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={onOpenCreate}>{t('project.predictionTasks.newTask')}</Button>
                </Space>
            </Space>

            <Card>
                <Table<PredictionTaskRead>
                    rowKey="id"
                    loading={loading}
                    dataSource={tasks}
                    rowSelection={{
                        type: 'radio',
                        selectedRowKeys: selectedTaskId ? [selectedTaskId] : [],
                        onChange: (keys) => setSelectedTaskId(String(keys[0] || '')),
                    }}
                    onRow={(row) => ({
                        onClick: () => setSelectedTaskId(row.id),
                    })}
                    pagination={{pageSize: 20}}
                    columns={[
                        {
                            title: t('project.predictionTasks.table.taskId'),
                            dataIndex: 'id',
                            width: 260,
                            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
                        },
                        {
                            title: 'Task ID',
                            dataIndex: 'taskId',
                            width: 260,
                            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
                        },
                        {
                            title: t('project.predictionTasks.table.status'),
                            dataIndex: 'status',
                            width: 130,
                            render: (value: string) => <Tag color={statusColor[value] || 'default'}>{value}</Tag>,
                        },
                        {
                            title: 'Plugin',
                            dataIndex: 'pluginId',
                            width: 180,
                        },
                        {
                            title: t('project.predictionTasks.table.totalItems'),
                            dataIndex: 'totalItems',
                            width: 100,
                        },
                        {
                            title: t('project.predictionTasks.table.error'),
                            dataIndex: 'lastError',
                            render: (value?: string | null) => value || '-',
                        },
                        {
                            title: t('project.predictionTasks.table.actions'),
                            key: 'actions',
                            width: 120,
                            render: (_, row) => (
                                <Space>
                                    <Button
                                        size="small"
                                        type="primary"
                                        disabled={row.status !== 'ready'}
                                        onClick={() => void onApply(row.id)}
                                    >
                                        {t('project.predictionTasks.actions.apply')}
                                    </Button>
                                </Space>
                            ),
                        },
                    ]}
                />
            </Card>

            <RoundConsolePanel
                title={selectedTask ? `Task 日志：${selectedTask.taskId}` : 'Task 日志'}
                wsConnected={!taskConsoleLoading}
                events={taskConsoleEvents}
                onClearBuffer={() => {
                    taskAfterSeqRef.current = 0;
                    setTaskConsoleEvents([]);
                }}
                emptyDescription={selectedTask ? '暂无任务日志' : '请选择一个 Prediction Task 查看日志'}
                exportFilePrefix={selectedTask ? `prediction-task-${selectedTask.taskId}` : 'prediction-task'}
                maxHeight={420}
            />

            <Modal
                title={t('project.predictionTasks.modal.title')}
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={() => void onCreateTask()}
                confirmLoading={submitting}
                okText={t('project.predictionTasks.modal.okText')}
            >
                <Form<TaskFormValues> form={form} layout="vertical">
                    <Form.Item label={t('project.predictionTasks.form.plugin')} name="pluginId" rules={[{required: true}]} extra={t('project.predictionTasks.form.pluginExtra')}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            onChange={onPluginChanged}
                            options={pluginOptions.map((id) => ({
                                value: id,
                                label: id,
                            }))}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.model')} name="modelId" rules={[{required: true}]}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={scopedModelOptions.map((item) => ({
                                value: item.id,
                                label: `${item.name} (${item.versionTag})`,
                            }))}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.artifactName')} name="artifactName" initialValue="best.pt" rules={[{required: true}]}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={artifactOptions}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.targetBranch')} name="targetBranchId" rules={[{required: true}]}>
                        <Select
                            options={branches.map((item) => ({
                                value: item.id,
                                label: item.name,
                            }))}
                            onChange={onBranchChanged}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.baseCommit')} name="baseCommitId" rules={[{required: true}]}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={commitOptions}
                            placeholder={t('project.predictionTasks.form.baseCommitPlaceholder')}
                        />
                    </Form.Item>
                    <Form.Item
                        label={t('project.predictionTasks.form.predictConf')}
                        name="predictConf"
                        tooltip={t('project.predictionTasks.form.predictConfTooltip')}
                        rules={[{required: true}]}
                    >
                        <Slider
                            min={0}
                            max={1}
                            step={0.001}
                            marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                            tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.scopeStatus')} name="scopeStatus" rules={[{required: true}]}>
                        <Select
                            options={[
                                {value: 'all', label: t('project.predictionTasks.scope.all')},
                                {value: 'unlabeled', label: t('project.predictionTasks.scope.unlabeled')},
                                {value: 'labeled', label: t('project.predictionTasks.scope.labeled')},
                                {value: 'draft', label: t('project.predictionTasks.scope.draft')},
                            ]}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectPredictionTasks;
