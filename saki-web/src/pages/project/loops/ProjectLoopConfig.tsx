import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Form,
    Input,
    InputNumber,
    Popconfirm,
    Select,
    Spin,
    message,
} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {
    Loop,
    LoopUpdateRequest,
    Project,
    RuntimePluginCatalogItem,
    RuntimeRequestConfigField,
    PluginConfigSchema,
    PluginConfigField,
} from '../../../types';
import {DynamicConfigForm} from '../../../components/common';

// ---------------------------------------------------------------------------
// Helper: Convert RuntimeRequestConfigField to PluginConfigField
// ---------------------------------------------------------------------------

function toPluginConfigField(field: RuntimeRequestConfigField): PluginConfigField {
    // Convert cond to visible expression for options
    const options = field.options?.map((opt) => {
        const result: any = {
            label: opt.label,
            value: opt.value,
        };

        // Convert cond to visible expression if present
        if (opt.cond) {
            const condParts: string[] = [];
            if (opt.cond.annotation_types?.subset_of) {
                const types = opt.cond.annotation_types.subset_of;
                condParts.push(`ctx.annotation_types.includes('${types[0]}')`);
            }
            if (opt.cond.when_field) {
                for (const [key, val] of Object.entries(opt.cond.when_field)) {
                    condParts.push(`form.${key} === '${val}'`);
                }
            }
            if (condParts.length > 0) {
                result.visible = condParts.join(' && ');
            }
        }

        return result;
    });

    return {
        key: field.key,
        label: field.label,
        type: field.type as any,
        required: field.required,
        min: field.min,
        max: field.max,
        default: field.default,
        description: field.description,
        group: field.group,
        depends_on: field.depends_on,
        // Merge ui into props
        props: field.ui ? {
            placeholder: field.ui.placeholder,
            step: field.ui.step,
            rows: field.ui.rows,
            min: field.ui.min ?? field.min,
            max: field.ui.max ?? field.max,
        } : undefined,
        options: options && options.length > 0 ? options : undefined,
    };
}

function toPluginConfigSchema(schema: {title?: string; description?: string; fields?: RuntimeRequestConfigField[]} | undefined): PluginConfigSchema {
    return {
        title: schema?.title,
        description: schema?.description,
        fields: (schema?.fields || []).map(toPluginConfigField),
    };
}

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

const ProjectLoopConfig: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [loop, setLoop] = useState<Loop | null>(null);
    const [project, setProject] = useState<Project | null>(null);
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

    const refreshLoopData = useCallback(async () => {
        if (!loopId || !projectId) return;
        const [loopRow, pluginCatalog, projectRow] = await Promise.all([
            api.getLoopById(loopId),
            api.getRuntimePlugins(),
            api.getProject(projectId),
        ]);
        setLoop(loopRow);
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
            message.error(error?.message || '加载 Loop 配置失败');
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

    // Handle plugin config changes
    const handlePluginConfigChange = useCallback((newValues: Record<string, any>) => {
        configForm.setFieldsValue({ pluginConfig: newValues });
    }, [configForm]);

    // Plugin config schema for DynamicConfigForm
    const pluginConfigSchema = useMemo((): PluginConfigSchema => {
        return toPluginConfigSchema(selectedPlugin?.requestConfigSchema);
    }, [selectedPlugin]);

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
                <Alert type="warning" showIcon message="暂无权限访问 Loop 配置页面"/>
            </Card>
        );
    }

    if (!loop) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" message="Loop 不存在或无权限访问"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <h2 className="text-xl font-semibold">{loop.name} 配置</h2>
                        <p className="text-sm text-gray-500">Loop ID: {loop.id}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}`)}>返回详情</Button>
                        <Button
                            type="primary"
                            loading={saving}
                            onClick={handleSave}
                        >
                            保存配置
                        </Button>
                    </div>
                </div>
            </Card>

            <Card
                className="!border-github-border !bg-github-panel"
                title="基本配置"
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
                            <div className="mb-2 font-semibold">模拟实验配置</div>
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
                        {pluginConfigSchema.fields.length === 0 ? (
                            <Alert type="info" showIcon message="当前插件未定义动态参数 schema"/>
                        ) : (
                            <DynamicConfigForm
                                schema={pluginConfigSchema}
                                values={pluginConfigValues}
                                onChange={handlePluginConfigChange}
                                context={{
                                    annotationTypes: projectAnnotationTypes,
                                    fieldValues: pluginConfigValues,
                                }}
                                form={configForm}
                                namePrefix="pluginConfig"
                            />
                        )}
                    </Card>
                </Form>
            </Card>
        </div>
    );
};

export default ProjectLoopConfig;
