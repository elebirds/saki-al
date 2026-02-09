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
import {Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';

import {api} from '../../../services/api';
import {
    ALLoop,
    LoopCreateRequest,
    LoopSummary,
    ProjectBranch,
    RuntimePluginCatalogItem,
    SimulationExperimentCreateRequest,
    SimulationExperimentCurves,
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

type CreateLoopFormValues = LoopCreateRequest & {
    simulationExperimentName?: string;
    simulationStrategies?: string[];
};

const RANDOM_BASELINE_STRATEGY = 'random_baseline';

const buildDefaultSimulationStrategies = (plugin?: RuntimePluginCatalogItem): string[] => {
    const merged = listSimulationStrategies(plugin);
    if (merged.length <= 3) return merged;
    return merged.slice(0, 3);
};

const listSimulationStrategies = (plugin?: RuntimePluginCatalogItem): string[] => {
    return Array.from(new Set([RANDOM_BASELINE_STRATEGY, ...(plugin?.supportedStrategies || [])]));
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
    const [curveModalOpen, setCurveModalOpen] = useState(false);
    const [curveLoading, setCurveLoading] = useState(false);
    const [selectedGroupId, setSelectedGroupId] = useState<string>();
    const [curves, setCurves] = useState<SimulationExperimentCurves | null>(null);
    const [createForm] = Form.useForm<CreateLoopFormValues>();
    const selectedMode = Form.useWatch('mode', createForm) || 'active_learning';

    const pluginOptions = useMemo(
        () => plugins.map((item) => ({label: `${item.displayName} (${item.pluginId})`, value: item.pluginId})),
        [plugins],
    );

    const selectedPluginId = Form.useWatch('modelArch', createForm);
    const selectedPlugin = useMemo(
        () => plugins.find((item) => item.pluginId === selectedPluginId),
        [plugins, selectedPluginId],
    );
    const simulationStrategyOptions = useMemo(
        () => listSimulationStrategies(selectedPlugin).map((item) => ({label: item, value: item})),
        [selectedPlugin],
    );
    const experimentGroupOptions = useMemo(() => {
        const groupSet = new Set<string>();
        loops.forEach((item) => {
            if (item.experimentGroupId) groupSet.add(item.experimentGroupId);
        });
        return Array.from(groupSet).map((id) => ({label: id, value: id}));
    }, [loops]);
    const curveChartRows = useMemo(() => {
        if (!curves) return [];
        const map = new Map<number, Record<string, number>>();
        curves.loops.forEach((loopCurve) => {
            loopCurve.points.forEach((point) => {
                const row = map.get(point.roundIndex) || {roundIndex: point.roundIndex};
                row[`${loopCurve.queryStrategy}:map50`] = Number(point.map50 || 0);
                map.set(point.roundIndex, row);
            });
        });
        return Array.from(map.values()).sort((a, b) => Number(a.roundIndex) - Number(b.roundIndex));
    }, [curves]);
    const curveLineKeys = useMemo(
        () => (curves?.loops || []).map((item) => `${item.queryStrategy}:map50`),
        [curves],
    );

    const loadCurves = useCallback(async (groupId: string) => {
        if (!groupId) return;
        setCurveLoading(true);
        try {
            const payload = await api.getSimulationExperimentCurves(groupId);
            setCurves(payload);
        } catch (error: any) {
            message.error(error?.message || '加载对比曲线失败');
        } finally {
            setCurveLoading(false);
        }
    }, []);

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
        const defaultSimulationStrategies = buildDefaultSimulationStrategies(firstPlugin);
        createForm.setFieldsValue({
            name: '',
            branchId: firstBranchId,
            mode: 'active_learning',
            modelArch: firstPlugin?.pluginId,
            queryStrategy: firstPlugin?.supportedStrategies?.[0],
            simulationExperimentName: '',
            simulationStrategies: defaultSimulationStrategies,
            maxRounds: 5,
            queryBatchSize: 200,
            minSeedLabeled: 100,
            minNewLabelsPerRound: 120,
            stopPatienceRounds: 2,
            stopMinGain: 0.002,
            autoRegisterModel: true,
            status: 'draft',
            simulationConfig: {
                oracleCommitId: undefined,
                initialSeedCount: 100,
                queryBatchSize: 200,
                maxRounds: 5,
                splitSeed: 0,
                randomSeed: 0,
                requireFullyLabeled: true,
            },
        });
    }, [createOpen, branches, plugins, createForm]);

    useEffect(() => {
        if (experimentGroupOptions.length === 0) {
            setSelectedGroupId(undefined);
            setCurves(null);
            return;
        }
        if (selectedGroupId && experimentGroupOptions.some((item) => item.value === selectedGroupId)) {
            return;
        }
        setSelectedGroupId(experimentGroupOptions[0].value);
    }, [experimentGroupOptions, selectedGroupId]);

    const handleCreateLoop = async () => {
        if (!projectId) return;
        try {
            const values = await createForm.validateFields();
            setCreating(true);
            const plugin = plugins.find((item) => item.pluginId === values.modelArch);
            if (values.mode === 'simulation') {
                const strategies = (values.simulationStrategies || []).filter((item) => !!String(item || '').trim());
                if (strategies.length === 0) {
                    message.error('请至少选择一个 simulation 策略');
                    return;
                }
                const simulationPayload: SimulationExperimentCreateRequest = {
                    branchId: values.branchId,
                    experimentName: values.simulationExperimentName?.trim() || undefined,
                    modelArch: values.modelArch,
                    strategies,
                    globalConfig: values.globalConfig || {},
                    modelRequestConfig: plugin?.defaultRequestConfig || {},
                    simulationConfig: values.simulationConfig!,
                    status: values.status || 'draft',
                };
                const created = await api.createSimulationExperiment(projectId, simulationPayload);
                message.success(`Simulation 实验创建成功，共 ${created.loops.length} 条策略 Loop`);
                setCreateOpen(false);
                await loadData();
                if (created.loops[0]) {
                    navigate(`/projects/${projectId}/loops/${created.loops[0].id}`);
                }
                return;
            }

            const {simulationExperimentName, simulationStrategies, ...loopValues} = values;
            void simulationExperimentName;
            void simulationStrategies;
            const payload: LoopCreateRequest = {
                ...loopValues,
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
                        <Button
                            onClick={async () => {
                                const groupId = selectedGroupId || experimentGroupOptions[0]?.value;
                                if (!groupId) {
                                    message.info('当前没有可展示的 simulation 实验组');
                                    return;
                                }
                                setCurveModalOpen(true);
                                await loadCurves(groupId);
                            }}
                            disabled={experimentGroupOptions.length === 0}
                        >
                            实验组曲线
                        </Button>
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
                                        <Text type="secondary">模式：{loop.mode}</Text>
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
                title={selectedMode === 'simulation' ? '新建 Simulation Experiment' : '新建 AL Loop'}
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreateLoop}
                okButtonProps={{loading: creating, disabled: plugins.length === 0 || branches.length === 0}}
                cancelButtonProps={{disabled: creating}}
            >
                <Form form={createForm} layout="vertical">
                    {selectedMode === 'active_learning' ? (
                        <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}>
                            <Input placeholder="例如：fedo-yolo-loop-1"/>
                        </Form.Item>
                    ) : (
                        <Form.Item name="simulationExperimentName" label="实验名称（可选）">
                            <Input placeholder="例如：车辆检测对比实验（留空则系统自动命名）"/>
                        </Form.Item>
                    )}
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
                                createForm.setFieldValue('simulationStrategies', buildDefaultSimulationStrategies(plugin));
                            }}
                        />
                    </Form.Item>
                    {selectedMode === 'active_learning' ? (
                        <Form.Item name="queryStrategy" label="默认采样策略" rules={[{required: true, message: '请选择采样策略'}]}>
                            <Select
                                options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                            />
                        </Form.Item>
                    ) : (
                        <Form.Item
                            name="simulationStrategies"
                            label="对比策略"
                            rules={[{required: true, message: '请至少选择一个策略'}]}
                        >
                            <Select
                                mode="multiple"
                                options={simulationStrategyOptions}
                                placeholder="至少选择一个策略，系统会自动补齐 random_baseline"
                            />
                        </Form.Item>
                    )}
                    <Form.Item name="mode" label="运行模式" rules={[{required: true, message: '请选择运行模式'}]}>
                        <Select
                            options={[
                                {label: '主动学习 (HITL)', value: 'active_learning'},
                                {label: '模拟实验 (Simulation)', value: 'simulation'},
                            ]}
                        />
                    </Form.Item>
                    {selectedMode === 'active_learning' ? (
                        <>
                            <Form.Item name="maxRounds" label="最大轮次">
                                <InputNumber min={1} max={500} className="w-full"/>
                            </Form.Item>
                            <Form.Item name="queryBatchSize" label="每轮 TopK">
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        </>
                    ) : null}
                    {selectedMode === 'simulation' ? (
                        <>
                            <Alert
                                type="info"
                                showIcon
                                message="每个策略会自动 fork 独立分支（simulation/<实验名>/<group>/<strategy>），不会占用当前业务分支。"
                            />
                            <Form.Item
                                name={['simulationConfig', 'oracleCommitId']}
                                label="Oracle Commit ID"
                                rules={[{required: true, message: 'simulation 模式必须提供 oracle commit'}]}
                            >
                                <Input placeholder="全量标注 commit id"/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'initialSeedCount']} label="初始 Seed 数量">
                                <InputNumber min={1} max={50000} className="w-full"/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'queryBatchSize']} label="每轮模拟选样 TopK">
                                <InputNumber min={1} max={50000} className="w-full"/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'maxRounds']} label="模拟最大轮次">
                                <InputNumber min={1} max={500} className="w-full"/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'splitSeed']} label="数据切分种子">
                                <InputNumber min={0} max={2147483647} className="w-full"/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'randomSeed']} label="随机策略种子">
                                <InputNumber min={0} max={2147483647} className="w-full"/>
                            </Form.Item>
                        </>
                    ) : null}
                    <Form.Item name="minSeedLabeled" label="最小 Seed 标注量">
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                    <Form.Item name="minNewLabelsPerRound" label="每轮最小新增标注">
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title="Simulation 策略对比曲线"
                open={curveModalOpen}
                onCancel={() => setCurveModalOpen(false)}
                footer={null}
                width={900}
            >
                <div className="flex flex-col gap-3">
                    <Select
                        value={selectedGroupId}
                        options={experimentGroupOptions}
                        onChange={async (value) => {
                            setSelectedGroupId(value);
                            await loadCurves(value);
                        }}
                        placeholder="选择实验组"
                    />
                    {curveLoading ? (
                        <div className="flex h-[320px] items-center justify-center">
                            <Spin/>
                        </div>
                    ) : curveChartRows.length === 0 ? (
                        <Empty description="暂无可绘制曲线数据"/>
                    ) : (
                        <div className="h-[360px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={curveChartRows}>
                                    <XAxis dataKey="roundIndex"/>
                                    <YAxis domain={[0, 1]}/>
                                    <Tooltip/>
                                    {curveLineKeys.map((key, idx) => (
                                        <Line
                                            key={key}
                                            type="monotone"
                                            dataKey={key}
                                            name={key}
                                            stroke={['#1677ff', '#13c2c2', '#fa8c16', '#f5222d', '#722ed1'][idx % 5]}
                                            strokeWidth={2}
                                            dot={false}
                                        />
                                    ))}
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </div>
            </Modal>
        </div>
    );
};

export default ProjectLoopOverview;
