import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Form,
    Input,
    InputNumber,
    Select,
    Slider,
    Spin,
    message,
} from 'antd';
import {useTranslation} from 'react-i18next';
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
    // 直接保留 visible 表达式（不做任何转换）
    const options = field.options?.map((opt) => ({
        label: opt.label,
        value: opt.value,
        visible: (opt as any).visible, // 保留 visible 属性
    }));

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
        visible: (field as any).visible, // 保留字段级 visible
        // 优先使用 props，回退到 ui
        props: (field as any).props ?? (field.ui ? {
            placeholder: field.ui.placeholder,
            step: field.ui.step,
            rows: field.ui.rows,
            min: field.ui.min ?? field.min,
            max: field.ui.max ?? field.max,
        } : undefined),
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
    const {t} = useTranslation();
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
            message.error(error?.message || t('project.loopConfig.messages.loadFailed'));
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
            message.success(t('project.loopConfig.messages.saveSuccess'));
            await refreshLoopData();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || t('project.loopConfig.messages.saveFailed'));
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
                <Alert type="warning" showIcon message={t('project.loopConfig.noPermission')}/>
            </Card>
        );
    }

    if (!loop) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Alert type="warning" message={t('project.loopConfig.notFoundOrNoPermission')}/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex w-full flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <h2 className="text-xl font-semibold">{t('project.loopConfig.pageTitle', {name: loop.name})}</h2>
                        <p className="text-sm text-gray-500">Loop ID: {loop.id}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}`)}>{t('project.loopConfig.backToDetail')}</Button>
                        <Button
                            type="primary"
                            loading={saving}
                            onClick={handleSave}
                        >
                            {t('project.loopConfig.saveConfig')}
                        </Button>
                    </div>
                </div>
            </Card>

            <Card
                className="!border-github-border !bg-github-panel"
                title={t('project.loopConfig.basicConfig')}
            >
                <Form form={configForm} layout="vertical">
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <div>
                            <Form.Item name="name" label={t('project.loopConfig.form.name')} rules={[{required: true, message: t('project.loopConfig.form.nameRequired')}]}>
                                <Input/>
                            </Form.Item>
                        </div>
                        <div>
                            <Form.Item name="mode" label={t('project.loopConfig.form.mode')} rules={[{required: true, message: t('project.loopConfig.form.modeRequired')}]}>
                                <Select
                                    options={[
                                        {label: t('project.loopConfig.form.modeOptions.activeLearning'), value: 'active_learning'},
                                        {label: t('project.loopConfig.form.modeOptions.simulation'), value: 'simulation'},
                                        {label: t('project.loopConfig.form.modeOptions.manual'), value: 'manual'},
                                    ]}
                                />
                            </Form.Item>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <div>
                            <Form.Item name="modelArch" label={t('project.loopConfig.form.modelArch')} rules={[{required: true, message: t('project.loopConfig.form.modelArchRequired')}]}>
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
                                <Form.Item name="samplingStrategy" label={t('project.loopConfig.form.samplingStrategy')} rules={[{required: true, message: t('project.loopConfig.form.samplingStrategyRequired')}]}>
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
                                <Form.Item name="queryBatchSize" label={t('project.loopConfig.form.queryBatchSize')}>
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                            </div>
                        ) : null}
                    </div>

                    {selectedMode === 'simulation' ? (
                        <div>
                            <div className="mb-2 font-semibold">{t('project.loopConfig.form.simulationConfigTitle')}</div>
                            <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                                <div>
                                    <Form.Item
                                        name={['simulationConfig', 'oracleCommitId']}
                                        label={t('project.loopConfig.form.oracleCommitId')}
                                        rules={[{required: true, message: t('project.loopConfig.form.oracleCommitIdRequired')}]}
                                    >
                                        <Input/>
                                    </Form.Item>
                                </div>
                                <div>
                                    <Form.Item name={['simulationConfig', 'seedRatio']} label={t('project.loopConfig.form.seedRatio')}>
                                        <Slider
                                            min={0.001}
                                            max={1}
                                            step={0.001}
                                            marks={{0.001: '0.001', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                            tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                        />
                                    </Form.Item>
                                </div>
                                <div>
                                    <Form.Item name={['simulationConfig', 'stepRatio']} label={t('project.loopConfig.form.stepRatio')}>
                                        <Slider
                                            min={0.001}
                                            max={1}
                                            step={0.001}
                                            marks={{0.001: '0.001', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                            tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                        />
                                    </Form.Item>
                                </div>
                                <div>
                                    <Form.Item name={['simulationConfig', 'seeds']} label={t('project.loopConfig.form.seeds')}>
                                        <Select mode="tags" tokenSeparators={[',']} placeholder={t('project.loopConfig.form.seedsPlaceholder')}/>
                                    </Form.Item>
                                </div>
                            </div>
                        </div>
                    ) : null}

                    <Card size="small" className="!border-github-border !bg-github-panel" title={selectedPlugin?.requestConfigSchema?.title || t('project.loopConfig.form.modelRequestParams')}>
                        {pluginConfigSchema.fields.length === 0 ? (
                            <Alert type="info" showIcon message={t('project.loopConfig.form.noDynamicSchema')}/>
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
