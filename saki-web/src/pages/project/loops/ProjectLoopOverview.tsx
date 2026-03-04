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
    Slider,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams} from 'react-router-dom';
import {Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {
    Loop,
    LoopCreateRequest,
    LoopSummary,
    ProjectBranch,
    RuntimePluginCatalogItem,
    SimulationComparison,
    SimulationExperimentCreateRequest,
} from '../../../types';
import {getSummaryMetricsBySource, pickPreviewMetric} from './runtimeMetricView';

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

type CreateLoopFormValues = LoopCreateRequest & {
    globalSeed: string;
    samplingStrategy?: string;
    queryBatchSize?: number;
    simulationExperimentName?: string;
    simulationStrategies?: string[];
    simulationConfig?: {
        oracleCommitId?: string;
        seedRatio?: number;
        stepRatio?: number;
        randomBaselineEnabled?: boolean;
        seeds?: Array<number | string>;
    };
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
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [createOpen, setCreateOpen] = useState(false);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [summaryMap, setSummaryMap] = useState<Record<string, LoopSummary>>({});
    const [curveModalOpen, setCurveModalOpen] = useState(false);
    const [curveLoading, setCurveLoading] = useState(false);
    const [selectedGroupId, setSelectedGroupId] = useState<string>();
    const [comparison, setComparison] = useState<SimulationComparison | null>(null);
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
        if (!comparison) return [];
        const map = new Map<number, Record<string, number>>();
        comparison.curves.forEach((point) => {
            const row = map.get(point.roundIndex) || {roundIndex: point.roundIndex};
            row[`${point.strategy}:mean`] = Number(point.meanMetric || 0);
            map.set(point.roundIndex, row);
        });
        return Array.from(map.values()).sort((a, b) => Number(a.roundIndex) - Number(b.roundIndex));
    }, [comparison]);

    const curveLineKeys = useMemo(
        () => (comparison?.strategies || []).map((item) => `${item.strategy}:mean`),
        [comparison],
    );

    const loadComparison = useCallback(async (groupId: string) => {
        if (!groupId) return;
        setCurveLoading(true);
        try {
            const payload = await api.getSimulationExperimentComparison(groupId, 'map50');
            setComparison(payload);
        } catch (error: any) {
            message.error(error?.message || t('project.loopOverview.messages.loadComparisonFailed'));
        } finally {
            setCurveLoading(false);
        }
    }, []);

    const loadData = useCallback(async () => {
        if (!projectId || !canManageLoops) return;
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
            message.error(error?.message || t('project.loopOverview.messages.loadOverviewFailed'));
        } finally {
            setLoading(false);
        }
    }, [projectId, canManageLoops]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

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
            globalSeed: '',
            samplingStrategy: firstPlugin?.supportedStrategies?.[0] || RANDOM_BASELINE_STRATEGY,
            simulationExperimentName: '',
            simulationStrategies: defaultSimulationStrategies,
            queryBatchSize: 200,
            lifecycle: 'draft',
            simulationConfig: {
                oracleCommitId: undefined,
                seedRatio: 0.05,
                stepRatio: 0.05,
                randomBaselineEnabled: true,
                seeds: [0, 1, 2, 3, 4],
            },
        });
    }, [createOpen, branches, plugins, createForm]);

    useEffect(() => {
        if (experimentGroupOptions.length === 0) {
            setSelectedGroupId(undefined);
            setComparison(null);
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
            const isSimulation = values.mode === 'simulation';
            const globalSeed = String(values.globalSeed || '').trim();

            if (isSimulation) {
                const strategies = (values.simulationStrategies || []).filter((item) => !!String(item || '').trim());
                if (strategies.length === 0) {
                    message.error(t('project.loopOverview.messages.selectAtLeastOneSimulationStrategy'));
                    return;
                }
                const seeds = (values.simulationConfig?.seeds || [0, 1, 2, 3, 4])
                    .map((item) => Number(item))
                    .filter((item) => Number.isFinite(item))
                    .map((item) => Math.trunc(item));

                const simulationPayload: SimulationExperimentCreateRequest = {
                    branchId: values.branchId,
                    experimentName: values.simulationExperimentName?.trim() || undefined,
                    modelArch: values.modelArch,
                    strategies,
                    config: {
                        plugin: plugin?.defaultRequestConfig || {},
                        reproducibility: {
                            globalSeed,
                        },
                        sampling: {
                            strategy: values.samplingStrategy || RANDOM_BASELINE_STRATEGY,
                            topk: Number(values.queryBatchSize ?? 200),
                        },
                        mode: {
                            oracleCommitId: values.simulationConfig?.oracleCommitId,
                            seedRatio: Number(values.simulationConfig?.seedRatio ?? 0.05),
                            stepRatio: Number(values.simulationConfig?.stepRatio ?? 0.05),
                            randomBaselineEnabled: Boolean(values.simulationConfig?.randomBaselineEnabled ?? true),
                            seeds: seeds.length > 0 ? seeds : [0, 1, 2, 3, 4],
                        },
                    },
                    lifecycle: values.lifecycle || 'draft',
                };
                const created = await api.createSimulationExperiment(projectId, simulationPayload);
                message.success(t('project.loopOverview.messages.simulationExperimentCreateSuccess', {count: created.loops.length}));
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
            const config: any = {
                plugin: plugin?.defaultRequestConfig || {},
                reproducibility: {
                    globalSeed,
                },
            };
            if (values.mode !== 'manual') {
                config.sampling = {
                    strategy: values.samplingStrategy || RANDOM_BASELINE_STRATEGY,
                    topk: Number(values.queryBatchSize ?? 200),
                };
            } else {
                config.mode = {singleRound: true};
            }
            const payload: LoopCreateRequest = {
                name: loopValues.name,
                branchId: loopValues.branchId,
                mode: loopValues.mode,
                modelArch: loopValues.modelArch,
                lifecycle: loopValues.lifecycle,
                config,
            };
            const created = await api.createProjectLoop(projectId, payload);
            message.success(t('project.loopOverview.messages.loopCreateSuccess'));
            setCreateOpen(false);
            await loadData();
            navigate(`/projects/${projectId}/loops/${created.id}`);
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || t('project.loopOverview.messages.loopCreateFailed'));
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

    if (!canManageLoops) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" showIcon message={t('project.loopOverview.noPermission')}/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <Title level={4} className="!mb-1">{t('project.loopOverview.title')}</Title>
                        <Text type="secondary">{t('project.loopOverview.subtitle')}</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate('/runtime/executors')}>{t('project.loopOverview.viewExecutors')}</Button>
                        <Button
                            onClick={async () => {
                                const groupId = selectedGroupId || experimentGroupOptions[0]?.value;
                                if (!groupId) {
                                    message.info(t('project.loopOverview.messages.noSimulationExperimentGroup'));
                                    return;
                                }
                                setCurveModalOpen(true);
                                await loadComparison(groupId);
                            }}
                            disabled={experimentGroupOptions.length === 0}
                        >
                            {t('project.loopOverview.compareExperimentGroup')}
                        </Button>
                        <Button onClick={loadData}>{t('project.loopOverview.refresh')}</Button>
                        <Button
                            type="primary"
                            onClick={() => setCreateOpen(true)}
                            disabled={plugins.length === 0 || branches.length === 0}
                        >
                            {t('project.loopOverview.createLoop')}
                        </Button>
                    </div>
                </div>
                {plugins.length === 0 ? (
                    <Alert
                        className="!mt-4"
                        type="warning"
                        showIcon
                        message={t('project.loopOverview.noPluginCatalog')}
                        description={t('project.loopOverview.noPluginCatalogDesc')}
                    />
                ) : null}
            </Card>

            {loops.length === 0 ? (
                <Card className="!border-github-border !bg-github-panel">
                    <Empty description={t('project.loopOverview.empty')}/>
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
                                            {t('project.loopOverview.enterDetail')}
                                        </Button>,
                                    ]}
                                >
                                    <div className="flex w-full flex-col gap-2.5">
                                        <div className="flex w-full items-center justify-between gap-2">
                                            <Text strong>{loop.name}</Text>
                                            <Tag color={LOOP_LIFECYCLE_COLOR[loop.lifecycle] || 'default'}>{loop.lifecycle}</Tag>
                                        </div>
                                        <Text type="secondary">{t('project.loopOverview.branch')}: {branchName}</Text>
                                        <Text type="secondary">{t('project.loopOverview.mode')}: {loop.mode}</Text>
                                        <Text type="secondary">Phase：{loop.phase}</Text>
                                        {loop.gate ? <Tag color={LOOP_GATE_COLOR[loop.gate] || 'default'}>{loop.gate}</Tag> : null}
                                        <Text type="secondary">{t('project.loopOverview.plugin')}: {loop.modelArch}</Text>
                                        <Text type="secondary">{t('project.loopOverview.strategy')}: {loop.config?.sampling?.strategy || '-'}</Text>
                                        <div className="grid grid-cols-2 gap-2 text-xs text-github-muted">
                                            <div>
                                                <Text strong>{summary?.roundsTotal ?? 0}</Text> {t('project.loopOverview.summary.rounds')}
                                            </div>
                                            <div>
                                                <Text strong>{summary?.roundsSucceeded ?? 0}</Text> {t('project.loopOverview.summary.roundsSucceeded')}
                                            </div>
                                            <div>
                                                <Text strong>{summary?.stepsTotal ?? 0}</Text> {t('project.loopOverview.summary.steps')}
                                            </div>
                                            <div>
                                                <Text strong>{summary?.stepsSucceeded ?? 0}</Text> {t('project.loopOverview.summary.stepsSucceeded')}
                                            </div>
                                        </div>
                                        <Text type="secondary">
                                            {`${t('project.loopOverview.summary.trainFinal')}: ${pickPreviewMetric(getSummaryMetricsBySource(summary || null, 'train'))}`}
                                        </Text>
                                        <Text type="secondary">
                                            {`${t('project.loopOverview.summary.evalFinal')}: ${pickPreviewMetric(getSummaryMetricsBySource(summary || null, 'eval'))}`}
                                        </Text>
                                    </div>
                                </Card>
                            </div>
                        );
                    })}
                </div>
            )}

            <Modal
                title={selectedMode === 'simulation' ? t('project.loopOverview.modal.createSimulationExperiment') : t('project.loopOverview.modal.createLoop')}
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreateLoop}
                okButtonProps={{loading: creating, disabled: plugins.length === 0 || branches.length === 0}}
                cancelButtonProps={{disabled: creating}}
            >
                <Form form={createForm} layout="vertical">
                    {selectedMode !== 'simulation' ? (
                        <Form.Item name="name" label={t('project.loopOverview.form.name')} rules={[{required: true, message: t('project.loopOverview.form.nameRequired')}]}>
                            <Input placeholder={t('project.loopOverview.form.namePlaceholder')}/>
                        </Form.Item>
                    ) : (
                        <Form.Item name="simulationExperimentName" label={t('project.loopOverview.form.simulationExperimentName')}>
                            <Input placeholder={t('project.loopOverview.form.simulationExperimentNamePlaceholder')}/>
                        </Form.Item>
                    )}
                    <Form.Item name="branchId" label={t('project.loopOverview.form.branchId')} rules={[{required: true, message: t('project.loopOverview.form.branchIdRequired')}]}>
                        <Select options={branches.map((item) => ({label: item.name, value: item.id}))}/>
                    </Form.Item>
                    <Form.Item name="modelArch" label={t('project.loopOverview.form.modelArch')} rules={[{required: true, message: t('project.loopOverview.form.modelArchRequired')}]}>
                        <Select
                            options={pluginOptions}
                            onChange={(value) => {
                                const plugin = plugins.find((item) => item.pluginId === value);
                                if (plugin?.supportedStrategies?.length) {
                                    createForm.setFieldValue('samplingStrategy', plugin.supportedStrategies[0]);
                                }
                                createForm.setFieldValue('simulationStrategies', buildDefaultSimulationStrategies(plugin));
                            }}
                        />
                    </Form.Item>

                    <Form.Item
                        name="globalSeed"
                        label={t('project.loopOverview.form.globalSeed')}
                        rules={[{required: true, message: t('project.loopOverview.form.globalSeedRequired')}]}
                    >
                        <Input placeholder={t('project.loopOverview.form.globalSeedPlaceholder')}/>
                    </Form.Item>

                    {selectedMode === 'active_learning' ? (
                        <Form.Item name="samplingStrategy" label={t('project.loopOverview.form.samplingStrategy')} rules={[{required: true, message: t('project.loopOverview.form.samplingStrategyRequired')}]}>
                            <Select options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}/>
                        </Form.Item>
                    ) : (
                        <Form.Item name="simulationStrategies" label={t('project.loopOverview.form.simulationStrategies')} rules={[{required: true, message: t('project.loopOverview.form.simulationStrategiesRequired')}]}>
                            <Select
                                mode="multiple"
                                options={simulationStrategyOptions}
                                placeholder={t('project.loopOverview.form.simulationStrategiesPlaceholder')}
                            />
                        </Form.Item>
                    )}

                    <Form.Item name="mode" label={t('project.loopOverview.form.mode')} rules={[{required: true, message: t('project.loopOverview.form.modeRequired')}]}>
                        <Select
                            options={[
                                {label: t('project.loopOverview.form.modeOptions.activeLearning'), value: 'active_learning'},
                                {label: t('project.loopOverview.form.modeOptions.simulation'), value: 'simulation'},
                                {label: t('project.loopOverview.form.modeOptions.manual'), value: 'manual'},
                            ]}
                        />
                    </Form.Item>

                    {selectedMode === 'simulation' ? (
                        <>
                            <Alert
                                type="info"
                                showIcon
                                message={t('project.loopOverview.form.simulationInfo')}
                            />
                            <Form.Item
                                name={['simulationConfig', 'oracleCommitId']}
                                label={t('project.loopOverview.form.oracleCommitId')}
                                rules={[{required: true, message: t('project.loopOverview.form.oracleCommitIdRequired')}]}
                            >
                                <Input placeholder={t('project.loopOverview.form.oracleCommitIdPlaceholder')}/>
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'seedRatio']} label={t('project.loopOverview.form.seedRatio')}>
                                <Slider
                                    min={0.001}
                                    max={1}
                                    step={0.001}
                                    marks={{0.001: '0.001', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                    tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                />
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'stepRatio']} label={t('project.loopOverview.form.stepRatio')}>
                                <Slider
                                    min={0.001}
                                    max={1}
                                    step={0.001}
                                    marks={{0.001: '0.001', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                    tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                />
                            </Form.Item>
                            <Form.Item name={['simulationConfig', 'seeds']} label={t('project.loopOverview.form.seeds')}>
                                <Select mode="tags" tokenSeparators={[',']} placeholder={t('project.loopOverview.form.seedsPlaceholder')}/>
                            </Form.Item>
                        </>
                    ) : null}

                    <Form.Item name="queryBatchSize" label={t('project.loopOverview.form.queryBatchSize')}>
                        <InputNumber min={1} max={5000} className="w-full"/>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={t('project.loopOverview.compareModal.title')}
                open={curveModalOpen}
                onCancel={() => setCurveModalOpen(false)}
                footer={null}
                width={960}
            >
                <div className="flex flex-col gap-3">
                    <Select
                        value={selectedGroupId}
                        options={experimentGroupOptions}
                        onChange={async (value) => {
                            setSelectedGroupId(value);
                            await loadComparison(value);
                        }}
                        placeholder={t('project.loopOverview.compareModal.selectGroupPlaceholder')}
                    />
                    {curveLoading ? (
                        <div className="flex h-[320px] items-center justify-center">
                            <Spin/>
                        </div>
                    ) : curveChartRows.length === 0 ? (
                        <Empty description={t('project.loopOverview.compareModal.empty')}/>
                    ) : (
                        <>
                            <div className="h-[320px] w-full">
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
                            <Table
                                size="small"
                                rowKey={(row) => row.strategy}
                                pagination={false}
                                dataSource={comparison?.strategies || []}
                                columns={[
                                    {title: t('project.loopOverview.compareModal.table.strategy'), dataIndex: 'strategy'},
                                    {title: 'Seeds', render: (_: unknown, row: any) => (row.seeds || []).join(', ')},
                                    {title: 'Final Mean', render: (_: unknown, row: any) => Number(row.finalMean || 0).toFixed(4)},
                                    {title: 'Final Std', render: (_: unknown, row: any) => Number(row.finalStd || 0).toFixed(4)},
                                    {title: 'AULC', render: (_: unknown, row: any) => Number(row.aulcMean || 0).toFixed(4)},
                                    {
                                        title: 'Delta vs Baseline',
                                        render: (_: unknown, row: any) => Number(comparison?.deltaVsBaseline?.[row.strategy] || 0).toFixed(4),
                                    },
                                ]}
                            />
                        </>
                    )}
                </div>
            </Modal>
        </div>
    );
};

export default ProjectLoopOverview;
