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
    Row,
    Col,
    Select,
    Space,
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
    LoopRound,
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
    pending: 'default',
    running: 'processing',
    success: 'success',
    failed: 'error',
    cancelled: 'warning',
};

type LoopConfigForm = {
    name: string;
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
};

const ProjectLoopDetail: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [controlLoading, setControlLoading] = useState(false);
    const [loop, setLoop] = useState<ALLoop | null>(null);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [rounds, setRounds] = useState<LoopRound[]>([]);
    const [jobs, setJobs] = useState<RuntimeJob[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [configForm] = Form.useForm<LoopConfigForm>();

    const selectedPluginId = Form.useWatch('modelArch', configForm);
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
                    <Select
                        options={(field.options || []).map((item) => ({label: item.label, value: item.value}))}
                    />
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
        const [loopRow, summaryRow, roundRows, jobRows, pluginCatalog] = await Promise.all([
            api.getLoopById(loopId),
            api.getLoopSummary(loopId),
            api.getLoopRounds(loopId, 500),
            api.getLoopJobs(loopId, 100),
            api.getRuntimePlugins(),
        ]);
        setLoop(loopRow);
        setSummary(summaryRow);
        setRounds(roundRows);
        setJobs(jobRows);
        setPlugins(pluginCatalog.items || []);
        const plugin = pluginCatalog.items.find((item) => item.pluginId === loopRow.modelArch);
        configForm.setFieldsValue({
            name: loopRow.name,
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

    const handleLoopControl = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
        if (!loopId) return;
        setControlLoading(true);
        try {
            if (action === 'start') await api.startLoop(loopId);
            if (action === 'pause') await api.pauseLoop(loopId);
            if (action === 'resume') await api.resumeLoop(loopId);
            if (action === 'stop') await api.stopLoop(loopId);
            await refreshLoopData();
            message.success(`Loop 已${action === 'start' ? '启动' : action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '停止'}`);
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
                <Space className="w-full !justify-between" wrap>
                    <Space direction="vertical" size={2}>
                        <Space>
                            <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>返回概览</Button>
                            <Title level={4} className="!mb-0">{loop.name}</Title>
                            <Tag color={LOOP_STATUS_COLOR[loop.status] || 'default'}>{loop.status}</Tag>
                        </Space>
                        <Text type="secondary">Loop ID: {loop.id}</Text>
                    </Space>
                    <Space>
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
                        <Button
                            danger
                            loading={controlLoading}
                            onClick={() => handleLoopControl('stop')}
                            disabled={loop.status === 'stopped' || loop.status === 'completed'}
                        >
                            Stop
                        </Button>
                    </Space>
                </Space>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Loop 摘要">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="总轮次">{summary?.roundsTotal ?? rounds.length}</Descriptions.Item>
                    <Descriptions.Item label="完成轮次">{summary?.roundsCompleted ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="累计选样">{summary?.selectedTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="累计标注">{summary?.labeledTotal ?? 0}</Descriptions.Item>
                </Descriptions>
            </Card>

            <Card
                className="!border-github-border !bg-github-panel"
                title="Loop 配置"
                extra={<Button type="primary" loading={saving} onClick={handleSave}>保存配置</Button>}
            >
                <Form form={configForm} layout="vertical">
                    <Row gutter={16}>
                        <Col xs={24} md={12}>
                            <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}>
                                <Input/>
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
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
                        </Col>
                    </Row>
                    <Row gutter={16}>
                        <Col xs={24} md={12}>
                            <Form.Item name="queryStrategy" label="采样策略" rules={[{required: true, message: '请选择采样策略'}]}>
                                <Select
                                    options={(selectedPlugin?.supportedStrategies || []).map((item) => ({
                                        label: item,
                                        value: item,
                                    }))}
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                            <Form.Item name="autoRegisterModel" label="自动注册模型" valuePropName="checked">
                                <Switch/>
                            </Form.Item>
                        </Col>
                    </Row>
                    <Row gutter={16}>
                        <Col xs={24} md={8}>
                            <Form.Item name="maxRounds" label="最大轮次">
                                <InputNumber min={1} max={500} className="w-full"/>
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                            <Form.Item name="queryBatchSize" label="每轮 TopK">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                            <Form.Item name="minSeedLabeled" label="最小 Seed 标注量">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </Col>
                    </Row>
                    <Row gutter={16}>
                        <Col xs={24} md={8}>
                            <Form.Item name="minNewLabelsPerRound" label="每轮最小新增标注">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                            <Form.Item name="stopPatienceRounds" label="Early Stop Patience">
                                <InputNumber min={1} max={100} className="w-full"/>
                            </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                            <Form.Item name="stopMinGain" label="Early Stop 最小增益">
                                <InputNumber min={0} max={1} step={0.0001} className="w-full"/>
                            </Form.Item>
                        </Col>
                    </Row>

                    <Card size="small" className="!border-github-border !bg-github-panel" title={selectedPlugin?.requestConfigSchema?.title || '模型请求参数'}>
                        {(selectedPlugin?.requestConfigSchema?.fields || []).length === 0 ? (
                            <Alert type="info" showIcon message="当前插件未定义动态参数 schema"/>
                        ) : (
                            <Row gutter={16}>
                                {(selectedPlugin?.requestConfigSchema?.fields || []).map((field) => (
                                    <Col key={field.key} xs={24} md={12}>
                                        {renderDynamicField(field)}
                                    </Col>
                                ))}
                            </Row>
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
                            dataIndex: 'status',
                            width: 120,
                            render: (value: string) => <Tag color={JOB_STATUS_COLOR[value] || 'default'}>{value}</Tag>,
                        },
                        {title: '插件', dataIndex: 'pluginId'},
                        {title: '策略', dataIndex: 'queryStrategy'},
                        {title: '执行器', dataIndex: 'assignedExecutorId', render: (v: string | null) => v || '-'},
                        {
                            title: '操作',
                            width: 120,
                            render: (_v: unknown, row: RuntimeJob) => (
                                <Button
                                    size="small"
                                    onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/jobs/${row.id}`)}
                                >
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
