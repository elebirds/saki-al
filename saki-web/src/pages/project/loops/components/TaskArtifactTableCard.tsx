import React, {useCallback, useState} from 'react';
import {App, Button, Card, Empty, Table, Tag, Typography} from 'antd';

import {buildArtifactKey, formatArtifactSize} from '../roundDetail/transforms';
import {formatDateTime} from '../runtimeTime';

const {Text} = Typography;

export interface TaskArtifactTableRow {
    key: string;
    taskId: string;
    name: string;
    kind: string;
    uri?: string | null;
    size?: number | null;
    createdAt?: string | null;
    sourceLabel?: string;
    sourceClassLabel?: string;
    sequenceLabel?: string;
}

interface TaskArtifactTableCardProps {
    title?: React.ReactNode;
    emptyDescription?: string;
    rows: TaskArtifactTableRow[];
    artifactUrls: Record<string, string>;
    resolveArtifactUrl?: (row: TaskArtifactTableRow) => Promise<string | null>;
    showSource?: boolean;
    showSourceClass?: boolean;
    showSequence?: boolean;
}

const TaskArtifactTableCard: React.FC<TaskArtifactTableCardProps> = ({
    title = '制品',
    emptyDescription = '暂无制品',
    rows,
    artifactUrls,
    resolveArtifactUrl,
    showSource = false,
    showSourceClass = false,
    showSequence = false,
}) => {
    const {message} = App.useApp();
    const [loadingByKey, setLoadingByKey] = useState<Record<string, boolean>>({});

    const handleDownload = useCallback(async (row: TaskArtifactTableRow) => {
        const taskId = String(row.taskId || '').trim();
        if (!taskId) return;
        const key = buildArtifactKey(taskId, row.name);
        const currentUrl = artifactUrls[key];
        if (currentUrl) {
            window.open(currentUrl, '_blank', 'noopener,noreferrer');
            return;
        }
        if (!resolveArtifactUrl) return;

        setLoadingByKey((prev) => ({...prev, [key]: true}));
        try {
            const resolved = await resolveArtifactUrl(row);
            if (resolved) {
                window.open(resolved, '_blank', 'noopener,noreferrer');
            } else {
                message.warning('当前制品暂不可下载');
            }
        } catch (error: any) {
            message.error(error?.message || '获取下载链接失败');
        } finally {
            setLoadingByKey((prev) => ({...prev, [key]: false}));
        }
    }, [artifactUrls, resolveArtifactUrl, message]);

    return (
        <Card className="!border-github-border !bg-github-panel" title={title}>
            {rows.length === 0 ? (
                <Empty description={emptyDescription}/>
            ) : (
                <Table<TaskArtifactTableRow>
                    size="small"
                    rowKey={(row) => row.key}
                    dataSource={rows}
                    pagination={{pageSize: 10, showSizeChanger: false}}
                    columns={[
                        ...(showSource ? [{
                            title: '来源',
                            dataIndex: 'sourceLabel',
                            width: 120,
                            render: (_value: unknown, row: TaskArtifactTableRow) => (
                                <Tag>{String(row.sourceLabel || '-')}</Tag>
                            ),
                        }] : []),
                        ...(showSourceClass ? [{
                            title: '类别',
                            dataIndex: 'sourceClassLabel',
                            width: 120,
                            render: (_value: unknown, row: TaskArtifactTableRow) => (
                                <Tag>{String(row.sourceClassLabel || '-')}</Tag>
                            ),
                        }] : []),
                        {title: '名称', dataIndex: 'name'},
                        {title: '类型', dataIndex: 'kind', width: 180, render: (value: string) => <Tag>{value}</Tag>},
                        {
                            title: '大小',
                            width: 120,
                            render: (_value: unknown, row: TaskArtifactTableRow) => formatArtifactSize(row.size),
                        },
                        ...(showSequence ? [{
                            title: '序号',
                            width: 100,
                            render: (_value: unknown, row: TaskArtifactTableRow) => String(row.sequenceLabel || '-'),
                        }] : []),
                        {
                            title: '时间',
                            width: 180,
                            render: (_value: unknown, row: TaskArtifactTableRow) => formatDateTime(row.createdAt),
                        },
                        {
                            title: '操作',
                            width: 220,
                            render: (_value: unknown, row: TaskArtifactTableRow) => {
                                const taskId = String(row.taskId || '').trim();
                                const url = taskId ? artifactUrls[buildArtifactKey(taskId, row.name)] : undefined;
                                const key = taskId ? buildArtifactKey(taskId, row.name) : row.key;
                                const isLoading = Boolean(loadingByKey[key]);
                                if (!taskId) {
                                    return <Text type="secondary">暂不可下载</Text>;
                                }
                                if (!url && !resolveArtifactUrl) {
                                    return <Text type="secondary">暂不可下载</Text>;
                                }
                                return (
                                    <Button
                                        size="small"
                                        loading={isLoading}
                                        onClick={() => void handleDownload(row)}
                                    >
                                        {url ? '下载/预览' : '获取链接并下载'}
                                    </Button>
                                );
                            },
                        },
                    ]}
                />
            )}
        </Card>
    );
};

export default TaskArtifactTableCard;
