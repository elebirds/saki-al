import React from 'react';
import {Card, Empty, Table, Tag} from 'antd';
import {
    Bar,
    BarChart,
    CartesianGrid,
    Legend,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';

import {RuntimeStep} from '../../../../types';
import {formatMetricValue} from '../runtimeMetricView';

interface EvalScopeCompareCardProps {
    evalStep: RuntimeStep | null;
    rows: Array<Record<string, number | string>>;
}

const SCOPE_LABEL: Record<string, string> = {
    test_anchor: 'TEST_ANCHOR',
    test_batch: 'TEST_BATCH',
    test_composite: 'TEST_COMPOSITE',
};

const EvalScopeCompareCard: React.FC<EvalScopeCompareCardProps> = ({evalStep, rows}) => {
    return (
        <Card className="!border-github-border !bg-github-panel" title="评估三口径对比（Metric Series）">
            {!evalStep ? (
                <Empty description="当前 Round 无评估阶段"/>
            ) : rows.length === 0 ? (
                <Empty description="评估阶段暂无三口径指标"/>
            ) : (
                <div className="space-y-4">
                    <div className="h-[280px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={rows}>
                                <CartesianGrid strokeDasharray="3 3"/>
                                <XAxis dataKey="scope"/>
                                <YAxis domain={[0, 1]}/>
                                <Tooltip/>
                                <Legend/>
                                <Bar dataKey="map50" fill="#1677ff"/>
                                <Bar dataKey="map50_95" fill="#52c41a"/>
                                <Bar dataKey="precision" fill="#faad14"/>
                                <Bar dataKey="recall" fill="#13c2c2"/>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                    <Table<Record<string, number | string>>
                        size="small"
                        rowKey={(row) => String(row.scope)}
                        pagination={false}
                        dataSource={rows}
                        columns={[
                            {
                                title: '口径',
                                dataIndex: 'scope',
                                render: (value: string) => <Tag>{SCOPE_LABEL[String(value)] || String(value)}</Tag>,
                            },
                            {
                                title: 'map50',
                                dataIndex: 'map50',
                                render: (value: unknown) => formatMetricValue(value),
                            },
                            {
                                title: 'map50_95',
                                dataIndex: 'map50_95',
                                render: (value: unknown) => formatMetricValue(value),
                            },
                            {
                                title: 'precision',
                                dataIndex: 'precision',
                                render: (value: unknown) => formatMetricValue(value),
                            },
                            {
                                title: 'recall',
                                dataIndex: 'recall',
                                render: (value: unknown) => formatMetricValue(value),
                            },
                        ]}
                    />
                </div>
            )}
        </Card>
    );
};

export default EvalScopeCompareCard;
