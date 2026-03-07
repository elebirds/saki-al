import React from 'react';
import {Card, Empty, Progress, Table, Tag, Typography} from 'antd';

import {RuntimeRound, RuntimeTaskCandidate} from '../../../../types';

const {Text} = Typography;

interface TopKCandidatesCardProps {
    roundMode?: RuntimeRound['mode'];
    topkCandidates: RuntimeTaskCandidate[];
    topkSource: string;
}

const TopKCandidatesCard: React.FC<TopKCandidatesCardProps> = ({
    roundMode,
    topkCandidates,
    topkSource,
}) => {
    if (roundMode === 'manual') return null;

    return (
        <Card
            className="!border-github-border !bg-github-panel"
            title="候选样本 / TopK"
            extra={<Tag>{`来源: ${topkSource}`}</Tag>}
        >
            {topkCandidates.length === 0 ? (
                <Empty description="当前 Round 暂无候选样本"/>
            ) : (
                <Table
                    size="small"
                    pagination={{pageSize: 10, showSizeChanger: false}}
                    dataSource={topkCandidates}
                    rowKey={(item) => `${item.sampleId}-${item.rank}`}
                    columns={[
                        {title: '#', dataIndex: 'rank', width: 60},
                        {
                            title: 'Sample ID',
                            dataIndex: 'sampleId',
                            render: (value: string) => <Text code>{value}</Text>,
                        },
                        {
                            title: 'Score',
                            dataIndex: 'score',
                            width: 220,
                            render: (value: number) => {
                                const percent = Math.max(0, Math.min(100, Number((Number(value || 0) * 100).toFixed(2))));
                                return (
                                    <div className="flex w-full flex-col gap-0.5">
                                        <Progress percent={percent}/>
                                        <Text type="secondary">{Number(value || 0).toFixed(6)}</Text>
                                    </div>
                                );
                            },
                        },
                        {
                            title: 'Reason',
                            dataIndex: 'reason',
                            render: (value: Record<string, any>) => <Text type="secondary">{JSON.stringify(value || {})}</Text>,
                        },
                    ]}
                />
            )}
        </Card>
    );
};

export default TopKCandidatesCard;
