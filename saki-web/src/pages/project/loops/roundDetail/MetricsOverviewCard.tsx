import React from 'react';
import {Card, Descriptions, Empty, Tag, Typography} from 'antd';

import {FINAL_METRIC_SOURCE_LABEL} from './constants';
import {formatMetricValue} from '../runtimeMetricView';

const {Text} = Typography;

interface MetricsOverviewCardProps {
    trainFinalMetricPairs: Array<[string, any]>;
    evalFinalMetricPairs: Array<[string, any]>;
    finalMetricPairs: Array<[string, any]>;
    finalMetricsSource: 'eval' | 'train' | 'other' | 'none';
    trainingStopSummary?: {
        patience: string;
        bestEpoch: string;
        stoppedEpoch: string;
        earlyStopTriggered: boolean;
    } | null;
}

const MetricsOverviewCard: React.FC<MetricsOverviewCardProps> = ({
    trainFinalMetricPairs,
    evalFinalMetricPairs,
    finalMetricPairs,
    finalMetricsSource,
    trainingStopSummary,
}) => {
    return (
        <Card className="!border-github-border !bg-github-panel" title="指标总览">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                <div>
                    <Text strong>Train 终态</Text>
                    {trainingStopSummary ? (
                        <Descriptions size="small" column={1} className="!mt-2 !mb-2">
                            <Descriptions.Item label="patience">{trainingStopSummary.patience}</Descriptions.Item>
                            <Descriptions.Item label="best_epoch">{trainingStopSummary.bestEpoch}</Descriptions.Item>
                            <Descriptions.Item label="stopped_epoch">{trainingStopSummary.stoppedEpoch}</Descriptions.Item>
                            <Descriptions.Item label="early_stop_triggered">
                                {trainingStopSummary.earlyStopTriggered ? 'true' : 'false'}
                            </Descriptions.Item>
                        </Descriptions>
                    ) : null}
                    {trainFinalMetricPairs.length === 0 ? (
                        <Empty description="暂无指标"/>
                    ) : (
                        <Descriptions size="small" column={1} className="!mt-2">
                            {trainFinalMetricPairs.map(([key, value]) => (
                                <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                            ))}
                        </Descriptions>
                    )}
                </div>
                <div>
                    <Text strong>Eval(Test) 终态</Text>
                    {evalFinalMetricPairs.length === 0 ? (
                        <Empty description="暂无指标"/>
                    ) : (
                        <Descriptions size="small" column={1} className="!mt-2">
                            {evalFinalMetricPairs.map(([key, value]) => (
                                <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                            ))}
                        </Descriptions>
                    )}
                </div>
                <div>
                    <div className="flex items-center gap-2">
                        <Text strong>Round Final(对外口径)</Text>
                        <Tag color={finalMetricsSource === 'eval' ? 'blue' : (finalMetricsSource === 'train' ? 'green' : 'default')}>
                            {`source: ${FINAL_METRIC_SOURCE_LABEL[finalMetricsSource]}`}
                        </Tag>
                    </div>
                    {finalMetricPairs.length === 0 ? (
                        <Empty description="暂无指标"/>
                    ) : (
                        <Descriptions size="small" column={1} className="!mt-2">
                            {finalMetricPairs.map(([key, value]) => (
                                <Descriptions.Item key={key} label={key}>{formatMetricValue(value)}</Descriptions.Item>
                            ))}
                        </Descriptions>
                    )}
                </div>
            </div>
        </Card>
    );
};

export default MetricsOverviewCard;
