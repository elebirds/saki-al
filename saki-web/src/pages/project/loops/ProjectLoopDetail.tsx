import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Form,
    Input,
    InputNumber,
    Select,
    Spin,
    Switch,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {api} from '../../../services/api';
import {
    ALLoop,
    LoopSummary,
    LoopUpdateRequest,
    RuntimeJob,
    RuntimePluginCatalogItem,
    RuntimeRequestConfigField,
} from '../../../types';

const {Title, Text} = Typography;

const LOOP_STATUS_COLOR: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    stopped: 'default',
    completed: 'success',
    failed: 'error',
};

const JOB_STATUS_COLOR: Record<string, string> = {
    job_pending: 'default',
    job_running: 'processing',
    job_succeeded: 'success',
    job_partial_failed: 'warning',
    job_failed: 'error',
    job_cancelled: 'warning',
};

type LoopConfigForm = {
    name: string;
    mode: 'active_learning' | 'simulation' | 'manual';
    modelArch: string;
    queryStrategy: string;
    maxRounds: number;
    queryBatchSize: number;
    minSeedLabeled: number;
    minNewLabelsPerRound: number;
    stopPatienceRounds: number;
    stopMinGain: number;
    autoRegisterModel: boolean;
    modelRequestConfig: Record<string, any>;
    simulationConfig: {
        oracleCommitId?: string | null;
        seedRatio: number;
        stepRatio: number;
        maxRounds: number;
        randomBaselineEnabled?: boolean;
        seeds: Array<number | string>;
    };
};

const ProjectLoopDetail: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [controlLoading, setControlLoading] = useState(false);
    const [loop, setLoop] = useState<ALLoop | null>(null);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [jobs, setJobs] = useState<RuntimeJob[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [configForm] = Form.useForm<LoopConfigForm>();

    const selectedPluginId = Form.useWatch('modelArch', configForm);
    const selectedMode = Form.useWatch('mode', configForm) || 'active_learning';
    const selectedPlugin = useMemo(
        () => plugins.find((item) => item.pluginId === selectedPluginId),
        [plugins, selectedPluginId],
    );

    const renderDynamicField = (field: RuntimeRequestConfigField) => {
        const keyPath: (string | number)[] = ['modelRequestConfig', field.key];
        const rules = field.required ? [{required: true, message: `${field.label} 必填`}] : undefined;
        if (field.type === 'boolean') {
            return (
                <Form.Item key={field.key} name={keyPath} label={field.label} valuePropName="checked">
                    <Switch/>
                </Form.Item>
            );
        }
        if (field.type === 'integer' || field.type === 'number') {
            return (
                <Form.Item key={field.key} name={keyPath} label={field.label} rules={rules}>
                    <InputNumber
                        className="w-full"
                        min={field.min}
                        max={field.max}
                        step={field.type === 'integer' ? 1 : 0.0001}
                    />
                </Form.Item>
            );
        }
        if (field.type === 'select') {
            return (
                <Form.Item key={field.key} name={keyPath} label={field.label} rules={rules}>
                    <Select options={(field.options || []).map((item) => ({label: item.label, value: item.value}))}/>
                </Form.Item>
            );
        }
        return (
            <Form.Item key={field.key} name={keyPath} label={field.label} rules={rules}>
                <Input/>
            </Form.Item>
        );
    };

    const refreshLoopData = useCallback(async () => {
        if (!loopId) return;
        const [loopRow, summaryRow, jobRows, pluginCatalog] = await Promise.all([
            api.getLoopById(loopId),
            api.getLoopSummary(loopId),
            api.getLoopJobs(loopId, 100),
            api.getRuntimePlugins(),
        ]);
        setLoop(loopRow);
        setSummary(summaryRow);
        setJobs(jobRows);
        setPlugins(pluginCatalog.items || []);

        const plugin = pluginCatalog.items.find((item) => item.pluginId === loopRow.modelArch);
        configForm.setFieldsValue({
            name: loopRow.name,
            mode: loopRow.mode || 'active_learning',
            modelArch: loopRow.modelArch,
            queryStrategy: loopRow.queryStrategy,
            maxRounds: loopRow.maxRounds,
            queryBatchSize: loopRow.queryBatchSize,
            minSeedLabeled: loopRow.minSeedLabeled,
            minNewLabelsPerRound: loopRow.minNewLabelsPerRound,
            stopPatienceRounds: loopRow.stopPatienceRounds,
            stopMinGain: loopRow.stopMinGain,
            autoRegisterModel: loopRow.autoRegisterModel,
            modelRequestConfig: {
                ...(plugin?.defaultRequestConfig || {}),
                ...(loopRow.modelRequestConfig || {}),
            },
            simulationConfig: {
                oracleCommitId: loopRow.simulationConfig?.oracleCommitId,
                seedRatio: loopRow.simulationConfig?.seedRatio ?? 0.05,
                stepRatio: loopRow.simulationConfig?.stepRatio ?? 0.05,
                maxRounds: loopRow.simulationConfig?.maxRounds ?? loopRow.maxRounds,
                randomBaselineEnabled: loopRow.simulationConfig?.randomBaselineEnabled ?? true,
                seeds: loopRow.simulationConfig?.seeds ?? [0, 1, 2, 3, 4],
            },
        });
    }, [loopId, configForm]);

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            await refreshLoopData();
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 详情失败');
        } finally {
            setLoading(false);
        }
    }, [refreshLoopData]);

    useEffect(() => {
        void loadData();
    }, [loadData]);

    const handleSave = async () => {
        if (!loopId) return;
        try {
            const values = await configForm.validateFields();
            setSaving(true);
            const payload: LoopUpdateRequest = {
                name: values.name,
                mode: values.mode,
                modelArch: values.modelArch,
                queryStrategy: values.queryStrategy,
                maxRounds: values.maxRounds,
                queryBatchSize: values.queryBatchSize,
                minSeedLabeled: values.minSeedLabeled,
                minNewLabelsPerRound: values.minNewLabelsPerRound,
                stopPatienceRounds: values.stopPatienceRounds,
                stopMinGain: values.stopMinGain,
                autoRegisterModel: values.autoRegisterModel,
                modelRequestConfig: values.modelRequestConfig || {},
                simulationConfig: {
                    oracleCommitId: values.simulationConfig?.oracleCommitId,
                    seedRatio: Number(values.simulationConfig?.seedRatio ?? 0.05),
                    stepRatio: Number(values.simulationConfig?.stepRatio ?? 0.05),
                    maxRounds: Number(values.simulationConfig?.maxRounds ?? values.maxRounds),
                    randomBaselineEnabled: Boolean(values.simulationConfig?.randomBaselineEnabled ?? true),
                    seeds: (values.simulationConfig?.seeds || [0, 1, 2, 3, 4])
                        .map((item) => Number(item))
                        .filter((item) => Number.isFinite(item))
                        .map((item) => Math.trunc(item)),
                },
            };
            await api.updateLoop(loopId, payload);
            message.success('Loop 配置已保存');
            await refreshLoopData();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || '保存 Loop 配置失败');
        } finally {
            setSaving(false);
        }
    };

    const handleLoopControl = async (action: 'start' | 'pause' | 'resume' | 'stop' | 'confirm') => {
        if (!loopId) return;
        setControlLoading(true);
        try {
            if (action === 'start') await api.startLoop(loopId);
            if (action === 'pause') await api.pauseLoop(loopId);
            if (action === 'resume') await api.resumeLoop(loopId);
            if (action === 'stop') await api.stopLoop(loopId);
            if (action === 'confirm') await api.confirmLoop(loopId);
            await refreshLoopData();
            message.success(`Loop 已${action}`);
        } catch (error: any) {
            message.error(error?.message || 'Loop 控制失败');
        } finally {
            setControlLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!loop) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="Loop 不存在或无权限访问"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>返回概览</Button>
                            <Title level={4} className="!mb-0">{loop.name}</Title>
                            <Tag color={LOOP_STATUS_COLOR[loop.status] || 'default'}>{loop.status}</Tag>
                            <Tag>{loop.phase}</Tag>
                        </div>
                        <Text type="secondary">Loop ID: {loop.id}</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate('/runtime/executors')}>执行器状态</Button>
                        <Button
                            type="primary"
                            loading={controlLoading}
                            onClick={() => handleLoopControl('start')}
                            disabled={loop.status === 'running'}
                        >
                            Start
                        </Button>
                        <Button
                            loading={controlLoading}
                            onClick={() => handleLoopControl('pause')}
                            disabled={loop.status !== 'running'}
                        >
                            Pause
                        </Button>
                        <Button
                            loading={controlLoading}
                            onClick={() => handleLoopControl('resume')}
                            disabled={loop.status !== 'paused' && loop.status !== 'draft'}
                        >
                            Resume
                        </Button>
                        {loop.mode === 'manual' ? (
                            <Button
                                loading={controlLoading}
                                onClick={() => handleLoopControl('confirm')}
                                disabled={loop.phase !== 'manual_wait_confirm'}
                            >
                                Confirm
                            </Button>
                        ) : null}
                        <Button
                            danger
                            loading={controlLoading}
                            onClick={() => handleLoopControl('stop')}
                            disabled={loop.status === 'stopped' || loop.status === 'completed'}
                        >
                            Stop
                        </Button>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Loop 摘要">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="模式">{loop.mode}</Descriptions.Item>
                    <Descriptions.Item label="Jobs 总数">{summary?.jobsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Jobs 成功">{summary?.jobsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Tasks 总数">{summary?.tasksTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Tasks 成功">{summary?.tasksSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="最新 map50">{Number(summary?.metricsLatest?.map50 || 0).toFixed(4)}</Descriptions.Item>
                </Descriptions>
            </Card>

            <Card
                className="!border-github-border !bg-github-panel"
                title="Loop 配置"
                extra={<Button type="primary" loading={saving} onClick={handleSave}>保存配置</Button>}
            >
                <Form form={configForm} layout="vertical">
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <div>
                            <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}>
                                <Input/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="mode" label="运行模式" rules={[{required: true, message: '请选择运行模式'}]}>
                                <Select
                                    options={[
                                        {label: '主动学习 (HITL)', value: 'active_learning'},
                                        {label: '模拟实验 (Simulation)', value: 'simulation'},
                                        {label: '手动模式 (Manual)', value: 'manual'},
                                    ]}
                                />
                            </Form.Item>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <div>
                            <Form.Item name="modelArch" label="插件" rules={[{required: true, message: '请选择插件'}]}>
                                <Select
                                    options={plugins.map((item) => ({
                                        label: `${item.displayName} (${item.pluginId})`,
                                        value: item.pluginId,
                                    }))}
                                    onChange={(value) => {
                                        const plugin = plugins.find((item) => item.pluginId === value);
                                        if (!plugin) return;
                                        const currentValues = configForm.getFieldValue('modelRequestConfig') || {};
                                        configForm.setFieldsValue({
                                            queryStrategy:
                                                plugin.supportedStrategies.includes(configForm.getFieldValue('queryStrategy'))
                                                    ? configForm.getFieldValue('queryStrategy')
                                                    : (plugin.supportedStrategies[0] || ''),
                                            modelRequestConfig: {
                                                ...plugin.defaultRequestConfig,
                                                ...currentValues,
                                            },
                                        });
                                    }}
                                />
                            </Form.Item>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <div>
                            <Form.Item name="queryStrategy" label="采样策略" rules={[{required: true, message: '请选择采样策略'}]}>
                                <Select
                                    options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                                />
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="autoRegisterModel" label="自动注册模型" valuePropName="checked">
                                <Switch/>
                            </Form.Item>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                        <div>
                            <Form.Item name="maxRounds" label="最大轮次">
                                <InputNumber min={1} max={500} className="w-full"/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="queryBatchSize" label="每轮 TopK">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="minSeedLabeled" label="最小 Seed 标注量">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </div>
                    </div>

                    {selectedMode === 'simulation' ? (
                        <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                            <div>
                                <Form.Item
                                    name={['simulationConfig', 'oracleCommitId']}
                                    label="Oracle Commit ID"
                                    rules={[{required: true, message: 'simulation 需要 oracle commit'}]}
                                >
                                    <Input/>
                                </Form.Item>
                            </div>
                            <div>
                                <Form.Item name={['simulationConfig', 'seedRatio']} label="初始种子比例">
                                    <InputNumber min={0.001} max={1} step={0.01} className="w-full"/>
                                </Form.Item>
                            </div>
                            <div>
                                <Form.Item name={['simulationConfig', 'stepRatio']} label="每轮提升比例">
                                    <InputNumber min={0.001} max={1} step={0.01} className="w-full"/>
                                </Form.Item>
                            </div>
                            <div>
                                <Form.Item name={['simulationConfig', 'maxRounds']} label="模拟最大轮次">
                                    <InputNumber min={1} max={500} className="w-full"/>
                                </Form.Item>
                            </div>
                            <div>
                                <Form.Item name={['simulationConfig', 'seeds']} label="随机种子列表">
                                    <Select mode="tags" tokenSeparators={[',']} placeholder="例如：0,1,2,3,4"/>
                                </Form.Item>
                            </div>
                        </div>
                    ) : null}

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                        <div>
                            <Form.Item name="minNewLabelsPerRound" label="每轮最小新增标注">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="stopPatienceRounds" label="Early Stop Patience">
                                <InputNumber min={1} max={100} className="w-full"/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="stopMinGain" label="Early Stop 最小增益">
                                <InputNumber min={0} max={1} step={0.0001} className="w-full"/>
                            </Form.Item>
                        </div>
                    </div>

                    <Card size="small" className="!border-github-border !bg-github-panel" title={selectedPlugin?.requestConfigSchema?.title || '模型请求参数'}>
                        {(selectedPlugin?.requestConfigSchema?.fields || []).length === 0 ? (
                            <Alert type="info" showIcon message="当前插件未定义动态参数 schema"/>
                        ) : (
                            <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                                {(selectedPlugin?.requestConfigSchema?.fields || []).map((field) => (
                                    <div key={field.key}>{renderDynamicField(field)}</div>
                                ))}
                            </div>
                        )}
                    </Card>
                </Form>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="当前 Loop 的 Jobs">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={jobs}
                    pagination={{pageSize: 8}}
                    columns={[
                        {title: 'Round', dataIndex: 'roundIndex', width: 90},
                        {
                            title: '状态',
                            dataIndex: 'summaryStatus',
                            width: 140,
                            render: (value: string) => <Tag color={JOB_STATUS_COLOR[value] || 'default'}>{value}</Tag>,
                        },
                        {title: '插件', dataIndex: 'pluginId'},
                        {title: '策略', dataIndex: 'queryStrategy'},
                        {
                            title: 'Tasks',
                            width: 180,
                            render: (_v: unknown, row: RuntimeJob) => JSON.stringify(row.taskCounts || {}),
                        },
                        {
                            title: '操作',
                            width: 120,
                            render: (_v: unknown, row: RuntimeJob) => (
                                <Button size="small" onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/jobs/${row.id}`)}>
                                    查看详情
                                </Button>
                            ),
                        },
                    ]}
                />
            </Card>
        </div>
    );
};

export default ProjectLoopDetail;
