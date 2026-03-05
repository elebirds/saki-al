import React from 'react';
import {Alert, Descriptions, Drawer, Progress, Tag, Typography} from 'antd';

import {RuntimeRound} from '../../../../types';
import {FINAL_METRIC_SOURCE_LABEL} from './constants';
import {formatDateTime} from '../runtimeTime';
import {formatMetricValue} from '../runtimeMetricView';

const {Text} = Typography;

interface RoundOverviewDrawerProps {
    open: boolean;
    onClose: () => void;
    round: RuntimeRound;
    stepsLength: number;
    roundDurationText: string;
    roundProgressPercent: number;
    trainFinalMetricPairs: Array<[string, any]>;
    evalFinalMetricPairs: Array<[string, any]>;
    finalMetricPairs: Array<[string, any]>;
    finalMetricsSource: 'eval' | 'train' | 'other' | 'none';
    finalArtifactNames: string[];
}

const RoundOverviewDrawer: React.FC<RoundOverviewDrawerProps> = ({
    open,
    onClose,
    round,
    stepsLength,
    roundDurationText,
    roundProgressPercent,
    trainFinalMetricPairs,
    evalFinalMetricPairs,
    finalMetricPairs,
    finalMetricsSource,
    finalArtifactNames,
}) => {
    return (
        <Drawer
            open={open}
            onClose={onClose}
            width={560}
            title={`Round 概览 · #${round.roundIndex} / Attempt ${round.attemptIndex || 1}`}
        >
            <Descriptions size="small" column={1}>
                <Descriptions.Item label="插件">{round.pluginId}</Descriptions.Item>
                <Descriptions.Item label="采样策略">{round.resolvedParams?.sampling?.strategy || '-'}</Descriptions.Item>
                <Descriptions.Item label="模式">{round.mode}</Descriptions.Item>
                <Descriptions.Item label="Attempt">{round.attemptIndex || 1}</Descriptions.Item>
                <Descriptions.Item label="开始时间">{formatDateTime(round.startedAt)}</Descriptions.Item>
                <Descriptions.Item label="结束时间">{formatDateTime(round.endedAt)}</Descriptions.Item>
                <Descriptions.Item label="耗时">{roundDurationText}</Descriptions.Item>
                <Descriptions.Item label="Step 数量">{stepsLength}</Descriptions.Item>
                <Descriptions.Item label="Retry From">{round.retryOfRoundId || '-'}</Descriptions.Item>
                <Descriptions.Item label="Retry Reason">{round.retryReason || '-'}</Descriptions.Item>
                <Descriptions.Item label="Train 终态">
                    {trainFinalMetricPairs.length === 0
                        ? '-'
                        : trainFinalMetricPairs.map(([key, value]) => (
                            <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
                        ))}
                </Descriptions.Item>
                <Descriptions.Item label="Eval(Test) 终态">
                    {evalFinalMetricPairs.length === 0
                        ? '-'
                        : evalFinalMetricPairs.map(([key, value]) => (
                            <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
                        ))}
                </Descriptions.Item>
                <Descriptions.Item label="Final Metrics">
                    <Tag color={finalMetricsSource === 'eval' ? 'blue' : (finalMetricsSource === 'train' ? 'green' : 'default')}>
                        {`source: ${FINAL_METRIC_SOURCE_LABEL[finalMetricsSource]}`}
                    </Tag>
                    {finalMetricPairs.length === 0
                        ? <Text className="ml-2">-</Text>
                        : finalMetricPairs.map(([key, value]) => (
                            <Text key={key} className="mr-2 block">{`${key}: ${formatMetricValue(value)}`}</Text>
                        ))}
                </Descriptions.Item>
                <Descriptions.Item label="Final Artifacts">
                    {finalArtifactNames.length === 0
                        ? '-'
                        : finalArtifactNames.map((name) => <Tag key={name}>{name}</Tag>)}
                </Descriptions.Item>
            </Descriptions>
            <div className="mt-3">
                <Text type="secondary">Round 进度</Text>
                <Progress percent={roundProgressPercent}/>
            </div>
            <div className="mt-2">
                <Text type="secondary">Step 聚合</Text>
                <div className="mt-1">
                    {(Object.entries(round.stepCounts || {}) as Array<[string, number]>).map(([key, value]) => (
                        <Tag key={key}>{`${key}:${value}`}</Tag>
                    ))}
                </div>
            </div>
            {round.lastError ? (
                <Alert className="!mt-3" type="error" showIcon message={round.lastError}/>
            ) : null}
        </Drawer>
    );
};

export default RoundOverviewDrawer;
