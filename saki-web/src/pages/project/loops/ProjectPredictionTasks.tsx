import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button, Card, Form, Modal, Select, Slider, Space, Table, Tag, Typography, message} from 'antd';
import {PlusOutlined, ReloadOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {api} from '../../../services/api';
import {
    CommitHistoryItem,
    Loop,
    PredictionSetGenerateRequest,
    PredictionTaskRead,
    ProjectBranch,
    ProjectModel,
    RuntimePluginCatalogItem,
    RuntimeRound,
    RuntimeRoundArtifact,
} from '../../../types';

const statusColor: Record<string, string> = {
    queued: 'default',
    running: 'processing',
    materializing: 'processing',
    ready: 'success',
    applied: 'success',
    failed: 'error',
};

type ScopeStatus = 'all' | 'unlabeled' | 'labeled' | 'draft';
type ModelSourceKind = 'round_artifact' | 'model';

interface TaskFormValues {
    pluginId: string;
    targetRoundId: string;
    modelSourceKind: ModelSourceKind;
    sourceRoundId?: string;
    modelId?: string;
    artifactName?: string;
    targetBranchId: string;
    baseCommitId: string;
    predictConf?: number;
    scopeStatus: ScopeStatus;
}

const ProjectPredictionTasks: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const [messageApi, contextHolder] = message.useMessage();
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [createOpen, setCreateOpen] = useState(false);
    const [tasks, setTasks] = useState<PredictionTaskRead[]>([]);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [roundsByLoopId, setRoundsByLoopId] = useState<Record<string, RuntimeRound[]>>({});
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [models, setModels] = useState<ProjectModel[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [roundArtifactNames, setRoundArtifactNames] = useState<Record<string, string[]>>({});
    const [branchCommits, setBranchCommits] = useState<CommitHistoryItem[]>([]);
    const [form] = Form.useForm<TaskFormValues>();
    const quickAppliedRef = useRef(false);
    const pluginId = Form.useWatch('pluginId', form);
    const modelSourceKind = Form.useWatch('modelSourceKind', form);
    const sourceRoundId = Form.useWatch('sourceRoundId', form);
    const modelId = Form.useWatch('modelId', form);

    const predictPluginIds = useMemo(
        () => plugins
            .filter((item) => (item.supportedStepTypes || []).map((v) => String(v).toLowerCase()).includes('predict'))
            .map((item) => item.pluginId),
        [plugins],
    );

    const roundOptions = useMemo(() => {
        const options: RuntimeRound[] = [];
        loops.forEach((loop) => {
            const rounds = roundsByLoopId[loop.id] || [];
            rounds.forEach((round) => options.push(round));
        });
        return options.sort((a, b) => {
            if (a.roundIndex !== b.roundIndex) return b.roundIndex - a.roundIndex;
            return (b.attemptIndex || 0) - (a.attemptIndex || 0);
        });
    }, [loops, roundsByLoopId]);

    const pluginOptions = useMemo(() => {
        const fromRounds = roundOptions.map((item) => String(item.pluginId || '').trim()).filter(Boolean);
        const fromModels = models.map((item) => String(item.pluginId || '').trim()).filter(Boolean);
        const merged = new Set<string>([...predictPluginIds, ...fromRounds, ...fromModels]);
        return Array.from(merged).sort((a, b) => a.localeCompare(b));
    }, [models, predictPluginIds, roundOptions]);

    const scopedRoundOptions = useMemo(() => {
        if (!pluginId) return roundOptions;
        return roundOptions.filter((item) => String(item.pluginId || '') === String(pluginId));
    }, [pluginId, roundOptions]);

    const scopedModelOptions = useMemo(() => {
        if (!pluginId) return models;
        return models.filter((item) => String(item.pluginId || '') === String(pluginId));
    }, [models, pluginId]);

    const artifactOptions = useMemo(() => {
        if (modelSourceKind === 'model') {
            const model = scopedModelOptions.find((item) => item.id === modelId);
            const names = model && model.artifacts && typeof model.artifacts === 'object'
                ? Object.keys(model.artifacts).filter((name) => Boolean(String(name || '').trim()))
                : [];
            const unique = Array.from(new Set<string>(names));
            if (unique.length === 0) {
                return [{value: 'best.pt', label: 'best.pt'}];
            }
            return unique.sort((a, b) => a.localeCompare(b)).map((name) => ({value: name, label: name}));
        }
        const names = sourceRoundId ? (roundArtifactNames[sourceRoundId] || []) : [];
        if (names.length === 0) {
            return [{value: 'best.pt', label: 'best.pt'}];
        }
        return names.map((name) => ({value: name, label: name}));
    }, [modelSourceKind, modelId, scopedModelOptions, sourceRoundId, roundArtifactNames]);

    const commitOptions = useMemo(() => {
        return branchCommits.map((item) => {
            const hash = String(item.commitHash || '').slice(0, 8) || String(item.id || '').slice(0, 8);
            const message = String(item.message || '').trim() || '(no message)';
            return {
                value: item.id,
                label: `${hash}  ${message}`,
            };
        });
    }, [branchCommits]);

    const refresh = useCallback(async () => {
        if (!projectId) return;
        setLoading(true);
        try {
            const [taskRows, loopRows, branchRows, modelRows, pluginCatalog] = await Promise.all([
                api.listPredictionTasks(projectId, 100),
                api.getProjectLoops(projectId),
                api.getProjectBranches(projectId),
                api.getProjectModels(projectId, 100).catch(() => []),
                api.getRuntimePlugins().catch(() => ({items: []})),
            ]);
            setTasks(taskRows);
            setLoops(loopRows);
            setBranches(branchRows);
            setModels(modelRows);
            setPlugins(Array.isArray(pluginCatalog?.items) ? pluginCatalog.items : []);

            const roundEntries: Array<readonly [string, RuntimeRound[]]> = await Promise.all(
                loopRows.map(async (loop: Loop) => {
                    const rows = await api.getLoopRounds(loop.id, 100).catch(() => []);
                    return [loop.id, rows] as const;
                }),
            );
            const roundMap: Record<string, RuntimeRound[]> = {};
            roundEntries.forEach(([loopId, rows]: readonly [string, RuntimeRound[]]) => {
                roundMap[loopId] = rows;
            });
            setRoundsByLoopId(roundMap);
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.messages.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [api, projectId, messageApi, t]);

    const ensureRoundArtifacts = useCallback(async (roundId?: string) => {
        const normalized = String(roundId || '').trim();
        if (!normalized) return;
        if (roundArtifactNames[normalized]?.length) return;
        try {
            const response = await api.getRoundArtifacts(normalized, 2000);
            const names = Array.from(
                new Set(
                    (response.items || [])
                        .map((item: RuntimeRoundArtifact) => String(item.name || '').trim())
                        .filter(Boolean),
                ),
            ).sort((a, b) => a.localeCompare(b));
            setRoundArtifactNames((prev) => ({...prev, [normalized]: names}));
        } catch (_error) {
            setRoundArtifactNames((prev) => ({...prev, [normalized]: []}));
        }
    }, [api, roundArtifactNames]);

    const loadBranchCommits = useCallback(async (branchId?: string) => {
        if (!projectId) return;
        const branch = branches.find((item) => item.id === branchId);
        if (!branch?.headCommitId) {
            setBranchCommits([]);
            form.setFieldValue('baseCommitId', '');
            return;
        }
        try {
            const rows = await api.getCommitHistory(branch.headCommitId, 100);
            const commits = Array.isArray(rows) ? rows : [];
            setBranchCommits(commits);
            const current = String(form.getFieldValue('baseCommitId') || '').trim();
            const exists = commits.some((item) => item.id === current);
            if (!exists) {
                form.setFieldValue('baseCommitId', commits[0]?.id || branch.headCommitId);
            }
        } catch (_error) {
            const fallback: CommitHistoryItem[] = [{
                id: branch.headCommitId,
                commitHash: branch.headCommitId.slice(0, 8),
                message: branch.headCommitMessage || '(head commit)',
                authorType: 'system',
                createdAt: '',
            }];
            setBranchCommits(fallback);
            form.setFieldValue('baseCommitId', branch.headCommitId);
        }
    }, [api, branches, form, projectId]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    useEffect(() => {
        if (quickAppliedRef.current) return;
        const targetRoundId = searchParams.get('targetRoundId');
        if (!targetRoundId) return;
        if (roundOptions.length === 0 || branches.length === 0) return;
        const round = roundOptions.find((item) => item.id === targetRoundId) || roundOptions[0];
        const branchId = searchParams.get('targetBranchId') || branches[0]?.id;
        const branch = branches.find((item) => item.id === branchId) || branches[0];
        form.setFieldsValue({
            pluginId: String(round?.pluginId || ''),
            targetRoundId: round?.id,
            modelSourceKind: 'round_artifact',
            sourceRoundId: round?.id,
            artifactName: searchParams.get('artifactName') || 'best.pt',
            targetBranchId: branch?.id,
            baseCommitId: branch?.headCommitId,
            predictConf: 0.1,
            scopeStatus: (searchParams.get('scopeStatus') as ScopeStatus) || 'all',
        });
        void ensureRoundArtifacts(round?.id);
        void loadBranchCommits(branch?.id);
        quickAppliedRef.current = true;
        setCreateOpen(true);
    }, [branches, ensureRoundArtifacts, form, loadBranchCommits, roundOptions, searchParams]);

    const onOpenCreate = useCallback(() => {
        const defaultRound = roundOptions[0];
        const defaultBranch = branches[0];
        form.setFieldsValue({
            pluginId: String(defaultRound?.pluginId || ''),
            targetRoundId: defaultRound?.id,
            modelSourceKind: 'round_artifact',
            sourceRoundId: defaultRound?.id,
            artifactName: 'best.pt',
            targetBranchId: defaultBranch?.id,
            baseCommitId: defaultBranch?.headCommitId,
            predictConf: 0.1,
            scopeStatus: 'all',
        });
        void ensureRoundArtifacts(defaultRound?.id);
        void loadBranchCommits(defaultBranch?.id);
        setCreateOpen(true);
    }, [branches, ensureRoundArtifacts, form, loadBranchCommits, roundOptions]);

    const onRoundChanged = useCallback((roundId?: string) => {
        if (!roundId) return;
        const row = scopedRoundOptions.find((item) => item.id === roundId) || roundOptions.find((item) => item.id === roundId);
        if (row?.pluginId) {
            form.setFieldValue('pluginId', row.pluginId);
        }
        const kind = form.getFieldValue('modelSourceKind');
        if (kind === 'round_artifact') {
            form.setFieldValue('sourceRoundId', roundId);
            void ensureRoundArtifacts(roundId);
        }
    }, [ensureRoundArtifacts, form, roundOptions, scopedRoundOptions]);

    const onPluginChanged = useCallback((nextPluginId?: string) => {
        const normalized = String(nextPluginId || '').trim();
        if (!normalized) return;
        const candidateRounds = roundOptions.filter((item) => String(item.pluginId || '') === normalized);
        const currentTargetRound = String(form.getFieldValue('targetRoundId') || '').trim();
        if (!candidateRounds.some((item) => item.id === currentTargetRound)) {
            const nextRoundId = candidateRounds[0]?.id;
            form.setFieldValue('targetRoundId', nextRoundId);
            if (form.getFieldValue('modelSourceKind') === 'round_artifact') {
                form.setFieldValue('sourceRoundId', nextRoundId);
                void ensureRoundArtifacts(nextRoundId);
            }
        }
        if (form.getFieldValue('modelSourceKind') === 'model') {
            const candidateModels = models.filter((item) => String(item.pluginId || '') === normalized);
            const currentModelId = String(form.getFieldValue('modelId') || '').trim();
            if (!candidateModels.some((item) => item.id === currentModelId)) {
                form.setFieldValue('modelId', candidateModels[0]?.id || undefined);
            }
        }
    }, [ensureRoundArtifacts, form, models, roundOptions]);

    const onBranchChanged = useCallback((branchId?: string) => {
        void loadBranchCommits(branchId);
    }, [loadBranchCommits]);

    useEffect(() => {
        if (modelSourceKind === 'round_artifact') {
            const fallbackRoundId = String(sourceRoundId || form.getFieldValue('targetRoundId') || '').trim();
            void ensureRoundArtifacts(fallbackRoundId);
        }
    }, [ensureRoundArtifacts, form, modelSourceKind, sourceRoundId]);

    useEffect(() => {
        const current = String(form.getFieldValue('artifactName') || '').trim();
        const values = artifactOptions.map((item) => String(item.value || '').trim()).filter(Boolean);
        if (values.length === 0) {
            if (current !== 'best.pt') {
                form.setFieldValue('artifactName', 'best.pt');
            }
            return;
        }
        if (!values.includes(current)) {
            form.setFieldValue('artifactName', values[0]);
        }
    }, [artifactOptions, form]);

    useEffect(() => {
        const branchId = String(form.getFieldValue('targetBranchId') || '').trim() || branches[0]?.id;
        if (!branchId) return;
        void loadBranchCommits(branchId);
    }, [branches, form, loadBranchCommits]);

    const onCreateTask = useCallback(async () => {
        if (!projectId) return;
        try {
            const values = await form.validateFields();
            const payload: PredictionSetGenerateRequest = {
                pluginId: values.pluginId,
                targetRoundId: values.targetRoundId,
                modelSource: values.modelSourceKind === 'model'
                    ? {
                        kind: 'model',
                        modelId: values.modelId,
                        artifactName: values.artifactName || 'best.pt',
                    }
                    : {
                        kind: 'round_artifact',
                        roundId: values.sourceRoundId || values.targetRoundId,
                        artifactName: values.artifactName || 'best.pt',
                    },
                targetBranchId: values.targetBranchId,
                baseCommitId: values.baseCommitId,
                predictConf: values.predictConf,
                scopeType: 'sample_status',
                scopePayload: {status: values.scopeStatus},
            };
            setSubmitting(true);
            await api.generatePredictionSet(projectId, payload);
            messageApi.success(t('project.predictionTasks.messages.createSuccess'));
            setCreateOpen(false);
            await refresh();
        } catch (error: any) {
            if (error?.errorFields) return;
            messageApi.error(error?.message || t('project.predictionTasks.messages.createFailed'));
        } finally {
            setSubmitting(false);
        }
    }, [api, form, messageApi, projectId, refresh, t]);

    const onApply = useCallback(async (taskId: string) => {
        try {
            const result = await api.applyPredictionSet(taskId, {});
            messageApi.success(t('project.predictionTasks.messages.applySuccess', {count: result.appliedCount}));
            await refresh();
        } catch (error: any) {
            messageApi.error(error?.message || t('project.predictionTasks.messages.applyFailed'));
        }
    }, [api, messageApi, refresh, t]);

    return (
        <div className="p-6 space-y-4">
            {contextHolder}
            <Space className="w-full justify-between">
                <Typography.Title level={4} className="!mb-0">Prediction Tasks</Typography.Title>
                <Space>
                    <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>{t('project.predictionTasks.refresh')}</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={onOpenCreate}>{t('project.predictionTasks.newTask')}</Button>
                </Space>
            </Space>

            <Card>
                <Table<PredictionTaskRead>
                    rowKey="id"
                    loading={loading}
                    dataSource={tasks}
                    pagination={{pageSize: 20}}
                    columns={[
                        {
                            title: t('project.predictionTasks.table.taskId'),
                            dataIndex: 'id',
                            width: 260,
                            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
                        },
                        {
                            title: t('project.predictionTasks.table.status'),
                            dataIndex: 'status',
                            width: 130,
                            render: (value: string) => <Tag color={statusColor[value] || 'default'}>{value}</Tag>,
                        },
                        {
                            title: 'Plugin',
                            dataIndex: 'pluginId',
                            width: 180,
                        },
                        {
                            title: t('project.predictionTasks.table.totalItems'),
                            dataIndex: 'totalItems',
                            width: 100,
                        },
                        {
                            title: t('project.predictionTasks.table.error'),
                            dataIndex: 'lastError',
                            render: (value?: string | null) => value || '-',
                        },
                        {
                            title: t('project.predictionTasks.table.actions'),
                            key: 'actions',
                            width: 220,
                            render: (_, row) => (
                                <Space>
                                    <Button size="small" onClick={() => navigate(`/projects/${projectId}/loops/${row.loopId}`)} disabled={!row.loopId}>
                                        {t('project.predictionTasks.actions.gotoLoop')}
                                    </Button>
                                    <Button
                                        size="small"
                                        type="primary"
                                        disabled={row.status !== 'ready'}
                                        onClick={() => void onApply(row.id)}
                                    >
                                        {t('project.predictionTasks.actions.apply')}
                                    </Button>
                                </Space>
                            ),
                        },
                    ]}
                />
            </Card>

            <Modal
                title={t('project.predictionTasks.modal.title')}
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={() => void onCreateTask()}
                confirmLoading={submitting}
                okText={t('project.predictionTasks.modal.okText')}
            >
                <Form<TaskFormValues> form={form} layout="vertical">
                    <Form.Item label={t('project.predictionTasks.form.plugin')} name="pluginId" rules={[{required: true}]} extra={t('project.predictionTasks.form.pluginExtra')}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            onChange={onPluginChanged}
                            options={pluginOptions.map((id) => ({
                                value: id,
                                label: id,
                            }))}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.targetRound')} name="targetRoundId" rules={[{required: true}]} extra={t('project.predictionTasks.form.targetRoundExtra')}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            onChange={onRoundChanged}
                            options={scopedRoundOptions.map((item) => ({
                                value: item.id,
                                label: `${item.pluginId || '-'} / R${item.roundIndex}A${item.attemptIndex}`,
                            }))}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.modelSource')} name="modelSourceKind" rules={[{required: true}]}>
                        <Select
                            options={[
                                {value: 'round_artifact', label: 'Round Artifact'},
                                {value: 'model', label: 'Registered Model'},
                            ]}
                        />
                    </Form.Item>
                    <Form.Item noStyle shouldUpdate>
                        {({getFieldValue}) => {
                            const kind = getFieldValue('modelSourceKind') as ModelSourceKind;
                            if (kind === 'model') {
                                return (
                                    <Form.Item label={t('project.predictionTasks.form.model')} name="modelId" rules={[{required: true}]}>
                                        <Select
                                            showSearch
                                            optionFilterProp="label"
                                            options={scopedModelOptions.map((item) => ({
                                                value: item.id,
                                                label: `${item.name} (${item.versionTag})`,
                                            }))}
                                        />
                                    </Form.Item>
                                );
                            }
                            return (
                                <Form.Item label={t('project.predictionTasks.form.sourceRound')} name="sourceRoundId" rules={[{required: true}]} extra={t('project.predictionTasks.form.sourceRoundExtra')}>
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        onChange={(value) => {
                                            void ensureRoundArtifacts(value);
                                        }}
                                        options={scopedRoundOptions.map((item) => ({
                                            value: item.id,
                                            label: `${item.pluginId || '-'} / R${item.roundIndex}A${item.attemptIndex}`,
                                        }))}
                                    />
                                </Form.Item>
                            );
                        }}
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.artifactName')} name="artifactName" initialValue="best.pt" rules={[{required: true}]}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={artifactOptions}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.targetBranch')} name="targetBranchId" rules={[{required: true}]}>
                        <Select
                            options={branches.map((item) => ({
                                value: item.id,
                                label: item.name,
                            }))}
                            onChange={onBranchChanged}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.baseCommit')} name="baseCommitId" rules={[{required: true}]}>
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={commitOptions}
                            placeholder={t('project.predictionTasks.form.baseCommitPlaceholder')}
                        />
                    </Form.Item>
                    <Form.Item
                        label={t('project.predictionTasks.form.predictConf')}
                        name="predictConf"
                        tooltip={t('project.predictionTasks.form.predictConfTooltip')}
                        rules={[{required: true}]}
                    >
                        <Slider
                            min={0}
                            max={1}
                            step={0.001}
                            marks={{0: '0', 0.1: '0.1', 0.5: '0.5', 1: '1.0'}}
                            tooltip={{formatter: (value) => (typeof value === 'number' ? value.toFixed(3) : '')}}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.predictionTasks.form.scopeStatus')} name="scopeStatus" rules={[{required: true}]}>
                        <Select
                            options={[
                                {value: 'all', label: t('project.predictionTasks.scope.all')},
                                {value: 'unlabeled', label: t('project.predictionTasks.scope.unlabeled')},
                                {value: 'labeled', label: t('project.predictionTasks.scope.labeled')},
                                {value: 'draft', label: t('project.predictionTasks.scope.draft')},
                            ]}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectPredictionTasks;
