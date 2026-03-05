import React from 'react';
import {Card, Empty} from 'antd';
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';

import {RuntimeStep} from '../../../../types';
import {TRAIN_METRIC_COLORS} from './constants';
import {isLossMetricName} from './transforms';

interface TrainCurveCardProps {
    trainStep: RuntimeStep | null;
    trainMetricChartData: Array<Record<string, number>>;
    trainMetricNames: string[];
    trainScoreAxisUpperBound: number;
}

const TrainCurveCard: React.FC<TrainCurveCardProps> = ({
    trainStep,
    trainMetricChartData,
    trainMetricNames,
    trainScoreAxisUpperBound,
}) => {
    return (
        <Card className="!border-github-border !bg-github-panel" title="训练曲线">
            {!trainStep ? (
                <Empty description="当前 Round 无训练阶段"/>
            ) : trainMetricChartData.length === 0 ? (
                <Empty description="训练阶段暂无指标曲线"/>
            ) : (
                <div className="h-[320px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={trainMetricChartData}>
                            <CartesianGrid strokeDasharray="3 3"/>
                            <XAxis dataKey="step"/>
                            <YAxis yAxisId="metric" domain={[0, trainScoreAxisUpperBound]}/>
                            <YAxis yAxisId="loss" orientation="right"/>
                            <Tooltip/>
                            {trainMetricNames.map((name, idx) => (
                                <Line
                                    key={name}
                                    type="monotone"
                                    dataKey={name}
                                    yAxisId={isLossMetricName(name) ? 'loss' : 'metric'}
                                    dot={false}
                                    stroke={TRAIN_METRIC_COLORS[idx % TRAIN_METRIC_COLORS.length]}
                                    strokeWidth={2}
                                />
                            ))}
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            )}
        </Card>
    );
};

export default TrainCurveCard;
