import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {Alert, Button, Card, Empty, Popconfirm, Spin, Tag, Typography, message} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {api} from '../../../services/api';
import {Loop, LoopSummary, ProjectBranch, RuntimePluginCatalogItem} from '../../../types';
import {getSummaryMetricsBySource, pickPreviewMetric} from './runtimeMetricView';
import {isLoopDeletable} from './loopLifecycle';

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

const ProjectLoopOverview: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');

    const [loading, setLoading] = useState(true);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [plugins, setPlugins] = useState<RuntimePluginCatalogItem[]>([]);
    const [summaryMap, setSummaryMap] = useState<Record<string, LoopSummary>>({});
    const [deletingLoopId, setDeletingLoopId] = useState<string>('');

    const availableBranchCount = useMemo(() => {
        const bound = new Set(loops.map((item) => item.branchId));
        return branches.filter((branch) => !bound.has(branch.id)).length;
    }, [loops, branches]);

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
    }, [projectId, canManageLoops, t]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadData();
    }, [canManageLoops, loadData]);

    const handleDeleteLoop = useCallback(async (loop: Loop) => {
        if (!projectId) return;
        if (!isLoopDeletable(loop.lifecycle)) {
            message.warning(`当前生命周期 ${loop.lifecycle} 不允许删除`);
            return;
        }
        setDeletingLoopId(loop.id);
        try {
            await api.deleteLoop(loop.id);
            message.success('Loop 已删除');
            await loadData();
        } catch (error: any) {
            message.error(error?.message || '删除 Loop 失败');
        } finally {
            setDeletingLoopId('');
        }
    }, [projectId, loadData]);

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
                        <Button onClick={loadData}>{t('project.loopOverview.refresh')}</Button>
                        <Button
                            type="primary"
                            onClick={() => navigate(`/projects/${projectId}/loops/create`)}
                            disabled={plugins.length === 0 || availableBranchCount === 0}
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
                {availableBranchCount === 0 ? (
                    <Alert
                        className="!mt-4"
                        type="warning"
                        showIcon
                        message={t('project.loopOverview.branchNoAvailable')}
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
                                        <Popconfirm
                                            key="delete"
                                            title="删除当前 Loop？"
                                            description="该操作不可恢复，会清理该 Loop 的运行时派生数据。"
                                            okText="确认删除"
                                            cancelText="取消"
                                            okButtonProps={{
                                                danger: true,
                                                loading: deletingLoopId === loop.id,
                                            }}
                                            onConfirm={() => void handleDeleteLoop(loop)}
                                            disabled={!isLoopDeletable(loop.lifecycle) || deletingLoopId === loop.id}
                                        >
                                            <Button
                                                type="link"
                                                danger
                                                disabled={!isLoopDeletable(loop.lifecycle)}
                                                loading={deletingLoopId === loop.id}
                                            >
                                                删除
                                            </Button>
                                        </Popconfirm>,
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
        </div>
    );
};

export default ProjectLoopOverview;
