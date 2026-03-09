import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Select, Spin, Table, Tag, message } from 'antd';

import { api } from '../../services/api';
import {
    RuntimeDesiredStateResponse,
    RuntimeRelease,
    RuntimeReleaseListResponse,
    RuntimeUpdateAttempt,
    RuntimeUpdateAttemptListResponse,
} from '../../types';

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
};

const RuntimeReleases: React.FC = () => {
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [releases, setReleases] = useState<RuntimeReleaseListResponse | null>(null);
    const [desiredState, setDesiredState] = useState<RuntimeDesiredStateResponse | null>(null);
    const [attempts, setAttempts] = useState<RuntimeUpdateAttemptListResponse | null>(null);

    const loadAll = useCallback(async () => {
        setLoading(true);
        try {
            const [releaseResp, desiredResp, attemptResp] = await Promise.all([
                api.getRuntimeReleases(),
                api.getRuntimeDesiredState(),
                api.getRuntimeUpdateAttempts({limit: 50}),
            ]);
            setReleases(releaseResp);
            setDesiredState(desiredResp);
            setAttempts(attemptResp);
        } catch (error: any) {
            message.error(error?.message || '加载 runtime 发布信息失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadAll();
    }, [loadAll]);

    const releaseGroups = useMemo(() => {
        const rows = releases?.items || [];
        const groups = new Map<string, RuntimeRelease[]>();
        rows.forEach((item) => {
            const key = `${item.componentType}:${item.componentName}`;
            const bucket = groups.get(key) || [];
            bucket.push(item);
            groups.set(key, bucket);
        });
        return Array.from(groups.entries()).map(([key, items]) => ({
            key,
            componentType: items[0].componentType,
            componentName: items[0].componentName,
            items: [...items].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()),
        }));
    }, [releases]);

    const desiredStateMap = useMemo(() => {
        const result = new Map<string, string>();
        (desiredState?.items || []).forEach((item) => {
            result.set(`${item.componentType}:${item.componentName}`, item.release.id);
        });
        return result;
    }, [desiredState]);

    const handleUpload = useCallback(async () => {
        if (!selectedFile) {
            message.warning('请先选择 tar.gz 发布包');
            return;
        }
        setUploading(true);
        try {
            await api.createRuntimeRelease(selectedFile);
            message.success('发布包上传成功');
            setSelectedFile(null);
            void loadAll();
        } catch (error: any) {
            message.error(error?.message || '发布包上传失败');
        } finally {
            setUploading(false);
        }
    }, [loadAll, selectedFile]);

    const handleDesiredChange = useCallback(async (componentType: string, componentName: string, releaseId?: string) => {
        try {
            await api.patchRuntimeDesiredState({
                items: [{
                    componentType: componentType as 'executor' | 'plugin',
                    componentName,
                    releaseId: releaseId || null,
                }],
            });
            message.success('目标版本已更新');
            void loadAll();
        } catch (error: any) {
            message.error(error?.message || '更新目标版本失败');
        }
    }, [loadAll]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large" />
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto">
            <Card title="Runtime 发布管理" bordered className="border-github-border bg-github-panel">
                <div className="flex flex-wrap items-center gap-3">
                    <input
                        type="file"
                        accept=".tar.gz"
                        onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
                    />
                    <Button type="primary" loading={uploading} onClick={() => void handleUpload()}>
                        上传发布包
                    </Button>
                    <span className="text-xs text-github-muted">
                        仅支持 tar.gz。plugin 包需包含 `plugin.yml`，executor 包需包含 `pyproject.toml`、`uv.lock`、`src/`。
                    </span>
                </div>
                {selectedFile ? (
                    <div className="mt-3 text-sm text-github-text">
                        已选择: <code>{selectedFile.name}</code>
                    </div>
                ) : null}
            </Card>

            <Card title="全局目标版本" bordered className="border-github-border bg-github-panel">
                {releaseGroups.length === 0 ? (
                    <Empty description="暂无可用发布版本" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                    <div className="grid gap-3">
                        {releaseGroups.map((group) => (
                            <div key={group.key} className="rounded-md border border-github-border p-3">
                                <div className="mb-2 flex flex-wrap items-center gap-2">
                                    <Tag color={group.componentType === 'executor' ? 'blue' : 'green'}>
                                        {group.componentType}
                                    </Tag>
                                    <code>{group.componentName}</code>
                                </div>
                                <div className="flex flex-wrap items-center gap-3">
                                    <Select
                                        style={{ minWidth: 320 }}
                                        placeholder="选择目标版本"
                                        value={desiredStateMap.get(group.key)}
                                        allowClear
                                        options={group.items.map((item) => ({
                                            value: item.id,
                                            label: `${item.version} · ${formatDateTime(item.createdAt)}`,
                                        }))}
                                        onChange={(value) => {
                                            void handleDesiredChange(group.componentType, group.componentName, value);
                                        }}
                                    />
                                    {desiredStateMap.get(group.key) ? <Tag color="processing">已设置目标</Tag> : <Tag>未设置</Tag>}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </Card>

            <Card title="最近更新尝试" bordered className="border-github-border bg-github-panel">
                {(attempts?.items || []).length === 0 ? (
                    <Empty description="暂无更新记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                    <Table<RuntimeUpdateAttempt>
                        rowKey="id"
                        dataSource={attempts?.items || []}
                        pagination={false}
                        columns={[
                            { title: 'Executor', dataIndex: 'executorId', key: 'executorId', render: (value) => <code>{value}</code> },
                            { title: '组件', key: 'component', render: (_, row) => `${row.componentType}:${row.componentName}` },
                            { title: '版本', key: 'version', render: (_, row) => `${row.fromVersion || '-'} -> ${row.targetVersion}` },
                            { title: '状态', dataIndex: 'status', key: 'status', render: (value, row) => <Tag color={row.rolledBack ? 'orange' : 'blue'}>{value}</Tag> },
                            { title: '详情', dataIndex: 'detail', key: 'detail', ellipsis: true },
                            { title: '开始时间', dataIndex: 'startedAt', key: 'startedAt', render: (value) => formatDateTime(value) },
                            { title: '结束时间', dataIndex: 'endedAt', key: 'endedAt', render: (value) => formatDateTime(value) },
                        ]}
                    />
                )}
            </Card>

            <Card title="发布目录" bordered className="border-github-border bg-github-panel">
                {(releases?.items || []).length === 0 ? (
                    <Empty description="暂无发布包" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                    <Table<RuntimeRelease>
                        rowKey="id"
                        dataSource={releases?.items || []}
                        pagination={false}
                        columns={[
                            { title: '组件', key: 'component', render: (_, row) => `${row.componentType}:${row.componentName}` },
                            { title: '版本', dataIndex: 'version', key: 'version', render: (value) => <Tag color="blue">v{value}</Tag> },
                            { title: 'SHA256', dataIndex: 'sha256', key: 'sha256', render: (value) => <code>{String(value || '').slice(0, 12)}</code> },
                            { title: '大小', dataIndex: 'sizeBytes', key: 'sizeBytes', render: (value) => `${value} B` },
                            { title: '创建时间', dataIndex: 'createdAt', key: 'createdAt', render: (value) => formatDateTime(value) },
                        ]}
                    />
                )}
            </Card>

            <Alert
                type="info"
                showIcon
                message="V1 为全局单目标收敛"
                description="dispatcher 会把漂移 executor 标记为 update_pending 并暂时排除出调度候选；空闲后按插件优先、executor 其次的顺序单步更新。"
            />
        </div>
    );
};

export default RuntimeReleases;
