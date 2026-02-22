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
    Popconfirm,
    Select,
    Spin,
    Switch,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {
    Loop,
    LoopSummary,
    LoopUpdateRequest,
    Project,
    RuntimeRound,
    RuntimePluginCatalogItem,
    RuntimeRequestConfigField,
    RuntimeRequestConfigFieldOption,
} from '../../../types';

const {Title, Text} = Typography;

const LOOP_STATE_COLOR: Record<string, string> = {
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
    wait_user: 'warning',
    completed: 'success',
    failed: 'error',
    cancelled: 'warning',
};

type LoopConfigForm = {
    name: string;
    mode: 'active_learning' | 'simulation' | 'manual';
    modelArch: string;
    samplingStrategy?: string;
    queryBatchSize?: number;
    pluginConfig: Record<string, any>;
    simulationConfig: {
        oracleCommitId?: string | null;
        seedRatio?: number;
        stepRatio?: number;
        randomBaselineEnabled?: boolean;
        seeds: Array<number | string>;
    };
};

// ---------------------------------------------------------------------------
// cond evaluation helpers
// ---------------------------------------------------------------------------

/**
 * Check whether an option's `cond` is satisfied.
 *
 * Supported cond types:
 * - `annotation_types.subset_of` – project annotation types must be a
 *   subset of the given set.
 * - `when_field` – a sibling field's current value must match.
 */
function evaluateOptionCond(
    option: RuntimeRequestConfigFieldOption,
    projectAnnotationTypes: string[],
    fieldValues: Record<string, any>,
): boolean {
    const cond = option.cond;
    if (!cond) return true;

    if (cond.annotation_types?.subset_of) {
        const allowed = new Set(cond.annotation_types.subset_of.map((s) => s.toLowerCase()));
        const actual = projectAnnotationTypes.map((s) => s.toLowerCase());
        if (!actual.every((t) => allowed.has(t))) return false;
    }

    if (cond.when_field) {
        for (const [fieldKey, expected] of Object.entries(cond.when_field)) {
            if (String(fieldValues[fieldKey] ?? '') !== String(expected)) return false;
        }
    }

    return true;
}

function filterFieldOptions(
    options: RuntimeRequestConfigFieldOption[],
    projectAnnotationTypes: string[],
    fieldValues: Record<string, any>,
): RuntimeRequestConfigFieldOption[] {
    return options.filter((opt) => evaluateOptionCond(opt, projectAnnotationTypes, fieldValues));
}

const ProjectLoopDetail: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [controlLoading, setControlLoading] = useState(false);
    const [cleaningRound, setCleaningRound] = useState<number | null>(null);
    const [loop, setLoop] = useState<Loop | null>(null);
    const [project, setProject] = useState<Project | null>(null);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [rounds, setRounds] = useState<RuntimeRound[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [configForm] = Form.useForm<LoopConfigForm>();

    const selectedPluginId = Form.useWatch('modelArch', configForm);
    const selectedMode = Form.useWatch('mode', configForm) || 'active_learning';
    const pluginConfigValues: Record<string, any> = Form.useWatch('pluginConfig', configForm) || {};
    const projectAnnotationTypes = useMemo(
        () => project?.enabledAnnotationTypes ?? [],
        [project],
    );
    const selectedPlugin = useMemo(
        () => plugins.find((item) => item.pluginId === selectedPluginId),
        [plugins, selectedPluginId],
    );

    // Auto-reset dependent fields when a parent field value changes
    const requestConfigFields = selectedPlugin?.requestConfigSchema?.fields || [];
    useEffect(() => {
        if (!requestConfigFields.length) return;
        const currentConfig = configForm.getFieldValue('pluginConfig') || {};
        const patches: Record<string, any> = {};

        for (const field of requestConfigFields) {
            if (field.type !== 'select' || !field.options?.length) continue;
            const visible = filterFieldOptions(field.options, projectAnnotationTypes, currentConfig);
            const currentVal = currentConfig[field.key];
            const stillValid = visible.some((opt) => opt.value === currentVal);
            if (!stillValid && visible.length > 0) {
                patches[field.key] = visible[0].value;
            }
        }

        if (Object.keys(patches).length > 0) {
            configForm.setFieldsValue({pluginConfig: {...currentConfig, ...patches}});
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pluginConfigValues, projectAnnotationTypes]);

    const renderDynamicField = (field: RuntimeRequestConfigField) => {
        const keyPath: (string | number)[] = ['pluginConfig', field.key];
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
            const visibleOptions = filterFieldOptions(
                field.options || [],
                projectAnnotationTypes,
                pluginConfigValues,
            );
            return (
                <Form.Item key={field.key} name={keyPath} label={field.label} rules={rules}>
                    <Select options={visibleOptions.map((item) => ({label: item.label, value: item.value}))}/>
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
        if (!loopId || !projectId) return;
        const [loopRow, summaryRow, roundRows, pluginCatalog, projectRow] = await Promise.all([
            api.getLoopById(loopId),
            api.getLoopSummary(loopId),
            api.getLoopRounds(loopId, 100),
            api.getRuntimePlugins(),
            api.getProject(projectId),
        ]);
        setLoop(loopRow);
        setSummary(summaryRow);
        setRounds(roundRows);
        setPlugins(pluginCatalog.items || []);
        setProject(projectRow);

        const plugin = pluginCatalog.items.find((item) => item.pluginId === loopRow.modelArch);
        const loopConfig = loopRow.config || ({} as any);
        const loopSampling: any = loopConfig.sampling || {};
        const loopModeConfig = loopConfig.mode || {};
        configForm.setFieldsValue({
            name: loopRow.name,
            mode: loopRow.mode || 'active_learning',
            modelArch: loopRow.modelArch,
            samplingStrategy: loopSampling.strategy || plugin?.supportedStrategies?.[0],
            queryBatchSize: Number(loopSampling.topk ?? 200),
            pluginConfig: {
                ...(plugin?.defaultRequestConfig || {}),
                ...(loopConfig.plugin || {}),
            },
            simulationConfig: {
                oracleCommitId: loopModeConfig.oracleCommitId,
                seedRatio: loopModeConfig.seedRatio ?? 0.05,
                stepRatio: loopModeConfig.stepRatio ?? 0.05,
                randomBaselineEnabled: loopModeConfig.randomBaselineEnabled ?? true,
                seeds: loopModeConfig.seeds ?? [0, 1, 2, 3, 4],
            },
        });
    }, [loopId, projectId, configForm]);

    const loadData = useCallback(async () => {
        if (!canManageLoops) return;
        setLoading(true);
        try {
            await refreshLoopData();
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 详情失败');
        } finally {
            setLoading(false);
        }
    }, [refreshLoopData, canManageLoops]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

    const handleSave = async () => {
        if (!loopId) return;
        try {
            const values = await configForm.validateFields();
            setSaving(true);
            const config: any = {
                plugin: values.pluginConfig || {},
            };
            if (values.mode !== 'manual') {
                config.sampling = {
                    strategy: values.samplingStrategy || selectedPlugin?.supportedStrategies?.[0] || 'random_baseline',
                    topk: Number(values.queryBatchSize ?? 200),
                };
            } else {
                config.mode = {singleRound: true};
            }
            if (values.mode === 'simulation') {
                config.mode = {
                    ...(config.mode || {}),
                    oracleCommitId: values.simulationConfig?.oracleCommitId,
                    seedRatio: Number(values.simulationConfig?.seedRatio ?? 0.05),
                    stepRatio: Number(values.simulationConfig?.stepRatio ?? 0.05),
                    randomBaselineEnabled: Boolean(values.simulationConfig?.randomBaselineEnabled ?? true),
                    seeds: (values.simulationConfig?.seeds || [0, 1, 2, 3, 4])
                        .map((item) => Number(item))
                        .filter((item) => Number.isFinite(item))
                        .map((item) => Math.trunc(item)),
                };
            }
            const payload: LoopUpdateRequest = {
                name: values.name,
                mode: values.mode,
                modelArch: values.modelArch,
                config,
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

    const handleCleanupRoundPredictions = async (roundIndex: number) => {
        if (!loopId) return;
        setCleaningRound(roundIndex);
        try {
            const response = await api.cleanupRoundPredictions(loopId, roundIndex);
            message.success(
                `已清理 Round ${roundIndex}：score-steps=${response.scoreSteps}，候选=${response.candidateRowsDeleted}，事件=${response.eventRowsDeleted}，指标=${response.metricRowsDeleted}`
            );
            await refreshLoopData();
        } catch (error: any) {
            message.error(error?.message || '清理 Round 预测数据失败');
        } finally {
            setCleaningRound(null);
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

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>返回概览</Button>
                            <Title level={4} className="!mb-0">{loop.name}</Title>
                            <Tag color={LOOP_STATE_COLOR[loop.state] || 'default'}>{loop.state}</Tag>
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
                            disabled={loop.state === 'running' || loop.state === 'stopping'}
                        >
                            Start
                        </Button>
                        <Button
                            loading={controlLoading}
                            onClick={() => handleLoopControl('pause')}
                            disabled={loop.state !== 'running'}
                        >
                            Pause
                        </Button>
                        <Button
                            loading={controlLoading}
                            onClick={() => handleLoopControl('resume')}
                            disabled={loop.state !== 'paused' && loop.state !== 'draft'}
                        >
                            Resume
                        </Button>
                        {loop.mode === 'active_learning' ? (
                            <Button
                                loading={controlLoading}
                                onClick={() => handleLoopControl('confirm')}
                                disabled={loop.phase !== 'al_wait_user'}
                            >
                                Confirm Round
                            </Button>
                        ) : null}
                        <Button
                            danger
                            loading={controlLoading}
                            onClick={() => handleLoopControl('stop')}
                            disabled={loop.state === 'stopped' || loop.state === 'stopping' || loop.state === 'completed'}
                        >
                            Stop
                        </Button>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Loop 摘要">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="模式">{loop.mode}</Descriptions.Item>
                    <Descriptions.Item label="Rounds 总数">{summary?.roundsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Rounds 成功">{summary?.roundsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 总数">{summary?.stepsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 成功">{summary?.stepsSucceeded ?? 0}</Descriptions.Item>
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
                                        const currentValues = configForm.getFieldValue('pluginConfig') || {};
                                        configForm.setFieldsValue({
                                            samplingStrategy:
                                                plugin.supportedStrategies.includes(configForm.getFieldValue('samplingStrategy'))
                                                    ? configForm.getFieldValue('samplingStrategy')
                                                    : (plugin.supportedStrategies[0] || ''),
                                            pluginConfig: {
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
                        {selectedMode !== 'manual' ? (
                            <div>
                                <Form.Item name="samplingStrategy" label="采样策略" rules={[{required: true, message: '请选择采样策略'}]}>
                                    <Select
                                        options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                                    />
                                </Form.Item>
                            </div>
                        ) : null}
                    </div>

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        {selectedMode !== 'manual' ? (
                            <div>
                                <Form.Item name="queryBatchSize" label="每轮 TopK">
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                            </div>
                        ) : null}
                    </div>

                    {selectedMode === 'simulation' ? (
                        <div>
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
                                    <Form.Item name={['simulationConfig', 'seeds']} label="随机种子列表">
                                        <Select mode="tags" tokenSeparators={[',']} placeholder="例如：0,1,2,3,4"/>
                                    </Form.Item>
                                </div>
                            </div>
                        </div>
                    ) : null}

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

            <Card className="!border-github-border !bg-github-panel" title="当前 Loop 的 Rounds">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={rounds}
                    pagination={{pageSize: 8}}
                    columns={[
                        {title: 'Round', dataIndex: 'roundIndex', width: 90},
                        {
                            title: '状态',
                            dataIndex: 'state',
                            width: 140,
                            render: (value: string) => <Tag color={ROUND_STATE_COLOR[value] || 'default'}>{value}</Tag>,
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
        </div>
    );
};

export default ProjectLoopDetail;
