import React from 'react';
import {Button, Card, Empty, Steps, Tag, Typography} from 'antd';

import {RuntimeRound, RuntimeStep} from '../../../../types';
import {computeDurationMs} from '../runtimeTime';
import {ROUND_STATE_COLOR} from './constants';
import {getStepFlowStatus} from './transforms';

const {Text, Title} = Typography;

interface RoundHeaderTimelineCardProps {
    round: RuntimeRound;
    sortedSteps: RuntimeStep[];
    currentTimelineIndex: number;
    nowMs: number;
    wsConnected: boolean;
    refreshing: boolean;
    retrying: boolean;
    onRetryRound: () => void;
    onRefresh: () => void;
    onOpenRoundOverview: () => void;
    onOpenLoopDetail: () => void;
    onOpenPublishModel: () => void;
    onOpenPredictionTasks: () => void;
    onSelectStep: (step: RuntimeStep) => void;
}

const RoundHeaderTimelineCard: React.FC<RoundHeaderTimelineCardProps> = ({
    round,
    sortedSteps,
    currentTimelineIndex,
    nowMs,
    wsConnected,
    refreshing,
    retrying,
    onRetryRound,
    onRefresh,
    onOpenRoundOverview,
    onOpenLoopDetail,
    onOpenPublishModel,
    onOpenPredictionTasks,
    onSelectStep,
}) => {
    return (
        <Card className="!border-github-border !bg-github-panel">
            <div className="flex w-full flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={onOpenLoopDetail}>返回 Loop 详情</Button>
                        <Title level={4} className="!mb-0">Round #{round.roundIndex} · Attempt {round.attemptIndex || 1}</Title>
                        <Tag color={ROUND_STATE_COLOR[round.state] || 'default'}>{round.state}</Tag>
                        {round.awaitingConfirm ? <Tag color="gold">awaiting_confirm</Tag> : null}
                    </div>
                    <Text type="secondary">{round.id}</Text>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Tag color={wsConnected ? 'success' : 'default'}>{wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'}</Tag>
                    <Button onClick={onOpenPublishModel}>
                        发布模型
                    </Button>
                    <Button onClick={onOpenPredictionTasks}>
                        预测任务快捷入口
                    </Button>
                    {round.state === 'failed' ? (
                        <Button type="primary" loading={retrying} onClick={onRetryRound}>
                            重跑本轮
                        </Button>
                    ) : null}
                    <Button onClick={onOpenRoundOverview}>Round 概览</Button>
                    <Button loading={refreshing} onClick={onRefresh}>刷新</Button>
                </div>
            </div>
            <div className="mt-4 border-t border-github-border pt-4">
                {sortedSteps.length === 0 ? (
                    <Empty description="当前 Round 没有 Step"/>
                ) : (
                    <Steps
                        current={Math.max(0, currentTimelineIndex)}
                        onChange={(index) => {
                            const target = sortedSteps[index];
                            if (!target) return;
                            onSelectStep(target);
                        }}
                        items={sortedSteps.map((item) => ({
                            title: `#${item.stepIndex} ${item.stepType}`,
                            description: (
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-xs text-github-muted">{`state: ${item.state}`}</span>
                                    <span className="text-xs text-github-muted">
                                        {`elapsed: ${Math.floor(computeDurationMs(item.startedAt, item.endedAt, nowMs) / 1000)}s`}
                                    </span>
                                </div>
                            ),
                            status: getStepFlowStatus(item.state),
                        }))}
                        size="small"
                    />
                )}
            </div>
        </Card>
    );
};

export default RoundHeaderTimelineCard;
