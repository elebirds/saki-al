import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Empty,
    Form,
    Input,
    InputNumber,
    Modal,
    Select,
    Spin,
    Tag,
    Typography,
    message,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {api} from '../../../services/api';
import {ALLoop, LoopCreateRequest, LoopSummary, ProjectBranch, RuntimePluginCatalogItem} from '../../../types';

const {Title, Text} = Typography;

const LOOP_STATUS_COLOR: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    stopped: 'default',
    completed: 'success',
    failed: 'error',
};

const ProjectLoopOverview: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [createOpen, setCreateOpen] = useState(false);
    const [loops, setLoops] = useState<ALLoop[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [summaryMap, setSummaryMap] = useState<Record<string, LoopSummary>>({});
    const [createForm] = Form.useForm<LoopCreateRequest>();

    const pluginOptions = useMemo(
        () => plugins.map((item) => ({label: `${item.displayName} (${item.pluginId})`, value: item.pluginId})),
        [plugins],
    );

    const selectedPluginId = Form.useWatch('modelArch', createForm);
    const selectedPlugin = useMemo(
        () => plugins.find((item) => item.pluginId === selectedPluginId),
        [plugins, selectedPluginId],
    );

    const loadData = useCallback(async () => {
        if (!projectId) return;
        setLoading(true);
        try {
            const [loopRows, branchRows, pluginCatalog] = await Promise.all([
                api.getProjectLoops(projectId),
                api.getProjectBranches(projectId),
                api.getRuntimePlugins(),
            ]);
            setLoops(loopRows);
            setBranches(branchRows);
            setPlugins(pluginCatalog.items || []);

            const summaryResults = await Promise.allSettled(
                loopRows.map(async (item) => [item.id, await api.getLoopSummary(item.id)] as const),
            );
            const nextSummaryMap: Record<string, LoopSummary> = {};
            summaryResults.forEach((item) => {
                if (item.status === 'fulfilled') {
                    nextSummaryMap[item.value[0]] = item.value[1];
                }
            });
            setSummaryMap(nextSummaryMap);
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 概览失败');
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        void loadData();
    }, [loadData]);

    useEffect(() => {
        if (!createOpen) return;
        const firstBranchId = branches[0]?.id;
        const firstPlugin = plugins[0];
        createForm.setFieldsValue({
            name: '',
            branchId: firstBranchId,
            modelArch: firstPlugin?.pluginId,
            queryStrategy: firstPlugin?.supportedStrategies?.[0] || 'aug_iou_disagreement_v1',
            maxRounds: 5,
            queryBatchSize: 200,
            minSeedLabeled: 100,
            minNewLabelsPerRound: 120,
            stopPatienceRounds: 2,
            stopMinGain: 0.002,
            autoRegisterModel: true,
            isActive: true,
            status: 'draft',
        });
    }, [createOpen, branches, plugins, createForm]);

    const handleCreateLoop = async () => {
        if (!projectId) return;
        try {
            const values = await createForm.validateFields();
            setCreating(true);
            const plugin = plugins.find((item) => item.pluginId === values.modelArch);
            const payload: LoopCreateRequest = {
                ...values,
                modelRequestConfig: plugin?.defaultRequestConfig || {},
            };
            const created = await api.createProjectLoop(projectId, payload);
            message.success('Loop 创建成功');
            setCreateOpen(false);
            await loadData();
            navigate(`/projects/${projectId}/loops/${created.id}`);
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || 'Loop 创建失败');
        } finally {
            setCreating(false);
        }
    };

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <Title level={4} className="!mb-1">AL Loop 概览</Title>
                        <Text type="secondary">一个项目可包含多个 Loop，点击卡片进入单 Loop 详情。</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate('/runtime/executors')}>查看执行器状态</Button>
                        <Button onClick={loadData}>刷新</Button>
                        <Button
                            type="primary"
                            onClick={() => setCreateOpen(true)}
                            disabled={plugins.length === 0 || branches.length === 0}
                        >
                            新建 Loop
                        </Button>
                    </div>
                </div>
                {plugins.length === 0 ? (
                    <Alert
                        className="!mt-4"
                        type="warning"
                        showIcon
                        message="当前没有可用插件目录"
                        description="请先启动至少一个 executor 并完成注册，再创建 Loop。"
                    />
                ) : null}
            </Card>

            {loops.length === 0 ? (
                <Card className="!border-github-border !bg-github-panel">
                    <Empty description="当前项目还没有 Loop"/>
                </Card>
            ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {loops.map((loop) => {
                        const summary = summaryMap[loop.id];
                        const branchName = branches.find((item) => item.id === loop.branchId)?.name || loop.branchId;
                        return (
                            <div key={loop.id} className="min-w-0">
                                <Card
                                    className="!h-full !border-github-border !bg-github-panel hover:!border-github-border-muted"
                                    actions={[
                                        <Button
                                            key="enter"
                                            type="link"
                                            onClick={() => navigate(`/projects/${projectId}/loops/${loop.id}`)}
                                        >
                                            进入详情
                                        </Button>,
                                    ]}
                                >
                                    <div className="flex w-full flex-col gap-2.5">
                                        <div className="flex w-full items-center justify-between gap-2">
                                            <Text strong>{loop.name}</Text>
                                            <Tag color={LOOP_STATUS_COLOR[loop.status] || 'default'}>{loop.status}</Tag>
                                        </div>
                                        <Text type="secondary">分支：{branchName}</Text>
                                        <Text type="secondary">插件：{loop.modelArch}</Text>
                                        <Text type="secondary">策略：{loop.queryStrategy}</Text>
                                        <div className="grid grid-cols-2 gap-2 text-xs text-github-muted">
                                            <div>
                                                <Text strong>{summary?.roundsTotal ?? 0}</Text> 轮次
                                            </div>
                                            <div>
                                                <Text strong>{summary?.roundsCompleted ?? 0}</Text> 已完成
                                            </div>
                                            <div>
                                                <Text strong>{summary?.selectedTotal ?? 0}</Text> 选样
                                            </div>
                                            <div>
                                                <Text strong>{summary?.labeledTotal ?? 0}</Text> 标注
                                            </div>
                                        </div>
                                    </div>
                                </Card>
                            </div>
                        );
                    })}
                </div>
            )}

            <Modal
                title="新建 AL Loop"
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreateLoop}
                okButtonProps={{loading: creating, disabled: plugins.length === 0 || branches.length === 0}}
                cancelButtonProps={{disabled: creating}}
            >
                <Form form={createForm} layout="vertical">
                    <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}>
                        <Input placeholder="例如：fedo-yolo-loop-1"/>
                    </Form.Item>
                    <Form.Item name="branchId" label="绑定分支" rules={[{required: true, message: '请选择分支'}]}>
                        <Select options={branches.map((item) => ({label: item.name, value: item.id}))}/>
                    </Form.Item>
                    <Form.Item name="modelArch" label="插件" rules={[{required: true, message: '请选择插件'}]}>
                        <Select
                            options={pluginOptions}
                            onChange={(value) => {
                                const plugin = plugins.find((item) => item.pluginId === value);
                                if (plugin?.supportedStrategies?.length) {
                                    createForm.setFieldValue('queryStrategy', plugin.supportedStrategies[0]);
                                }
                            }}
                        />
                    </Form.Item>
                    <Form.Item name="queryStrategy" label="默认采样策略" rules={[{required: true, message: '请选择采样策略'}]}>
                        <Select
                            options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                        />
                    </Form.Item>
                    <Form.Item name="maxRounds" label="最大轮次">
                        <InputNumber min={1} max={500} className="w-full"/>
                    </Form.Item>
                    <Form.Item name="queryBatchSize" label="每轮 TopK">
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                    <Form.Item name="minSeedLabeled" label="最小 Seed 标注量">
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                    <Form.Item name="minNewLabelsPerRound" label="每轮最小新增标注">
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectLoopOverview;
