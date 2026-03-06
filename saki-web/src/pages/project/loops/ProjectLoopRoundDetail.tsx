import React, {useEffect, useMemo, useState} from 'react';
import {App, Alert, Card, Empty, Spin} from 'antd';
import {useNavigate, useParams} from 'react-router-dom';

import {useResourcePermission} from '../../../hooks';
import {useAuthStore} from '../../../store/authStore';
import RoundConsolePanel from './components/RoundConsolePanel';
import {RuntimeStep} from '../../../types';
import {
    normalizeFinalMetricSource,
    orderMetricEntries,
} from './runtimeMetricView';
import ArtifactTableCard from './roundDetail/ArtifactTableCard';
import {ARTIFACT_CLASS_LABEL, STAGE_LABEL} from './roundDetail/constants';
import MetricsOverviewCard from './roundDetail/MetricsOverviewCard';
import RoundHeaderTimelineCard from './roundDetail/RoundHeaderTimelineCard';
import RoundOverviewDrawer from './roundDetail/RoundOverviewDrawer';
import StepDetailDrawer from './roundDetail/StepDetailDrawer';
import TopKCandidatesCard from './roundDetail/TopKCandidatesCard';
import TrainCurveCard from './roundDetail/TrainCurveCard';
import {useRoundArtifactsAndCandidates} from './roundDetail/useRoundArtifactsAndCandidates';
import {useRoundCoreData} from './roundDetail/useRoundCoreData';
import {useRoundEventStream} from './roundDetail/useRoundEventStream';
import {ConsoleStageFilter, RoundArtifactTableRow, RoundStageKey} from './roundDetail/types';
import {computeDurationMs, formatDuration} from './runtimeTime';
import {
    buildArtifactKey,
    buildStageSnapshots,
    isLossMetricName,
    isTerminalStepState,
    mapStepTypeToStage,
    pickTimelineCurrentStep,
    resolveModeStageOrder,
} from './roundDetail/transforms';

const ProjectLoopRoundDetail: React.FC = () => {
    const {projectId, loopId, roundId} = useParams<{ projectId: string; loopId: string; roundId: string }>();
    const navigate = useNavigate();
    const {message: messageApi} = App.useApp();
    const token = useAuthStore((state) => state.token);
    const {can: canProject} = useResourcePermission('project', projectId);
    const canManageLoops = canProject('loop:manage:assigned');

    const {
        loading,
        refreshing,
        retrying,
        round,
        steps,
        setSteps,
        loadRoundData,
        scheduleRoundMetaRefresh,
        handleRetryRound,
    } = useRoundCoreData({
        canManageLoops,
        roundId,
        loopId,
        messageApi,
    });

    const [nowMs, setNowMs] = useState<number>(Date.now());
    const [roundOverviewOpen, setRoundOverviewOpen] = useState(false);
    const [stepDrawerOpen, setStepDrawerOpen] = useState(false);
    const [stepDrawerStepId, setStepDrawerStepId] = useState('');
    const [consoleStage, setConsoleStage] = useState<ConsoleStageFilter>('all');

    const sortedSteps = useMemo(
        () => [...steps].sort((left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0)),
        [steps],
    );

    const currentTimelineStep = useMemo(() => pickTimelineCurrentStep(sortedSteps), [sortedSteps]);
    const currentTimelineIndex = useMemo(
        () => sortedSteps.findIndex((item) => item.id === currentTimelineStep?.id),
        [sortedSteps, currentTimelineStep?.id],
    );

    const stageSnapshots = useMemo(
        () => buildStageSnapshots(sortedSteps, nowMs),
        [sortedSteps, nowMs],
    );

    const trainStep = stageSnapshots.train.representativeStep;
    const evalStep = stageSnapshots.eval.representativeStep;
    const scoreStep = stageSnapshots.score.representativeStep;
    const selectStep = stageSnapshots.select.representativeStep;

    const {
        trainMetricPoints,
        setTrainMetricPoints,
        topkCandidates,
        topkSource,
        roundArtifacts,
        setRoundArtifacts,
        artifactUrls,
        ensureArtifactUrls,
    } = useRoundArtifactsAndCandidates({
        canManageLoops,
        round,
        trainStep,
        selectStep,
        scoreStep,
    });

    const consoleStageOptions = useMemo(() => {
        if (!round) return [];
        const ordered = resolveModeStageOrder(round.mode);
        const stageOptions = ordered
            .filter((key) => Boolean(stageSnapshots[key].representativeStep))
            .map((key) => ({
                label: STAGE_LABEL[key],
                value: key,
            }));
        return [{label: '全部阶段', value: 'all' as const}, ...stageOptions];
    }, [round?.mode, stageSnapshots]);

    const activeConsoleStages = useMemo(
        (): RoundStageKey[] => (consoleStage === 'all' ? [] : [consoleStage]),
        [consoleStage],
    );

    const {events, wsConnected, clearEventsBuffer} = useRoundEventStream({
        canManageLoops,
        roundId: round?.id,
        token,
        steps,
        activeConsoleStages,
        scheduleRoundMetaRefresh,
        ensureArtifactUrls,
        setSteps,
        setTrainMetricPoints,
        setRoundArtifacts,
    });

    useEffect(() => {
        const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);

    useEffect(() => {
        if (!round) return;
        setConsoleStage((prev) => {
            if (prev === 'all') return 'all';
            if (prev && stageSnapshots[prev].representativeStep) return prev;
            return 'all';
        });
    }, [round?.id, round?.mode, stageSnapshots, currentTimelineStep]);

    const consoleStep = useMemo(() => {
        if (consoleStage === 'all') return currentTimelineStep || null;
        const stageStep = stageSnapshots[consoleStage]?.representativeStep;
        return stageStep || currentTimelineStep || null;
    }, [consoleStage, stageSnapshots, currentTimelineStep]);

    const consoleTargetSteps = useMemo(() => {
        if (consoleStage === 'all') return sortedSteps;
        const row = stageSnapshots[consoleStage]?.representativeStep;
        return row ? [row] : [];
    }, [consoleStage, sortedSteps, stageSnapshots]);

    useEffect(() => {
        if (!stepDrawerStepId) return;
        if (sortedSteps.some((item) => item.id === stepDrawerStepId)) return;
        setStepDrawerStepId('');
    }, [stepDrawerStepId, sortedSteps]);

    const stepDrawerStep = useMemo(
        () => sortedSteps.find((item) => item.id === stepDrawerStepId) || null,
        [sortedSteps, stepDrawerStepId],
    );

    const roundDurationText = useMemo(
        () => formatDuration(computeDurationMs(round?.startedAt, round?.endedAt, nowMs)),
        [round?.startedAt, round?.endedAt, nowMs],
    );

    const roundProgressPercent = useMemo(() => {
        if (steps.length > 0) {
            const done = steps.filter((item) => isTerminalStepState(item.state)).length;
            return Math.max(0, Math.min(100, Number(((done / steps.length) * 100).toFixed(2))));
        }
        const stepCounts = round?.stepCounts || {};
        const total = Object.values(stepCounts).reduce((sum, item) => sum + Number(item || 0), 0);
        if (!total) return 0;
        const done = ['succeeded', 'failed', 'cancelled', 'skipped']
            .reduce((sum, key) => sum + Number((stepCounts as Record<string, number>)[key] || 0), 0);
        return Math.max(0, Math.min(100, Number(((done / total) * 100).toFixed(2))));
    }, [round?.stepCounts, steps]);

    const trainFinalMetricPairs = useMemo(
        () => orderMetricEntries(round?.trainFinalMetrics || trainStep?.metrics || {}),
        [round?.trainFinalMetrics, trainStep?.id, trainStep?.metrics],
    );

    const evalFinalMetricPairs = useMemo(
        () => orderMetricEntries(round?.evalFinalMetrics || stageSnapshots.eval.metricSummary || evalStep?.metrics || {}),
        [round?.evalFinalMetrics, stageSnapshots.eval.metricSummary, evalStep?.id, evalStep?.metrics],
    );

    const finalMetricPairs = useMemo(
        () => orderMetricEntries(round?.finalMetrics || {}),
        [round?.finalMetrics],
    );

    const finalMetricsSource = useMemo(
        () => normalizeFinalMetricSource(round?.finalMetricsSource),
        [round?.finalMetricsSource],
    );

    const finalArtifactNames = useMemo(
        () => Object.keys(round?.finalArtifacts || {}).slice(0, 8),
        [round?.finalArtifacts],
    );

    const trainMetricNames = useMemo(() => {
        const names = new Set<string>();
        trainMetricPoints.forEach((item) => names.add(item.metricName));
        return Array.from(names);
    }, [trainMetricPoints]);

    const trainMetricChartData = useMemo(() => {
        const rows = new Map<number, Record<string, number>>();
        trainMetricPoints.forEach((point) => {
            const stepKey = Number(point.step || 0);
            const current = rows.get(stepKey) || {step: stepKey};
            current[point.metricName] = Number(point.metricValue);
            rows.set(stepKey, current);
        });
        return Array.from(rows.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
    }, [trainMetricPoints]);

    const trainScoreAxisUpperBound = useMemo(() => {
        let maxValue = 0;
        trainMetricPoints.forEach((point) => {
            if (isLossMetricName(point.metricName)) return;
            const value = Number(point.metricValue);
            if (!Number.isFinite(value)) return;
            maxValue = Math.max(maxValue, value);
        });
        if (maxValue <= 0) return 1;
        const padded = Math.min(1, maxValue * 1.1);
        return Math.max(0.05, Number(padded.toFixed(4)));
    }, [trainMetricPoints]);

    const roundArtifactRows = useMemo<RoundArtifactTableRow[]>(() => {
        return (roundArtifacts || [])
            .filter((item) => String(item.taskId || '').trim().length > 0)
            .map((item) => {
            const taskId = String(item.taskId || '').trim();
            const stageKey = String(item.stage || '').trim().toLowerCase() as RoundStageKey;
            const stageLabel = STAGE_LABEL[stageKey] || String(item.stage || '-');
            const artifactClass = String(item.artifactClass || '').trim().toLowerCase();
            return {
                key: buildArtifactKey(taskId, item.name),
                stage: String(item.stage || ''),
                stageLabel,
                artifactClass,
                artifactClassLabel: ARTIFACT_CLASS_LABEL[artifactClass] || artifactClass || '-',
                stepId: item.stepId,
                taskId: item.taskId,
                stepIndex: Number(item.stepIndex || 0),
                name: item.name,
                kind: item.kind,
                size: item.size,
                createdAt: item.createdAt,
            };
            });
    }, [roundArtifacts]);

    const handleSelectStep = (step: RuntimeStep) => {
        setStepDrawerStepId(step.id);
        setStepDrawerOpen(true);
        setConsoleStage(mapStepTypeToStage(step.stepType));
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

    if (!round) {
        return (
            <Card className="!border-github-border !bg-github-panel">
                <Empty description="Round 不存在或无权限访问"/>
            </Card>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <RoundHeaderTimelineCard
                round={round}
                sortedSteps={sortedSteps}
                currentTimelineIndex={currentTimelineIndex}
                nowMs={nowMs}
                wsConnected={wsConnected}
                refreshing={refreshing}
                retrying={retrying}
                onRetryRound={handleRetryRound}
                onRefresh={() => loadRoundData(true)}
                onOpenRoundOverview={() => setRoundOverviewOpen(true)}
                onOpenLoopDetail={() => navigate(`/projects/${projectId}/loops/${loopId}`)}
                onOpenPublishModel={() => navigate(`/projects/${projectId}/models?roundId=${round.id}`)}
                onOpenPredictionTasks={() => navigate(`/projects/${projectId}/prediction-tasks`)}
                onSelectStep={handleSelectStep}
            />

            <TrainCurveCard
                trainStep={trainStep}
                trainMetricChartData={trainMetricChartData}
                trainMetricNames={trainMetricNames}
                trainScoreAxisUpperBound={trainScoreAxisUpperBound}
            />

            <ArtifactTableCard roundArtifactRows={roundArtifactRows} artifactUrls={artifactUrls}/>

            <TopKCandidatesCard
                roundMode={round.mode}
                topkCandidates={topkCandidates}
                topkSource={topkSource}
            />

            <MetricsOverviewCard
                trainFinalMetricPairs={trainFinalMetricPairs}
                evalFinalMetricPairs={evalFinalMetricPairs}
                finalMetricPairs={finalMetricPairs}
                finalMetricsSource={finalMetricsSource}
            />

            <RoundConsolePanel
                className="!border-github-border !bg-github-panel"
                title={
                    consoleStage === 'all'
                        ? 'Round 控制台日志 · 全部阶段'
                        : (consoleStep
                            ? `Round 控制台日志 · ${STAGE_LABEL[consoleStage]} (#${consoleStep.stepIndex} ${consoleStep.stepType})`
                            : 'Round 控制台日志')
                }
                wsConnected={wsConnected}
                events={events}
                stageValue={consoleStage}
                stageOptions={consoleStageOptions.map((item) => ({
                    label: String(item.label),
                    value: String(item.value),
                }))}
                onStageChange={(value) => setConsoleStage(value as ConsoleStageFilter)}
                onClearBuffer={clearEventsBuffer}
                emptyDescription={consoleTargetSteps.length === 0 ? '当前 Round 暂无可用日志阶段' : '暂无命中日志'}
                exportFilePrefix={`round-${round.roundIndex}-${consoleStage}`}
            />

            <RoundOverviewDrawer
                open={roundOverviewOpen}
                onClose={() => setRoundOverviewOpen(false)}
                round={round}
                stepsLength={steps.length}
                roundDurationText={roundDurationText}
                roundProgressPercent={roundProgressPercent}
                trainFinalMetricPairs={trainFinalMetricPairs}
                evalFinalMetricPairs={evalFinalMetricPairs}
                finalMetricPairs={finalMetricPairs}
                finalMetricsSource={finalMetricsSource}
                finalArtifactNames={finalArtifactNames}
            />

            <StepDetailDrawer
                open={stepDrawerOpen}
                onClose={() => setStepDrawerOpen(false)}
                step={stepDrawerStep}
                nowMs={nowMs}
            />
        </div>
    );
};

export default ProjectLoopRoundDetail;
