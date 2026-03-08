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
    Typography,
    message,
} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams} from 'react-router-dom';

import {DynamicConfigForm} from '../../../components/common';
import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {
    CommitHistoryItem,
    Loop,
    Project,
    ProjectLabel,
    ProjectBranch,
    RuntimeExecutorRead,
    RuntimePluginCatalogItem,
} from '../../../types';
import {toPluginConfigSchema} from './loopFormSchemaAdapter';
import {
    buildLoopCreatePayload,
    LoopEditorFormValues,
    mergePluginConfigWithDefaults,
    pickDefaultSamplingStrategy,
    RANDOM_BASELINE_STRATEGY,
} from './loopPayloadBuilder';
import {buildExecutorCapabilitySummary, executorSupportsPlugin} from '../../runtime/executorCapability';

const {Title, Text} = Typography;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const ProjectLoopCreate: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');

    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [executors, setExecutors] = useState<RuntimeExecutorRead[]>([]);
    const [commits, setCommits] = useState<CommitHistoryItem[]>([]);
    const [project, setProject] = useState<Project | null>(null);
    const [labels, setLabels] = useState<ProjectLabel[]>([]);
    const [createForm] = Form.useForm<LoopEditorFormValues>();

    const selectedMode = Form.useWatch('mode', createForm) || 'active_learning';
    const selectedSamplingStrategy = Form.useWatch('samplingStrategy', createForm) || '';
    const selectedDeterministicLevel = Form.useWatch('deterministicLevel', createForm) || 'off';
    const selectedPluginId = Form.useWatch('modelArch', createForm);
    const selectedOracleInputMode = Form.useWatch(['simulationConfig', 'oracleInputMode'], createForm) || 'select';
    const pluginConfigValues: Record<string, any> = Form.useWatch('pluginConfig', createForm) || {};

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

    const availableBranches = useMemo(() => {
        const bound = new Set(loops.map((item) => item.branchId));
        return branches.filter((branch) => !bound.has(branch.id));
    }, [loops, branches]);

    const commitOptions = useMemo(
        () => commits.map((item) => ({
            label: `${item.message || t('project.loopCreate.form.oracleCommitUnknownMessage')} (${item.id.slice(0, 8)})`,
            value: item.id,
            searchText: `${item.id} ${item.message || ''}`.toLowerCase(),
        })),
        [commits, t],
    );

    const loadData = useCallback(async () => {
        if (!projectId || !canManageLoops) return;
        setLoading(true);
        try {
            const [loopRows, branchRows, pluginCatalog, executorResponse, commitRows, projectRow, labelsRows] = await Promise.all([
                api.getProjectLoops(projectId),
                api.getProjectBranches(projectId),
                api.getRuntimePlugins(),
                api.getRuntimeExecutors(),
                api.getProjectCommits(projectId),
                api.getProject(projectId),
                api.getProjectLabels(projectId),
            ]);
            const runtimeExecutors = Array.isArray(executorResponse?.items)
                ? executorResponse.items as RuntimeExecutorRead[]
                : [];
            const nextPlugins = pluginCatalog.items || [];
            setLoops(loopRows);
            setBranches(branchRows);
            setPlugins(nextPlugins);
            setExecutors(runtimeExecutors);
            setCommits(commitRows);
            setProject(projectRow);
            setLabels(labelsRows);

            const bound = new Set(loopRows.map((item) => item.branchId));
            const openBranches = branchRows.filter((branch) => !bound.has(branch.id));
            const firstPlugin = nextPlugins[0];
            const defaultStrategy = pickDefaultSamplingStrategy(firstPlugin);
            createForm.setFieldsValue({
                name: '',
                branchId: openBranches[0]?.id,
                mode: 'active_learning',
                modelArch: firstPlugin?.pluginId,
                preferredExecutorId: undefined,
                executionConfig: {},
                globalSeed: '',
                deterministicLevel: 'off',
                samplingStrategy: defaultStrategy || RANDOM_BASELINE_STRATEGY,
                queryBatchSize: 200,
                pluginConfig: mergePluginConfigWithDefaults(firstPlugin, {}),
                simulationConfig: {
                    oracleInputMode: 'select',
                    oracleCommitId: commitRows[0]?.id,
                    oracleCommitIdManual: '',
                    maxRounds: 20,
                    snapshotInit: {
                        trainSeedRatio: 0.05,
                        valRatio: 0.1,
                        testRatio: 0.1,
                        valPolicy: 'anchor_only',
                    },
                },
                trainingLabelIds: [],
                negativeSampleRatio: null,
            });
        } catch (error: any) {
            message.error(error?.message || t('project.loopCreate.messages.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [projectId, canManageLoops, createForm, t]);

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

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

    const handlePluginConfigChange = useCallback((newValues: Record<string, any>) => {
        createForm.setFieldsValue({pluginConfig: newValues});
    }, [createForm]);

    const handleCreate = async () => {
        if (!projectId) return;
        try {
            const values = await createForm.validateFields();
            const plugin = plugins.find((item) => item.pluginId === values.modelArch);
            if (!plugin) {
                message.error(t('project.loopCreate.messages.pluginMissing'));
                return;
            }
            if (values.mode !== 'manual' && plugin.supportedStrategies.length === 0) {
                message.error(t('project.loopCreate.messages.noStrategyForPlugin'));
                return;
            }
            setCreating(true);
            const payload = buildLoopCreatePayload(values, plugin);
            const created = await api.createProjectLoop(projectId, payload);
            message.success(t('project.loopCreate.messages.createSuccess'));
            navigate(`/projects/${projectId}/loops/${created.id}`);
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || t('project.loopCreate.messages.createFailed'));
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
                <Alert type="warning" showIcon message={t('project.loopCreate.noPermission')}/>
            </Card>
        );
    }

    const canSubmit = plugins.length > 0 && availableBranches.length > 0;

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <Title level={4} className="!mb-1">{t('project.loopCreate.title')}</Title>
                        <Text type="secondary">{t('project.loopCreate.subtitle')}</Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>
                            {t('project.loopCreate.backToOverview')}
                        </Button>
                        <Button onClick={loadData}>{t('project.loopCreate.reload')}</Button>
                    </div>
                </div>
                {plugins.length === 0 ? (
                    <Alert
                        className="!mt-4"
                        type="warning"
                        showIcon
                        message={t('project.loopCreate.noPluginCatalog')}
                        description={t('project.loopCreate.noPluginCatalogDesc')}
                    />
                ) : null}
                {availableBranches.length === 0 ? (
                    <Alert
                        className="!mt-4"
                        type="warning"
                        showIcon
                        message={t('project.loopCreate.form.branchNoAvailable')}
                    />
                ) : null}
            </Card>

            <Form form={createForm} layout="vertical">
                <Card className="!border-github-border !bg-github-panel" title={t('project.loopCreate.section.basic')}>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <Form.Item
                            name="name"
                            label={t('project.loopCreate.form.name')}
                            rules={[{required: true, message: t('project.loopCreate.form.nameRequired')}]}
                        >
                            <Input placeholder={t('project.loopCreate.form.namePlaceholder')}/>
                        </Form.Item>
                        <Form.Item
                            name="branchId"
                            label={t('project.loopCreate.form.branchId')}
                            rules={[{required: true, message: t('project.loopCreate.form.branchIdRequired')}]}
                        >
                            <Select
                                options={availableBranches.map((item) => ({label: item.name, value: item.id}))}
                                disabled={availableBranches.length === 0}
                            />
                        </Form.Item>
                    </div>

                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-4">
                        <Form.Item
                            name="mode"
                            label={t('project.loopCreate.form.mode')}
                            rules={[{required: true, message: t('project.loopCreate.form.modeRequired')}]}
                        >
                            <Select
                                options={[
                                    {label: t('project.loopCreate.form.modeOptions.activeLearning'), value: 'active_learning'},
                                    {label: t('project.loopCreate.form.modeOptions.simulation'), value: 'simulation'},
                                    {label: t('project.loopCreate.form.modeOptions.manual'), value: 'manual'},
                                ]}
                            />
                        </Form.Item>
                        <Form.Item
                            name="modelArch"
                            label={t('project.loopCreate.form.modelArch')}
                            rules={[{required: true, message: t('project.loopCreate.form.modelArchRequired')}]}
                        >
                            <Select
                                options={plugins.map((item) => ({
                                    label: `${item.displayName} (${item.pluginId})`,
                                    value: item.pluginId,
                                }))}
                                onChange={(value) => {
                                    const plugin = plugins.find((item) => item.pluginId === value);
                                    if (!plugin) return;
                                    const currentStrategy = createForm.getFieldValue('samplingStrategy');
                                    const currentPluginConfig = createForm.getFieldValue('pluginConfig') || {};
                                    const currentPreferredExecutorId = String(
                                        createForm.getFieldValue('preferredExecutorId') || '',
                                    ).trim();
                                    const currentPreferredExecutor = executors.find(
                                        (item) => item.executorId === currentPreferredExecutorId,
                                    );
                                    createForm.setFieldsValue({
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
                            name="globalSeed"
                            label={t('project.loopCreate.form.globalSeed')}
                            rules={[
                                {required: true, message: t('project.loopCreate.form.globalSeedRequired')},
                                {
                                    validator: (_, value) => (
                                        String(value || '').trim()
                                            ? Promise.resolve()
                                            : Promise.reject(new Error(t('project.loopCreate.form.globalSeedRequired')))
                                    ),
                                },
                            ]}
                        >
                            <Input placeholder={t('project.loopCreate.form.globalSeedPlaceholder')}/>
                        </Form.Item>
                        <Form.Item
                            name="deterministicLevel"
                            label={t('project.loopCreate.form.deterministicLevel')}
                            rules={[{required: true, message: t('project.loopCreate.form.deterministicLevelRequired')}]}
                        >
                            <Select
                                options={[
                                    {label: t('project.loopCreate.form.deterministicLevelOptions.off'), value: 'off'},
                                    {
                                        label: t('project.loopCreate.form.deterministicLevelOptions.deterministic'),
                                        value: 'deterministic',
                                    },
                                    {
                                        label: t('project.loopCreate.form.deterministicLevelOptions.strongDeterministic'),
                                        value: 'strong_deterministic',
                                    },
                                ]}
                            />
                        </Form.Item>
                        {selectedDeterministicLevel !== 'off' ? (
                            <Alert
                                type="warning"
                                showIcon
                                message={t('project.loopCreate.form.deterministicLevelPerfHint')}
                            />
                        ) : null}
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                        <Form.Item
                            name="preferredExecutorId"
                            label={t('project.loopCreate.form.preferredExecutor')}
                            extra={t('project.loopCreate.form.preferredExecutorHint')}
                        >
                            <Select
                                allowClear
                                showSearch
                                placeholder={t('project.loopCreate.form.preferredExecutorPlaceholder')}
                                options={executorOptions}
                                filterOption={(input, option) => {
                                    const haystack = String((option as any)?.searchText || '').toLowerCase();
                                    return haystack.includes(input.toLowerCase());
                                }}
                            />
                        </Form.Item>
                    </div>
                </Card>

                <Card className="!mt-4 !border-github-border !bg-github-panel" title={t('project.loopCreate.section.mode')}>
                    <Alert
                        type="info"
                        showIcon
                        message={t(`project.loopCreate.form.payloadModeHint.${selectedMode}`)}
                    />
                    <div className="mt-4 grid grid-cols-1 gap-x-4 md:grid-cols-3">
                        {selectedMode !== 'manual' ? (
                            <>
                                <Form.Item
                                    name="samplingStrategy"
                                    label={t('project.loopCreate.form.samplingStrategy')}
                                    rules={[{required: true, message: t('project.loopCreate.form.samplingStrategyRequired')}]}
                                >
                                    <Select
                                        options={(selectedPlugin?.supportedStrategies || []).map((item) => ({label: item, value: item}))}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name="queryBatchSize"
                                    label={t('project.loopCreate.form.queryBatchSize')}
                                    rules={[{required: true, message: t('project.loopCreate.form.queryBatchSizeRequired')}]}
                                >
                                    <InputNumber min={1} max={5000} className="w-full"/>
                                </Form.Item>
                            </>
                        ) : null}
                        <Form.Item
                            name="trainingLabelIds"
                            label={t('project.loopCreate.form.trainingLabelScope')}
                            extra={t('project.loopCreate.form.trainingLabelScopeHint')}
                        >
                            <Select
                                mode="multiple"
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                placeholder={t('project.loopCreate.form.trainingLabelScopePlaceholder')}
                                options={labels.map((item) => ({
                                    label: item.name,
                                    value: item.id,
                                }))}
                            />
                        </Form.Item>
                        <Form.Item
                            name="negativeSampleRatio"
                            label={t('project.loopCreate.form.negativeSampleRatio')}
                            extra={t('project.loopCreate.form.negativeSampleRatioHint')}
                        >
                            <InputNumber
                                min={0}
                                step={0.1}
                                className="w-full"
                                placeholder={t('project.loopCreate.form.negativeSampleRatioPlaceholder')}
                            />
                        </Form.Item>
                    </div>

                    {selectedMode === 'simulation' ? (
                        <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2">
                            <Form.Item
                                name={['simulationConfig', 'oracleInputMode']}
                                label={t('project.loopCreate.form.oracleCommitInputMode')}
                                rules={[{required: true, message: t('project.loopCreate.form.oracleCommitInputModeRequired')}]}
                            >
                                <Radio.Group
                                    options={[
                                        {label: t('project.loopCreate.form.oracleCommitSelect'), value: 'select'},
                                        {label: t('project.loopCreate.form.oracleCommitManual'), value: 'manual'},
                                    ]}
                                />
                            </Form.Item>
                            <Form.Item
                                name={['simulationConfig', 'maxRounds']}
                                label={t('project.loopCreate.form.maxRounds')}
                                rules={[{required: true, message: t('project.loopCreate.form.maxRoundsRequired')}]}
                            >
                                <InputNumber min={1} max={10000} className="w-full"/>
                            </Form.Item>

                            {selectedOracleInputMode === 'manual' ? (
                                <Form.Item
                                    name={['simulationConfig', 'oracleCommitIdManual']}
                                    label={t('project.loopCreate.form.oracleCommitIdManual')}
                                    rules={[
                                        {required: true, message: t('project.loopCreate.form.oracleCommitIdRequired')},
                                        {
                                            validator: (_, value) => {
                                                const text = String(value || '').trim();
                                                if (!text) {
                                                    return Promise.reject(new Error(t('project.loopCreate.form.oracleCommitIdRequired')));
                                                }
                                                if (!UUID_RE.test(text)) {
                                                    return Promise.reject(new Error(t('project.loopCreate.form.oracleCommitIdInvalid')));
                                                }
                                                return Promise.resolve();
                                            },
                                        },
                                    ]}
                                >
                                    <Input placeholder={t('project.loopCreate.form.oracleCommitIdPlaceholder')}/>
                                </Form.Item>
                            ) : (
                                <Form.Item
                                    name={['simulationConfig', 'oracleCommitId']}
                                    label={t('project.loopCreate.form.oracleCommitId')}
                                    rules={[{required: true, message: t('project.loopCreate.form.oracleCommitIdRequired')}]}
                                >
                                    <Select
                                        showSearch
                                        options={commitOptions}
                                        placeholder={t('project.loopCreate.form.oracleCommitIdSelectPlaceholder')}
                                        filterOption={(input, option) => {
                                            const haystack = String((option as any)?.searchText || '').toLowerCase();
                                            return haystack.includes(input.toLowerCase());
                                        }}
                                    />
                                </Form.Item>
                            )}

                            <Form.Item
                                name={['simulationConfig', 'snapshotInit', 'trainSeedRatio']}
                                label={t('project.loopCreate.form.snapshotInitTrainSeedRatio')}
                            >
                                <Slider
                                    min={0}
                                    max={1}
                                    step={0.001}
                                    marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                    tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                />
                            </Form.Item>
                            <Form.Item
                                name={['simulationConfig', 'snapshotInit', 'valRatio']}
                                label={t('project.loopCreate.form.snapshotInitValRatio')}
                            >
                                <Slider
                                    min={0}
                                    max={1}
                                    step={0.001}
                                    marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                    tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                />
                            </Form.Item>
                            <Form.Item
                                name={['simulationConfig', 'snapshotInit', 'testRatio']}
                                label={t('project.loopCreate.form.snapshotInitTestRatio')}
                            >
                                <Slider
                                    min={0}
                                    max={1}
                                    step={0.001}
                                    marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                                    tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                                />
                            </Form.Item>
                            <Form.Item
                                name={['simulationConfig', 'snapshotInit', 'valPolicy']}
                                label={t('project.loopCreate.form.snapshotInitValPolicy')}
                            >
                                <Select
                                    options={[
                                        {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                        {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                                    ]}
                                />
                            </Form.Item>
                        </div>
                    ) : null}
                </Card>

                <Card
                    className="!mt-4 !border-github-border !bg-github-panel"
                    title={selectedPlugin?.requestConfigSchema?.title || t('project.loopCreate.form.modelRequestParams')}
                    extra={<Text type="secondary">{t('project.loopCreate.form.pluginSchemaHint')}</Text>}
                >
                    {pluginConfigSchema.fields.length === 0 ? (
                        <Alert type="info" showIcon message={t('project.loopCreate.form.noDynamicSchema')}/>
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
                            form={createForm}
                            namePrefix="pluginConfig"
                        />
                    )}
                </Card>

                <Card className="!mt-4 !border-github-border !bg-github-panel">
                    <div className="flex flex-wrap items-center justify-end gap-2">
                        <Button onClick={() => navigate(`/projects/${projectId}/loops`)}>
                            {t('project.loopCreate.cancel')}
                        </Button>
                        <Button
                            type="primary"
                            loading={creating}
                            disabled={!canSubmit}
                            onClick={handleCreate}
                        >
                            {t('project.loopCreate.submit')}
                        </Button>
                    </div>
                </Card>
            </Form>
        </div>
    );
};

export default ProjectLoopCreate;
