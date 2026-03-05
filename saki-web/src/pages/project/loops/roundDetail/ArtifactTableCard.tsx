import React from 'react';
import {Button, Card, Empty, Table, Tag, Typography} from 'antd';

import {RoundArtifactTableRow} from './types';
import {buildArtifactKey, formatArtifactSize} from './transforms';
import {formatDateTime} from '../runtimeTime';

const {Text} = Typography;

interface ArtifactTableCardProps {
    roundArtifactRows: RoundArtifactTableRow[];
    artifactUrls: Record<string, string>;
}

const ArtifactTableCard: React.FC<ArtifactTableCardProps> = ({roundArtifactRows, artifactUrls}) => {
    return (
        <Card className="!border-github-border !bg-github-panel" title="制品">
            {roundArtifactRows.length === 0 ? (
                <Empty description="当前 Round 暂无制品"/>
            ) : (
                <Table<RoundArtifactTableRow>
                    size="small"
                    rowKey={(row) => row.key}
                    dataSource={roundArtifactRows}
                    pagination={{pageSize: 10, showSizeChanger: false}}
                    columns={[
                        {
                            title: '来源阶段',
                            dataIndex: 'stageLabel',
                            width: 120,
                            render: (_value: unknown, row: RoundArtifactTableRow) => (
                                <Tag>{row.stageLabel}</Tag>
                            ),
                        },
                        {
                            title: '类别',
                            dataIndex: 'artifactClassLabel',
                            width: 120,
                            render: (_value: unknown, row: RoundArtifactTableRow) => <Tag>{row.artifactClassLabel}</Tag>,
                        },
                        {title: '名称', dataIndex: 'name'},
                        {title: '类型', dataIndex: 'kind', width: 180, render: (value: string) => <Tag>{value}</Tag>},
                        {
                            title: '大小',
                            width: 120,
                            render: (_value: unknown, row: RoundArtifactTableRow) => formatArtifactSize(row.size),
                        },
                        {
                            title: 'Step',
                            width: 100,
                            render: (_value: unknown, row: RoundArtifactTableRow) => `#${row.stepIndex}`,
                        },
                        {
                            title: '时间',
                            width: 180,
                            render: (_value: unknown, row: RoundArtifactTableRow) => formatDateTime(row.createdAt),
                        },
                        {
                            title: '操作',
                            width: 220,
                            render: (_value: unknown, row: RoundArtifactTableRow) => {
                                const url = artifactUrls[buildArtifactKey(row.stepId, row.name)];
                                return url ? (
                                    <Button size="small" onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}>
                                        下载/预览
                                    </Button>
                                ) : (
                                    <Text type="secondary">暂不可下载</Text>
                                );
                            },
                        },
                    ]}
                />
            )}
        </Card>
    );
};

export default ArtifactTableCard;
