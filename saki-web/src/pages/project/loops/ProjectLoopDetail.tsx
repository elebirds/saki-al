import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Popconfirm,
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
    LoopSummary,
    Project,
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
                        <Button onClick={() => navigate(`/projects/${projectId}/loops/${loopId}/config`)}>
                            配置
                        </Button>
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
