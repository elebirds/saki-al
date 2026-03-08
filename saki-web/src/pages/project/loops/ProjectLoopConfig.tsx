import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Form,
    Input,
    InputNumber,
    Radio,
    Select,
    Slider,
    Spin,
    message,
} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams} from 'react-router-dom';

import {DynamicConfigForm} from '../../../components/common';
import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {CommitHistoryItem, Loop, Project, ProjectLabel, RuntimeExecutorRead, RuntimePluginCatalogItem} from '../../../types';
import {toPluginConfigSchema} from './loopFormSchemaAdapter';
import {
    buildLoopUpdatePayload,
    LoopEditorFormValues,
    mergePluginConfigWithDefaults,
    pickDefaultSamplingStrategy,
} from './loopPayloadBuilder';
import {buildExecutorCapabilitySummary, executorSupportsPlugin} from '../../runtime/executorCapability';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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
    const [labels, setLabels] = useState<ProjectLabel[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [executors, setExecutors] = useState<RuntimeExecutorRead[]>([]);
    const [commits, setCommits] = useState<CommitHistoryItem[]>([]);
    const [configForm] = Form.useForm<LoopEditorFormValues>();

    const selectedPluginId = Form.useWatch('modelArch', configForm);
    const selectedMode = Form.useWatch('mode', configForm) || 'active_learning';
    const selectedSamplingStrategy = Form.useWatch('samplingStrategy', configForm) || '';
    const selectedDeterministicLevel = Form.useWatch('deterministicLevel', configForm) || 'off';
    const selectedOracleInputMode = Form.useWatch(['simulationConfig', 'oracleInputMode'], configForm) || 'select';
    const pluginConfigValues: Record<string, any> = Form.useWatch('pluginConfig', configForm) || {};

    const selectedPlugin = useMemo(
        () => plugins.find((item) => item.pluginId === selectedPluginId),
        [plugins, selectedPluginId],
    );
    const projectAnnotationTypes = useMemo(
        () => project?.enabledAnnotationTypes ?? [],
        [project],
    );
    const pluginConfigSchema = useMemo(
        () => toPluginConfigSchema(selectedPlugin?.requestConfigSchema),
        [selectedPlugin],
    );
    const commitOptions = useMemo(
        () => commits.map((item) => ({
            label: `${item.message || t('project.loopConfig.form.oracleCommitUnknownMessage')} (${item.id.slice(0, 8)})`,
            value: item.id,
            searchText: `${item.id} ${item.message || ''}`.toLowerCase(),
        })),
        [commits, t],
    );

    const refreshLoopData = useCallback(async () => {
        if (!loopId || !projectId) return;
        const [loopRow, pluginCatalog, executorResponse, projectRow, commitRows, labelsRows] = await Promise.all([
            api.getLoopById(loopId),
            api.getRuntimePlugins(),
            api.getRuntimeExecutors(),
            api.getProject(projectId),
            api.getProjectCommits(projectId),
            api.getProjectLabels(projectId),
        ]);

        const nextPlugins = pluginCatalog.items || [];
        setLoop(loopRow);
        setPlugins(nextPlugins);
        setExecutors(Array.isArray(executorResponse?.items) ? executorResponse.items : []);
        setProject(projectRow);
        setLabels(labelsRows);
        setCommits(commitRows);

        const plugin = nextPlugins.find((item) => item.pluginId === loopRow.modelArch);
        const loopConfig = loopRow.config || ({} as any);
        const loopSampling: any = loopConfig.sampling || {};
        const loopModeConfig = loopConfig.mode || {};
        const loopReproducibility = loopConfig.reproducibility || {};
        const loopExecutionConfig = loopConfig.execution || {};
        const oracleCommitId = String(loopModeConfig.oracleCommitId || '').trim();
        const loopSnapshotInit = (loopModeConfig.snapshotInit || {}) as Record<string, any>;
        const rawDeterministicLevel = String(loopReproducibility.deterministicLevel || '').trim().toLowerCase();
        const deterministicLevel =
            rawDeterministicLevel === 'deterministic' || rawDeterministicLevel === 'strong_deterministic'
                ? rawDeterministicLevel
                : 'off';
        const commitExists = commitRows.some((item) => item.id === oracleCommitId);
        const oracleInputMode = oracleCommitId && !commitExists ? 'manual' : 'select';
        configForm.setFieldsValue({
            name: loopRow.name,
            mode: loopRow.mode || 'active_learning',
            modelArch: loopRow.modelArch,
            preferredExecutorId: String(loopExecutionConfig.preferredExecutorId || '').trim() || undefined,
            executionConfig: loopExecutionConfig,
            globalSeed: String(loopReproducibility.globalSeed || ''),
            deterministicLevel,
            samplingStrategy: loopSampling.strategy || pickDefaultSamplingStrategy(plugin),
            queryBatchSize: Number(loopSampling.topk ?? 200),
            pluginConfig: mergePluginConfigWithDefaults(plugin, loopConfig.plugin || {}),
            simulationConfig: {
                oracleInputMode,
                oracleCommitId: oracleInputMode === 'select' ? (oracleCommitId || commitRows[0]?.id) : undefined,
                oracleCommitIdManual: oracleInputMode === 'manual' ? oracleCommitId : '',
                maxRounds: Number(loopModeConfig.maxRounds ?? loopRow.maxRounds ?? 20),
                snapshotInit: {
                    trainSeedRatio: Number(loopSnapshotInit.trainSeedRatio ?? 0.05),
                    valRatio: Number(loopSnapshotInit.valRatio ?? 0.1),
                    testRatio: Number(loopSnapshotInit.testRatio ?? 0.1),
                    valPolicy: String(loopSnapshotInit.valPolicy || 'anchor_only'),
                },
            },
            trainingLabelIds: Array.isArray(loopConfig.training?.includeLabelIds)
                ? loopConfig.training.includeLabelIds
                : [],
            negativeSampleRatio: loopConfig.training?.negativeSampleRatio === null
                ? null
                : Number(loopConfig.training?.negativeSampleRatio ?? 0),
        });
    }, [loopId, projectId, configForm]);

    const executorOptions = useMemo(() => (
        executors.map((executor) => {
            const supportsSelectedPlugin = executorSupportsPlugin(executor, selectedPluginId);
            const statusText = executor.isOnline ? executor.status : 'offline';
            return {
                value: executor.executorId,
                label: `${executor.executorId} · ${statusText} · ${buildExecutorCapabilitySummary(executor)}`,
                searchText: `${executor.executorId} ${statusText} ${buildExecutorCapabilitySummary(executor)}`.toLowerCase(),
                disabled: selectedPluginId ? !supportsSelectedPlugin : false,
            };
        })
    ), [executors, selectedPluginId]);

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
    }, [refreshLoopData, canManageLoops, t]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

    const handleSave = async () => {
        if (!loopId) return;
        try {
            const values = await configForm.validateFields();
            const plugin = plugins.find((item) => item.pluginId === values.modelArch);
            if (!plugin) {
                message.error(t('project.loopConfig.messages.pluginMissing'));
                return;
            }
            if (values.mode !== 'manual' && plugin.supportedStrategies.length === 0) {
                message.error(t('project.loopConfig.messages.noStrategyForPlugin'));
                return;
            }
            setSaving(true);
            const payload = buildLoopUpdatePayload(values, plugin);
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

    const handlePluginConfigChange = useCallback((newValues: Record<string, any>) => {
        configForm.setFieldsValue({pluginConfig: newValues});
    }, [configForm]);

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
    const simulationSnapshotLocked = Boolean(loop.activeSnapshotVersionId);

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
                        <Button type="primary" loading={saving} onClick={handleSave}>
                            {t('project.loopConfig.saveConfig')}
                        </Button>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title={t('project.loopConfig.basicConfig')}>
                <Form form={configForm} layout="vertical">
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <Form.Item
                            name="name"
                            label={t('project.loopConfig.form.name')}
                            rules={[{required: true, message: t('project.loopConfig.form.nameRequired')}]}
                        >
                            <Input/>
                        </Form.Item>
                        <Form.Item
                            name="mode"
                            label={t('project.loopConfig.form.mode')}
                            rules={[{required: true, message: t('project.loopConfig.form.modeRequired')}]}
                        >
                            <Select
                                options={[
                                    {label: t('project.loopConfig.form.modeOptions.activeLearning'), value: 'active_learning'},
                                    {label: t('project.loopConfig.form.modeOptions.simulation'), value: 'simulation'},
                                    {label: t('project.loopConfig.form.modeOptions.manual'), value: 'manual'},
                                ]}
                            />
                        </Form.Item>
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <Form.Item
                            name="modelArch"
                            label={t('project.loopConfig.form.modelArch')}
                            rules={[{required: true, message: t('project.loopConfig.form.modelArchRequired')}]}
                        >
                            <Select
                                options={plugins.map((item) => ({
                                    label: `${item.displayName} (${item.pluginId})`,
                                    value: item.pluginId,
                                }))}
                                onChange={(value) => {
                                    const plugin = plugins.find((item) => item.pluginId === value);
                                    if (!plugin) return;
                                    const currentStrategy = configForm.getFieldValue('samplingStrategy');
                                    const currentPluginConfig = configForm.getFieldValue('pluginConfig') || {};
                                    const currentPreferredExecutorId = String(
                                        configForm.getFieldValue('preferredExecutorId') || '',
                                    ).trim();
                                    const currentPreferredExecutor = executors.find(
                                        (item) => item.executorId === currentPreferredExecutorId,
                                    );
                                    configForm.setFieldsValue({
                                        samplingStrategy:
                                            plugin.supportedStrategies.includes(currentStrategy)
                                                ? currentStrategy
                                                : pickDefaultSamplingStrategy(plugin),
                                        pluginConfig: mergePluginConfigWithDefaults(plugin, currentPluginConfig),
                                        preferredExecutorId: (
                                            currentPreferredExecutor
                                            && !executorSupportsPlugin(currentPreferredExecutor, String(value))
                                        )
                                            ? undefined
                                            : currentPreferredExecutorId || undefined,
                                    });
                                }}
                            />
                        </Form.Item>
                        <Form.Item
                            name="preferredExecutorId"
                            label={t('project.loopConfig.form.preferredExecutor')}
                            extra={t('project.loopConfig.form.preferredExecutorHint')}
                        >
                            <Select
                                allowClear
                                showSearch
                                placeholder={t('project.loopConfig.form.preferredExecutorPlaceholder')}
                                options={executorOptions}
                                filterOption={(input, option) => {
                                    const haystack = String((option as any)?.searchText || '').toLowerCase();
                                    return haystack.includes(input.toLowerCase());
                                }}
                            />
                        </Form.Item>
                    </div>

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                        {selectedMode !== 'manual' ? (
                            <Form.Item
                                name="samplingStrategy"
                                label={t('project.loopConfig.form.samplingStrategy')}
                                rules={[{required: true, message: t('project.loopConfig.form.samplingStrategyRequired')}]}
                            >
                                <Select
                                    options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                                />
                            </Form.Item>
                        ) : null}
                        <Form.Item
                            name="trainingLabelIds"
                            label={t('project.loopConfig.form.trainingLabelScope')}
                            extra={
                                loop.lifecycle === 'draft'
                                    ? t('project.loopConfig.form.trainingLabelScopeHint')
                                    : t('project.loopConfig.form.trainingLabelScopeImmutable')
                            }
                        >
                            <Select
                                mode="multiple"
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                placeholder={t('project.loopConfig.form.trainingLabelScopePlaceholder')}
                                options={labels.map((item) => ({
                                    label: item.name,
                                    value: item.id,
                                }))}
                                disabled={loop.lifecycle !== 'draft'}
                            />
                        </Form.Item>
                        <Form.Item
                            name="negativeSampleRatio"
                            label={t('project.loopConfig.form.negativeSampleRatio')}
                            extra={
                                loop.lifecycle === 'draft'
                                    ? t('project.loopConfig.form.negativeSampleRatioHint')
                                    : t('project.loopConfig.form.negativeSampleRatioImmutable')
                            }
                        >
                            <InputNumber
                                min={0}
                                step={0.1}
                                className="w-full"
                                placeholder={t('project.loopConfig.form.negativeSampleRatioPlaceholder')}
                                disabled={loop.lifecycle !== 'draft'}
                            />
                        </Form.Item>
                    </div>

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                        <Form.Item
                            name="globalSeed"
                            label={t('project.loopConfig.form.globalSeed')}
                            rules={[{required: true, message: t('project.loopConfig.form.globalSeedRequired')}]}
                            extra={loop.lifecycle === 'draft' ? undefined : t('project.loopConfig.form.globalSeedImmutable')}
                        >
                            <Input disabled={loop.lifecycle !== 'draft'} />
                        </Form.Item>
                        <Form.Item
                            name="deterministicLevel"
                            label={t('project.loopConfig.form.deterministicLevel')}
                            rules={[{required: true, message: t('project.loopConfig.form.deterministicLevelRequired')}]}
                            extra={
                                loop.lifecycle === 'draft'
                                    ? undefined
                                    : t('project.loopConfig.form.deterministicLevelImmutable')
                            }
                        >
                            <Select
                                disabled={loop.lifecycle !== 'draft'}
                                options={[
                                    {label: t('project.loopConfig.form.deterministicLevelOptions.off'), value: 'off'},
                                    {
                                        label: t('project.loopConfig.form.deterministicLevelOptions.deterministic'),
                                        value: 'deterministic',
                                    },
                                    {
                                        label: t('project.loopConfig.form.deterministicLevelOptions.strongDeterministic'),
                                        value: 'strong_deterministic',
                                    },
                                ]}
                            />
                        </Form.Item>
                        {selectedDeterministicLevel !== 'off' ? (
                            <Alert
                                type="warning"
                                showIcon
                                message={t('project.loopConfig.form.deterministicLevelPerfHint')}
                            />
                        ) : null}
                        {selectedMode !== 'manual' ? (
                            <Form.Item name="queryBatchSize" label={t('project.loopConfig.form.queryBatchSize')}>
                                <InputNumber min={1} max={5000} className="w-full"/>
                            </Form.Item>
                        ) : null}
                    </div>

                    {selectedMode === 'simulation' ? (
                        <div>
                            <div className="mb-2 font-semibold">{t('project.loopConfig.form.simulationConfigTitle')}</div>
                            <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                                <Form.Item
                                    name={['simulationConfig', 'oracleInputMode']}
                                    label={t('project.loopConfig.form.oracleCommitInputMode')}
                                    rules={[{required: true, message: t('project.loopConfig.form.oracleCommitInputModeRequired')}]}
                                >
                                    <Radio.Group
                                        disabled={simulationSnapshotLocked}
                                        options={[
                                            {label: t('project.loopConfig.form.oracleCommitSelect'), value: 'select'},
                                            {label: t('project.loopConfig.form.oracleCommitManual'), value: 'manual'},
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name={['simulationConfig', 'maxRounds']}
                                    label={t('project.loopConfig.form.maxRounds')}
                                    rules={[{required: true, message: t('project.loopConfig.form.maxRoundsRequired')}]}
                                >
                                    <InputNumber min={1} max={10000} className="w-full"/>
                                </Form.Item>
                            </div>
                            <div className="grid grid-cols-1 gap-x-4 md:grid-cols-3">
                                {selectedOracleInputMode === 'manual' ? (
                                    <Form.Item
                                        name={['simulationConfig', 'oracleCommitIdManual']}
                                        label={t('project.loopConfig.form.oracleCommitIdManual')}
                                        rules={[
                                            {required: true, message: t('project.loopConfig.form.oracleCommitIdRequired')},
                                            {
                                                validator: (_, value) => {
                                                    const text = String(value || '').trim();
                                                    if (!text) {
                                                        return Promise.reject(new Error(t('project.loopConfig.form.oracleCommitIdRequired')));
                                                    }
                                                    if (!UUID_RE.test(text)) {
                                                        return Promise.reject(new Error(t('project.loopConfig.form.oracleCommitIdInvalid')));
                                                    }
                                                    return Promise.resolve();
                                                },
                                            },
                                        ]}
                                    >
                                        <Input
                                            placeholder={t('project.loopConfig.form.oracleCommitIdPlaceholder')}
                                            disabled={simulationSnapshotLocked}
                                        />
                                    </Form.Item>
                                ) : (
                                    <Form.Item
                                        name={['simulationConfig', 'oracleCommitId']}
                                        label={t('project.loopConfig.form.oracleCommitId')}
                                        rules={[{required: true, message: t('project.loopConfig.form.oracleCommitIdRequired')}]}
                                    >
                                        <Select
                                            showSearch
                                            options={commitOptions}
                                            placeholder={t('project.loopConfig.form.oracleCommitIdSelectPlaceholder')}
                                            disabled={simulationSnapshotLocked}
                                            filterOption={(input, option) => {
                                                const haystack = String((option as any)?.searchText || '').toLowerCase();
                                                return haystack.includes(input.toLowerCase());
                                            }}
                                        />
                                    </Form.Item>
                                )}
                                <Form.Item
                                    name={['simulationConfig', 'snapshotInit', 'trainSeedRatio']}
                                    label={t('project.loopConfig.form.snapshotInitTrainSeedRatio')}
                                >
                                    <Slider
                                        min={0}
                                        max={1}
                                        step={0.001}
                                        disabled={simulationSnapshotLocked}
                                        marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                        tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name={['simulationConfig', 'snapshotInit', 'valRatio']}
                                    label={t('project.loopConfig.form.snapshotInitValRatio')}
                                >
                                    <Slider
                                        min={0}
                                        max={1}
                                        step={0.001}
                                        disabled={simulationSnapshotLocked}
                                        marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                        tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name={['simulationConfig', 'snapshotInit', 'testRatio']}
                                    label={t('project.loopConfig.form.snapshotInitTestRatio')}
                                >
                                    <Slider
                                        min={0}
                                        max={1}
                                        step={0.001}
                                        disabled={simulationSnapshotLocked}
                                        marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                        tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name={['simulationConfig', 'snapshotInit', 'valPolicy']}
                                    label={t('project.loopConfig.form.snapshotInitValPolicy')}
                                >
                                    <Select
                                        disabled={simulationSnapshotLocked}
                                        options={[
                                            {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                            {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                                        ]}
                                    />
                                </Form.Item>
                            </div>
                        </div>
                    ) : null}

                    <Card
                        size="small"
                        className="!border-github-border !bg-github-panel"
                        title={selectedPlugin?.requestConfigSchema?.title || t('project.loopConfig.form.modelRequestParams')}
                    >
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
                                    samplingStrategy: selectedSamplingStrategy,
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
