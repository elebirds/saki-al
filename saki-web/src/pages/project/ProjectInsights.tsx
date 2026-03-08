import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {Card, Empty, Select, Spin, Statistic, Table, Tag, Typography} from 'antd';
import {useTranslation} from 'react-i18next';
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
import {
    collectMetricKeys,
    formatMetricValue,
    getMetricBySource,
    getSummaryMetricsBySource,
    pickPreviewMetric,
} from './loops/runtimeMetricView';

const {Text} = Typography;

const LOOP_LIFECYCLE_COLOR: Record<string, string> = {
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

const compareRoundAttemptAsc = (left: RuntimeRound, right: RuntimeRound): number => {
    const leftRound = Number(left.roundIndex || 0);
    const rightRound = Number(right.roundIndex || 0);
    if (leftRound !== rightRound) return leftRound - rightRound;

    const leftAttempt = Number(left.attemptIndex || 1);
    const rightAttempt = Number(right.attemptIndex || 1);
    if (leftAttempt !== rightAttempt) return leftAttempt - rightAttempt;

    return String(left.id).localeCompare(String(right.id));
};

const ProjectInsights: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const [loading, setLoading] = useState(true);
    const [loops, setLoops] = useState<Loop[]>([]);
    const [selectedLoopId, setSelectedLoopId] = useState<string>();
    const [rounds, setRounds] = useState<RuntimeRound[]>([]);
    const [summary, setSummary] = useState<LoopSummary | null>(null);
    const [models, setModels] = useState<ProjectModel[]>([]);
    const [metricSource, setMetricSource] = useState<'eval' | 'train'>('eval');
    const [selectedMetricKey, setSelectedMetricKey] = useState<string>('map50');

    const selectedLoop = useMemo(
        () => loops.find((item) => item.id === selectedLoopId),
        [loops, selectedLoopId],
    );

    const loadLoopDetail = useCallback(async (loopId: string) => {
        const [roundRows, summaryRow] = await Promise.all([
            api.getLoopRounds(loopId, 500),
            api.getLoopSummary(loopId),
        ]);
        const sorted = [...roundRows].sort(compareRoundAttemptAsc);
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

    const metricKeyOptions = useMemo(
        () => collectMetricKeys(rounds, metricSource),
        [rounds, metricSource],
    );

    useEffect(() => {
        if (metricKeyOptions.length === 0) {
            setSelectedMetricKey('map50');
            return;
        }
        if (metricKeyOptions.includes(selectedMetricKey)) return;
        setSelectedMetricKey(metricKeyOptions[0]);
    }, [metricKeyOptions, selectedMetricKey]);

    const chartData = useMemo(() => {
        return rounds.map((item) => {
            const sourceMetrics = getMetricBySource(item, metricSource);
            const metricRaw = sourceMetrics[selectedMetricKey];
            const metricValue = Number(metricRaw);
            const round = Number(item.roundIndex || 0);
            const attempt = Number(item.attemptIndex || 1);
            return {
                round,
                attempt,
                roundAttempt: `R${round}·A${attempt}`,
                metricValue: Number.isFinite(metricValue) ? metricValue : null,
                succeededSteps: Number(item.stepCounts?.succeeded || 0),
            };
        });
    }, [rounds, metricSource, selectedMetricKey]);

    const productionModels = useMemo(() => models.filter((item) => item.status === 'production'), [models]);
    const candidateModels = useMemo(() => models.filter((item) => item.status === 'candidate'), [models]);
    const latestMetricPreview = useMemo(
        () => pickPreviewMetric(getSummaryMetricsBySource(summary, metricSource)),
        [summary, metricSource],
    );

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
                <Empty description={t('project.insights.emptyLoops')}/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex flex-wrap items-center gap-3">
                    <Text type="secondary">{t('project.insights.loopDimension')}</Text>
                    <Select
                        className="min-w-[320px]"
                        value={selectedLoopId}
                        onChange={async (value) => {
                            setSelectedLoopId(value);
                            await loadLoopDetail(value);
                        }}
                        options={loops.map((item) => ({
                            label: `${item.name} (${item.lifecycle} / ${item.phase})`,
                            value: item.id,
                        }))}
                    />
                    {selectedLoop ? (
                        <Tag color={LOOP_LIFECYCLE_COLOR[selectedLoop.lifecycle] || 'default'}>{selectedLoop.lifecycle}</Tag>
                    ) : null}
                    <Select
                        className="min-w-[180px]"
                        value={metricSource}
                        onChange={(value) => setMetricSource(value as 'eval' | 'train')}
                        options={[
                            {label: t('project.insights.metricSource.eval'), value: 'eval'},
                            {label: t('project.insights.metricSource.train'), value: 'train'},
                        ]}
                    />
                    <Select
                        className="min-w-[180px]"
                        value={selectedMetricKey}
                        onChange={(value) => setSelectedMetricKey(value)}
                        options={(metricKeyOptions.length > 0 ? metricKeyOptions : [selectedMetricKey]).map((key) => ({
                            label: key,
                            value: key,
                        }))}
                    />
                </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title={t('project.insights.stats.roundsTotal')} value={summary?.roundsTotal ?? rounds.length}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title={t('project.insights.stats.roundsSucceeded')} value={summary?.roundsSucceeded ?? 0}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title={t('project.insights.stats.stepsTotal')} value={summary?.stepsTotal ?? 0}/>
                    </Card>
                </div>
                <div>
                    <Card className="!border-github-border !bg-github-panel">
                        <Statistic title={t('project.insights.stats.stepsSucceeded')} value={summary?.stepsSucceeded ?? 0}/>
                    </Card>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="min-w-0 lg:col-span-2">
                    <Card className="!border-github-border !bg-github-panel" title={t('project.insights.roundMetricsTrend')}>
                        {chartData.length === 0 ? (
                            <Empty description={t('project.insights.emptyRoundMetrics')}/>
                        ) : (
                            <div className="h-[340px]">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={chartData}>
                                        <CartesianGrid strokeDasharray="3 3"/>
                                        <XAxis dataKey="roundAttempt"/>
                                        <YAxis yAxisId="left" domain={[0, 1]}/>
                                        <YAxis yAxisId="right" orientation="right"/>
                                        <Tooltip/>
                                        <Line
                                            yAxisId="left"
                                            type="monotone"
                                            dataKey="metricValue"
                                            name={selectedMetricKey}
                                            stroke="#1677ff"
                                            strokeWidth={2}
                                            dot={false}
                                            connectNulls={false}
                                        />
                                        <Line yAxisId="right" type="monotone" dataKey="succeededSteps" stroke="#52c41a" strokeWidth={2} dot={false}/>
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        )}
                    </Card>
                </div>
                <div className="min-w-0">
                    <Card className="!border-github-border !bg-github-panel" title={t('project.insights.modelStatus')}>
                        <div className="flex flex-col gap-4">
                            <Statistic title={t('project.insights.stats.totalModels')} value={models.length}/>
                            <Statistic title={t('project.insights.stats.candidateModels')} value={candidateModels.length}/>
                            <Statistic title={t('project.insights.stats.productionModels')} value={productionModels.length}/>
                            <Text type="secondary">
                                {t('project.insights.latestMetric', {
                                    source: metricSource === 'eval' ? t('project.insights.metricSource.eval') : t('project.insights.metricSource.train'),
                                    value: latestMetricPreview,
                                })}
                            </Text>
                        </div>
                    </Card>
                </div>
            </div>

            <Card className="!border-github-border !bg-github-panel" title={t('project.insights.roundDetails')}>
                <Table
                    size="small"
                    rowKey={(item) => item.id}
                    dataSource={rounds}
                    pagination={{pageSize: 10}}
                    columns={[
                        {title: 'Round', dataIndex: 'roundIndex', width: 90},
                        {title: 'Attempt', dataIndex: 'attemptIndex', width: 90},
                        {
                            title: t('project.insights.table.status'),
                            dataIndex: 'state',
                            width: 140,
                            render: (value: string) => <Tag color={ROUND_STATE_COLOR[value] || 'default'}>{value}</Tag>,
                        },
                        {title: t('project.insights.table.strategy'), dataIndex: 'queryStrategy', width: 180},
                        {
                            title: `Train(${selectedMetricKey})`,
                            width: 140,
                            render: (_: unknown, row: RuntimeRound) => formatMetricValue(getMetricBySource(row, 'train')[selectedMetricKey]),
                        },
                        {
                            title: `Eval(${selectedMetricKey})`,
                            width: 140,
                            render: (_: unknown, row: RuntimeRound) => formatMetricValue(getMetricBySource(row, 'eval')[selectedMetricKey]),
                        },
                        {
                            title: `Final(${selectedMetricKey})`,
                            width: 140,
                            render: (_: unknown, row: RuntimeRound) => formatMetricValue(getMetricBySource(row, 'final')[selectedMetricKey]),
                        },
                        {title: 'stepCounts', render: (_: unknown, row: RuntimeRound) => JSON.stringify(row.stepCounts || {})},
                    ]}
                />
            </Card>
        </div>
    );
};

export default ProjectInsights;
