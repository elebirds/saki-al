import React, {useCallback, useEffect, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Divider,
    Dropdown,
    Empty,
    Form,
    Input,
    InputNumber,
    Modal,
    Popconfirm,
    Select,
    Spin,
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
    LoopAnnotationGapsResponse,
    LoopSnapshotRead,
    LoopStageResponse,
    SnapshotInitRequest,
    SnapshotUpdateRequest,
    LoopSummary,
    RuntimeRound,
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

const LOOP_STAGE_COLOR: Record<string, string> = {
    snapshot_required: 'default',
    label_gap_required: 'warning',
    ready_to_start: 'processing',
    running_round: 'processing',
    waiting_round_label: 'warning',
    ready_to_confirm: 'success',
    failed_retryable: 'error',
    completed: 'success',
    stopped: 'default',
    failed: 'error',
};

const PARTITION_LABEL: Record<string, string> = {
    train_seed: 'TRAIN_SEED',
    train_pool: 'TRAIN_POOL',
    val_anchor: 'VAL_ANCHOR',
    val_batch: 'VAL_BATCH',
    test_anchor: 'TEST_ANCHOR',
    test_batch: 'TEST_BATCH',
};

const SNAPSHOT_INIT_DEFAULTS: SnapshotInitRequest = {
    trainSeedRatio: 0.05,
    valRatio: 0.1,
    testRatio: 0.1,
    valPolicy: 'anchor_only',
};

const SNAPSHOT_UPDATE_DEFAULTS: SnapshotUpdateRequest = {
    mode: 'append_all_to_pool',
    batchTestRatio: 0.1,
    batchValRatio: 0.1,
};

const ProjectLoopDetail: React.FC = () => {
    const {projectId, loopId} = useParams<{ projectId: string; loopId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');
    const [loading, setLoading] = useState(true);
    const [controlLoading, setControlLoading] = useState(false);
    const [cleaningRound, setCleaningRound] = useState<number | null>(null);
    const [loop, setLoop] = useState<Loop | null>(null);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [rounds, setRounds] = useState<RuntimeRound[]>([]);
    const [stageInfo, setStageInfo] = useState<LoopStageResponse | null>(null);
    const [snapshotInfo, setSnapshotInfo] = useState<LoopSnapshotRead | null>(null);
    const [gapInfo, setGapInfo] = useState<LoopAnnotationGapsResponse | null>(null);
    const [snapshotInitOpen, setSnapshotInitOpen] = useState(false);
    const [snapshotUpdateOpen, setSnapshotUpdateOpen] = useState(false);
    const [snapshotSubmitting, setSnapshotSubmitting] = useState(false);
    const [initForm] = Form.useForm<SnapshotInitRequest & { sampleIdsText?: string }>();
    const [updateForm] = Form.useForm<SnapshotUpdateRequest & { sampleIdsText?: string }>();
    const updateMode = Form.useWatch('mode', updateForm);

    const refreshLoopData = useCallback(async () => {
        if (!loopId || !projectId) return;
        const [loopRow, summaryRow, roundRows] = await Promise.all([
            api.getLoopById(loopId),
            api.getLoopSummary(loopId),
            api.getLoopRounds(loopId, 100),
        ]);
        setLoop(loopRow);
        setSummary(summaryRow);
        setRounds(roundRows);
        const stageRow = await api.getLoopStage(loopId).catch(() => null);
        setStageInfo(stageRow);
        if (loopRow.mode === 'active_learning') {
            const snapshotRow = await api.getLoopSnapshot(loopId).catch(() => null);
            let gapRow: LoopAnnotationGapsResponse | null = null;
            if (snapshotRow?.activeSnapshotVersionId) {
                gapRow = await api.getLoopAnnotationGaps(loopId).catch(() => null);
            }
            setSnapshotInfo(snapshotRow);
            setGapInfo(gapRow);
        } else {
            setSnapshotInfo(null);
            setGapInfo(null);
        }
    }, [loopId, projectId]);

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

    const executeLoopAction = useCallback(
        async (
            action?: string,
            payload: Record<string, any> = {},
            opts: { force?: boolean; refresh?: boolean } = {},
        ) => {
            if (!loopId) return null;
            setControlLoading(true);
            try {
                const result = await api.actLoop(loopId, {
                    action: action as any,
                    force: Boolean(opts.force),
                    decisionToken: stageInfo?.decisionToken || undefined,
                    payload,
                });
                setStageInfo({
                    loopId: result.loopId,
                    stage: result.stage,
                    stageMeta: result.stageMeta || {},
                    primaryAction: result.primaryAction || null,
                    actions: result.actions || [],
                    decisionToken: result.decisionToken || '',
                    blockingReasons: result.blockingReasons || [],
                });
                const actionKeys = new Set((result.actions || []).map((item) => item.key));
                if (actionKeys.has('snapshot_init') && loop?.mode === 'active_learning') {
                    initForm.resetFields();
                    initForm.setFieldsValue(SNAPSHOT_INIT_DEFAULTS);
                    setSnapshotInitOpen(true);
                }
                if (loop?.mode === 'active_learning' && (actionKeys.has('view_annotation_gaps') || actionKeys.has('annotate'))) {
                    const gaps = await api.getLoopAnnotationGaps(loopId).catch(() => null);
                    setGapInfo(gaps);
                }
                if (result.executedAction) {
                    message.success(result.message || `已执行 ${result.executedAction}`);
                } else {
                    message.info(result.message || `当前阶段无需执行：${result.stage}`);
                }
                if (opts.refresh !== false) {
                    await refreshLoopData();
                }
                return result;
            } catch (error: any) {
                message.error(error?.message || 'Loop 动作执行失败');
                return null;
            } finally {
                setControlLoading(false);
            }
        },
        [loopId, stageInfo?.decisionToken, loop?.mode, refreshLoopData],
    );

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

    const parseSampleIds = (raw?: string): string[] | undefined => {
        const text = String(raw || '').trim();
        if (!text) return undefined;
        const rows = text
            .split(/[\n,]+/g)
            .map((item) => item.trim())
            .filter((item) => !!item);
        return rows.length > 0 ? rows : undefined;
    };

    const handleInitSnapshot = async () => {
        if (!loopId) return;
        try {
            const values = await initForm.validateFields();
            setSnapshotSubmitting(true);
            const payload: SnapshotInitRequest = {
                seed: values.seed,
                trainSeedRatio: values.trainSeedRatio,
                valRatio: values.valRatio,
                testRatio: values.testRatio,
                valPolicy: values.valPolicy,
                sampleIds: parseSampleIds((values as any).sampleIdsText),
            };
            await executeLoopAction('snapshot_init', payload, {refresh: true});
            message.success('Snapshot 初始化成功');
            setSnapshotInitOpen(false);
            initForm.resetFields();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || 'Snapshot 初始化失败');
        } finally {
            setSnapshotSubmitting(false);
        }
    };

    const handleUpdateSnapshot = async () => {
        if (!loopId) return;
        try {
            const values = await updateForm.validateFields();
            setSnapshotSubmitting(true);
            const payload: SnapshotUpdateRequest = {
                mode: values.mode,
                seed: values.seed,
                batchTestRatio: values.batchTestRatio,
                batchValRatio: values.batchValRatio,
                valPolicy: values.valPolicy,
                sampleIds: parseSampleIds((values as any).sampleIdsText),
            };
            await executeLoopAction('snapshot_update', payload, {refresh: true});
            message.success('Snapshot 更新成功');
            setSnapshotUpdateOpen(false);
            updateForm.resetFields();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || 'Snapshot 更新失败');
        } finally {
            setSnapshotSubmitting(false);
        }
    };

    const openSnapshotInitModal = () => {
        initForm.resetFields();
        initForm.setFieldsValue(SNAPSHOT_INIT_DEFAULTS);
        setSnapshotInitOpen(true);
    };

    const openSnapshotUpdateModal = () => {
        updateForm.resetFields();
        updateForm.setFieldsValue(SNAPSHOT_UPDATE_DEFAULTS);
        setSnapshotUpdateOpen(true);
    };

    const handleContinue = async () => {
        await executeLoopAction(primaryAction?.key || undefined);
    };

    const primaryAction = stageInfo?.primaryAction || null;
    const continueLabel = primaryAction ? `Continue · ${primaryAction.label}` : 'Continue';
    const continueDisabled = !primaryAction || !primaryAction.runnable;
    const advancedActionItems = (stageInfo?.actions || [])
        .filter((item) => item.key !== primaryAction?.key)
        .map((item) => ({
            key: item.key,
            label: item.label,
            disabled: !item.runnable,
            onClick: () => {
                if (item.key === 'snapshot_init') {
                    openSnapshotInitModal();
                    return;
                }
                if (item.key === 'snapshot_update') {
                    openSnapshotUpdateModal();
                    return;
                }
                void executeLoopAction(item.key);
            },
            danger: item.key === 'stop',
        }));

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
                        <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/config`)}>
                            配置
                        </Button>
                        <Button onClick={() => navigate('/runtime/executors')}>执行器状态</Button>
                        <Button
                            type="primary"
                            loading={controlLoading}
                            onClick={handleContinue}
                            disabled={continueDisabled}
                        >
                            {continueLabel}
                        </Button>
                        <Dropdown
                            menu={{
                                items: advancedActionItems.map((item) => ({
                                    key: item.key,
                                    label: item.label,
                                    disabled: item.disabled,
                                    danger: item.danger,
                                })),
                                onClick: ({key}) => {
                                    const match = advancedActionItems.find((item) => item.key === key);
                                    if (match && !match.disabled) {
                                        match.onClick();
                                    }
                                },
                            }}
                            trigger={['click']}
                        >
                            <Button>高级操作</Button>
                        </Dropdown>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="Loop 摘要">
                <Descriptions size="small" column={4}>
                    <Descriptions.Item label="模式">{loop.mode}</Descriptions.Item>
                    <Descriptions.Item label="Stage">
                        {loop.stage ? <Tag color={LOOP_STAGE_COLOR[loop.stage] || 'default'}>{loop.stage}</Tag> : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="Rounds 总数">{summary?.roundsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Attempts 总数">{summary?.attemptsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Rounds 成功">{summary?.roundsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 总数">{summary?.stepsTotal ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="Steps 成功">{summary?.stepsSucceeded ?? 0}</Descriptions.Item>
                    <Descriptions.Item label="最新 map50">{Number(summary?.metricsLatest?.map50 || 0).toFixed(4)}</Descriptions.Item>
                </Descriptions>
            </Card>

            {loop.mode === 'active_learning' ? (
                <Card className="!border-github-border !bg-github-panel" title="AL Stage 面板">
                    {stageInfo ? (
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <Tag color={LOOP_STAGE_COLOR[stageInfo.stage] || 'default'}>{stageInfo.stage}</Tag>
                                {stageInfo.primaryAction ? (
                                    <Tag color="green">primary: {stageInfo.primaryAction.key}</Tag>
                                ) : null}
                                {(stageInfo.actions || []).map((action) => (
                                    <Tag key={action.key} color={action.runnable ? 'blue' : 'default'}>
                                        {action.key}
                                    </Tag>
                                ))}
                            </div>
                            <Text type="secondary">stageMeta: {JSON.stringify(stageInfo.stageMeta || {})}</Text>
                        </div>
                    ) : (
                        <Empty description="暂无 stage 信息"/>
                    )}
                </Card>
            ) : null}

            {loop.mode === 'active_learning' ? (
                <Card className="!border-github-border !bg-github-panel" title="Snapshot 信息">
                    {snapshotInfo?.active ? (
                        <div className="flex flex-col gap-3">
                            <Descriptions size="small" column={4}>
                                <Descriptions.Item label="Active Version">{snapshotInfo.active.versionIndex}</Descriptions.Item>
                                <Descriptions.Item label="Update Mode">{snapshotInfo.active.updateMode}</Descriptions.Item>
                                <Descriptions.Item label="Val Policy">{snapshotInfo.active.valPolicy}</Descriptions.Item>
                                <Descriptions.Item label="样本总数">{snapshotInfo.active.sampleCount}</Descriptions.Item>
                            </Descriptions>
                            <div className="flex flex-wrap items-center gap-2">
                                {Object.entries(snapshotInfo.partitionCounts || {}).map(([key, value]) => (
                                    <Tag key={key}>{PARTITION_LABEL[key] || key}: {value}</Tag>
                                ))}
                            </div>
                            <Divider className="!my-2"/>
                            <Text strong>历史版本（最近 5 个）</Text>
                            <Table
                                size="small"
                                rowKey={(row) => row.id}
                                dataSource={(snapshotInfo.history || []).slice(-5).reverse()}
                                pagination={false}
                                columns={[
                                    {title: 'Version', dataIndex: 'versionIndex', width: 90},
                                    {title: 'Mode', dataIndex: 'updateMode', width: 180},
                                    {title: 'Val', dataIndex: 'valPolicy', width: 170},
                                    {title: 'Samples', dataIndex: 'sampleCount', width: 110},
                                    {
                                        title: 'Manifest',
                                        dataIndex: 'manifestHash',
                                        render: (value: string) => String(value || '').slice(0, 12),
                                    },
                                ]}
                            />
                        </div>
                    ) : (
                        <Alert
                            type="info"
                            showIcon
                            message="当前尚未初始化 Snapshot"
                            description="请先执行“初始化 Snapshot”，再开始主动学习循环。"
                        />
                    )}
                </Card>
            ) : null}

            {loop.mode === 'active_learning' ? (
                <Card className="!border-github-border !bg-github-panel" title="Annotation Gaps">
                    {gapInfo ? (
                        <Table
                            size="small"
                            rowKey={(_row, idx) => idx ?? 0}
                            dataSource={gapInfo.buckets || []}
                            pagination={false}
                            columns={[
                                {
                                    title: 'Partition',
                                    dataIndex: 'partition',
                                    width: 180,
                                    render: (value: string) => PARTITION_LABEL[value] || value,
                                },
                                {title: 'Total', dataIndex: 'total', width: 110},
                                {title: 'Missing', dataIndex: 'missingCount', width: 120},
                                {
                                    title: '缺失样本（前 5）',
                                    render: (_value: unknown, row: { partition?: string; sampleIds?: string[] }) =>
                                        (row.sampleIds || []).slice(0, 5).join(', ') || '-',
                                },
                            ]}
                        />
                    ) : (
                        <Empty description="暂无 gap 信息"/>
                    )}
                </Card>
            ) : null}

            <Card className="!border-github-border !bg-github-panel" title="当前 Loop 的 Rounds">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={rounds}
                    pagination={{pageSize: 8}}
                    columns={[
                        {
                            title: 'Round/Attempt',
                            width: 140,
                            render: (_v: unknown, row: RuntimeRound) => `#${row.roundIndex} · A${row.attemptIndex || 1}`,
                        },
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

            <Modal
                title="初始化 Snapshot"
                open={snapshotInitOpen}
                onCancel={() => setSnapshotInitOpen(false)}
                onOk={handleInitSnapshot}
                okButtonProps={{loading: snapshotSubmitting}}
                destroyOnClose
            >
                <Form form={initForm} layout="vertical">
                    <Form.Item name="seed" label="Seed">
                        <Input placeholder="可选，不填则按规则生成"/>
                    </Form.Item>
                    <Form.Item name="trainSeedRatio" label="Train Seed Ratio">
                        <InputNumber className="w-full" min={0} max={1} step={0.01}/>
                    </Form.Item>
                    <Form.Item name="valRatio" label="Val Ratio">
                        <InputNumber className="w-full" min={0} max={1} step={0.01}/>
                    </Form.Item>
                    <Form.Item name="testRatio" label="Test Ratio">
                        <InputNumber className="w-full" min={0} max={1} step={0.01}/>
                    </Form.Item>
                    <Form.Item name="valPolicy" label="Val Policy">
                        <Select
                            allowClear
                            options={[
                                {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                            ]}
                        />
                    </Form.Item>
                    <Form.Item name="sampleIdsText" label="Sample IDs（可选）">
                        <Input.TextArea rows={4} placeholder="按逗号或换行分隔，不填则使用项目全集"/>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title="更新 Snapshot"
                open={snapshotUpdateOpen}
                onCancel={() => setSnapshotUpdateOpen(false)}
                onOk={handleUpdateSnapshot}
                okButtonProps={{loading: snapshotSubmitting}}
                destroyOnClose
            >
                <Form form={updateForm} layout="vertical">
                    <Form.Item name="mode" label="Update Mode">
                        <Select
                            allowClear
                            options={[
                                {label: 'APPEND_ALL_TO_POOL', value: 'append_all_to_pool'},
                                {label: 'APPEND_SPLIT', value: 'append_split'},
                            ]}
                        />
                    </Form.Item>
                    <Form.Item name="seed" label="Seed">
                        <Input placeholder="可选，不填则按规则生成"/>
                    </Form.Item>
                    <Form.Item name="valPolicy" label="Val Policy（可选覆盖）">
                        <Select
                            allowClear
                            options={[
                                {label: 'ANCHOR_ONLY', value: 'anchor_only'},
                                {label: 'EXPAND_WITH_BATCH_VAL', value: 'expand_with_batch_val'},
                            ]}
                        />
                    </Form.Item>
                    {updateMode === 'append_split' ? (
                        <>
                            <Form.Item name="batchTestRatio" label="Batch Test Ratio">
                                <InputNumber className="w-full" min={0} max={1} step={0.01}/>
                            </Form.Item>
                            <Form.Item name="batchValRatio" label="Batch Val Ratio">
                                <InputNumber className="w-full" min={0} max={1} step={0.01}/>
                            </Form.Item>
                        </>
                    ) : null}
                    <Form.Item name="sampleIdsText" label="Sample IDs（可选）">
                        <Input.TextArea rows={4} placeholder="按逗号或换行分隔，不填则自动取新增样本"/>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default ProjectLoopDetail;
