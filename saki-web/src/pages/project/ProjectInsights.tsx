import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {Card, Empty, Select, Spin, Statistic, Table, Tag, Typography} from 'antd';
import {useParams} from 'react-router-dom';
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';

import {api} from '../../services/api';
import {Loop, LoopSummary, ProjectModel, RuntimeRound} from '../../types';

const {Text} = Typography;

const LOOP_STATE_COLOR: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    stopped: 'default',
    completed: 'success',
    failed: 'error',
};

const ROUND_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    completed: 'success',
    failed: 'error',
    cancelled: 'warning',
};

const ProjectInsights: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>();
    const [loading, setLoading] = useState(true);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [selectedLoopId, setSelectedLoopId] = useState<string>();
    const [rounds, setRounds] = useState<RuntimeRound[]>([]);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [models, setModels] = useState<ProjectModel[]>([]);

    const selectedLoop = useMemo(
        () => loops.find((item) => item.id === selectedLoopId),
        [loops, selectedLoopId],
    );

    const loadLoopDetail = useCallback(async (loopId: string) => {
        const [roundRows, summaryRow] = await Promise.all([
            api.getLoopRounds(loopId, 500),
            api.getLoopSummary(loopId),
        ]);
        const sorted = [...roundRows].sort((a, b) => a.roundIndex - b.roundIndex);
        setRounds(sorted);
        setSummary(summaryRow);
    }, []);

    const loadAll = useCallback(async () => {
        if (!projectId) return;
        setLoading(true);
        try {
            const [loopRows, modelRows] = await Promise.all([
                api.getProjectLoops(projectId),
                api.getProjectModels(projectId, 300),
            ]);
            setLoops(loopRows);
            setModels(modelRows);
            const nextLoopId = selectedLoopId && loopRows.some((item) => item.id === selectedLoopId)
                ? selectedLoopId
                : loopRows[0]?.id;
            setSelectedLoopId(nextLoopId);
            if (nextLoopId) {
                await loadLoopDetail(nextLoopId);
            } else {
                setRounds([]);
                setSummary(null);
            }
        } finally {
            setLoading(false);
        }
    }, [projectId, selectedLoopId, loadLoopDetail]);

    useEffect(() => {
        void loadAll();
    }, [loadAll]);

    const chartData = useMemo(() => {
        return rounds.map((item) => ({
            round: item.roundIndex,
            map50: Number(item.finalMetrics?.map50 || 0),
            recall: Number(item.finalMetrics?.recall || 0),
            succeededSteps: Number(item.stepCounts?.succeeded || 0),
        }));
    }, [rounds]);

    const productionModels = useMemo(() => models.filter((item) => item.status === 'production'), [models]);
    const candidateModels = useMemo(() => models.filter((item) => item.status === 'candidate'), [models]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!selectedLoop && loops.length === 0) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="暂无 Loop 数据，先到 Loops 页面创建并运行闭环"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex flex-wrap items-center gap-3">
                    <Text type="secondary">Loop 维度</Text>
                    <Select
                        className="min-w-[320px]"
                        value={selectedLoopId}
                        onChange={async (value) => {
                            setSelectedLoopId(value);
                            await loadLoopDetail(value);
                        }}
                        options={loops.map((item) => ({
                            label: `${item.name} (${item.state} / ${item.phase})`,
                            value: item.id,
                        }))}
                    />
                    {selectedLoop ? (
                        <Tag color={LOOP_STATE_COLOR[selectedLoop.state] || 'default'}>{selectedLoop.state}</Tag>
                    ) : null}
                </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title="Rounds 总数" value={summary?.roundsTotal ?? rounds.length}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title="Rounds 成功" value={summary?.roundsSucceeded ?? 0}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title="Steps 总数" value={summary?.stepsTotal ?? 0}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title="Steps 成功" value={summary?.stepsSucceeded ?? 0}/>
                    </Card>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="min-w-0 lg:col-span-2">
                    <Card className="!border-github-border !bg-github-panel" title="Round 指标走势">
                        {chartData.length === 0 ? (
                            <Empty description="暂无 Round 指标"/>
                        ) : (
                            <div className="h-[340px]">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={chartData}>
                                        <CartesianGrid strokeDasharray="3 3"/>
                                        <XAxis dataKey="round"/>
                                        <YAxis yAxisId="left" domain={[0, 1]}/>
                                        <YAxis yAxisId="right" orientation="right"/>
                                        <Tooltip/>
                                        <Line yAxisId="left" type="monotone" dataKey="map50" stroke="#1677ff" strokeWidth={2} dot={false}/>
                                        <Line yAxisId="left" type="monotone" dataKey="recall" stroke="#13c2c2" strokeWidth={2} dot={false}/>
                                        <Line yAxisId="right" type="monotone" dataKey="succeededSteps" stroke="#52c41a" strokeWidth={2} dot={false}/>
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        )}
                    </Card>
                </div>
                <div className="min-w-0">
                    <Card className="!border-github-border !bg-github-panel" title="模型状态">
                        <div className="flex flex-col gap-4">
                            <Statistic title="总模型数" value={models.length}/>
                            <Statistic title="候选模型" value={candidateModels.length}/>
                            <Statistic title="生产模型" value={productionModels.length}/>
                            <Text type="secondary">最新 mAP50: {Number(summary?.metricsLatest?.map50 || 0).toFixed(4)}</Text>
                        </div>
                    </Card>
                </div>
            </div>

            <Card className="!border-github-border !bg-github-panel" title="Round 明细">
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={rounds}
                    pagination={{pageSize: 10}}
                    columns={[
                        {title: 'Round', dataIndex: 'roundIndex', width: 90},
                        {
                            title: '状态',
                            dataIndex: 'state',
                            width: 140,
                            render: (value: string) => <Tag color={ROUND_STATE_COLOR[value] || 'default'}>{value}</Tag>,
                        },
                        {title: '策略', dataIndex: 'queryStrategy', width: 180},
                        {title: 'mAP50', render: (_: unknown, row: RuntimeRound) => Number(row.finalMetrics?.map50 || 0).toFixed(4), width: 100},
                        {title: 'recall', render: (_: unknown, row: RuntimeRound) => Number(row.finalMetrics?.recall || 0).toFixed(4), width: 100},
                        {title: 'stepCounts', render: (_: unknown, row: RuntimeRound) => JSON.stringify(row.stepCounts || {})},
                    ]}
                />
            </Card>
        </div>
    );
};

export default ProjectInsights;
