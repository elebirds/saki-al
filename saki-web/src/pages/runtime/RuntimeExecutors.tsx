import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Col,
    Descriptions,
    Empty,
    Progress,
    Row,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';

import {api} from '../../services/api';
import {RuntimeExecutorListResponse, RuntimeExecutorPluginCapability, RuntimeExecutorRead} from '../../types';

const {Title, Text} = Typography;

const STATUS_COLOR: Record<string, string> = {
    idle: 'success',
    reserved: 'processing',
    busy: 'processing',
    offline: 'default',
};

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return value;
    }
};

const extractPlugins = (executor: RuntimeExecutorRead | null): RuntimeExecutorPluginCapability[] => {
    if (!executor) return [];
    const raw = executor.pluginIds?.plugins;
    if (Array.isArray(raw)) {
        return raw;
    }
    return [];
};

const RuntimeExecutors: React.FC = () => {
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [detailLoading, setDetailLoading] = useState(false);
    const [data, setData] = useState<RuntimeExecutorListResponse | null>(null);
    const [selectedExecutorId, setSelectedExecutorId] = useState<string | null>(null);
    const [selectedExecutor, setSelectedExecutor] = useState<RuntimeExecutorRead | null>(null);

    const loadExecutors = useCallback(async (silent: boolean = false) => {
        if (silent) {
            setRefreshing(true);
        } else {
            setLoading(true);
        }
        try {
            const resp = await api.getRuntimeExecutors();
            setData(resp);
            if (!selectedExecutorId && resp.items.length > 0) {
                setSelectedExecutorId(resp.items[0].executorId);
                setSelectedExecutor(resp.items[0]);
            } else if (selectedExecutorId) {
                const matched = resp.items.find((item) => item.executorId === selectedExecutorId) || null;
                setSelectedExecutor(matched);
            }
        } catch (error: any) {
            message.error(error?.message || '加载执行器状态失败');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [selectedExecutorId]);

    const loadExecutorDetail = useCallback(async (executorId: string) => {
        setDetailLoading(true);
        try {
            const detail = await api.getRuntimeExecutor(executorId);
            setSelectedExecutor(detail);
        } catch (error: any) {
            message.error(error?.message || '加载执行器详情失败');
        } finally {
            setDetailLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadExecutors(false);
    }, [loadExecutors]);

    useEffect(() => {
        if (!selectedExecutorId) return;
        void loadExecutorDetail(selectedExecutorId);
    }, [selectedExecutorId, loadExecutorDetail]);

    const summary = data?.summary;
    const plugins = useMemo(() => extractPlugins(selectedExecutor), [selectedExecutor]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <Title level={4} className="!mb-1">Runtime Executors</Title>
                        <Text type="secondary">查看当前执行器在线情况、可用率与插件能力明细。</Text>
                    </div>
                    <Button loading={refreshing} onClick={() => loadExecutors(true)}>刷新</Button>
                </div>
            </Card>

            {summary ? (
                <Row gutter={[16, 16]}>
                    <Col xs={12} md={6}>
                        <Card className="!border-github-border !bg-github-panel" size="small">
                            <div className="text-xs text-github-muted">执行器总数</div>
                            <div className="text-2xl font-semibold text-github-text">{summary.totalCount}</div>
                        </Card>
                    </Col>
                    <Col xs={12} md={6}>
                        <Card className="!border-github-border !bg-github-panel" size="small">
                            <div className="text-xs text-github-muted">在线数</div>
                            <div className="text-2xl font-semibold text-github-text">{summary.onlineCount}</div>
                        </Card>
                    </Col>
                    <Col xs={12} md={6}>
                        <Card className="!border-github-border !bg-github-panel" size="small">
                            <div className="text-xs text-github-muted">忙碌数</div>
                            <div className="text-2xl font-semibold text-github-text">{summary.busyCount}</div>
                        </Card>
                    </Col>
                    <Col xs={12} md={6}>
                        <Card className="!border-github-border !bg-github-panel" size="small">
                            <div className="text-xs text-github-muted">可用数</div>
                            <div className="text-2xl font-semibold text-github-text">{summary.availableCount}</div>
                        </Card>
                    </Col>
                </Row>
            ) : null}

            <Card className="!border-github-border !bg-github-panel" title="可用率">
                <Space direction="vertical" className="w-full" size={4}>
                    <Progress percent={Number(((summary?.availabilityRate || 0) * 100).toFixed(2))}/>
                    <Text type="secondary">
                        pending assign: {summary?.pendingAssignCount || 0} · pending stop: {summary?.pendingStopCount || 0}
                        · latest heartbeat: {formatDateTime(summary?.latestHeartbeatAt)}
                    </Text>
                </Space>
            </Card>

            <Row gutter={[16, 16]}>
                <Col xs={24} xl={15}>
                    <Card className="!border-github-border !bg-github-panel" title="执行器列表">
                        {!data || data.items.length === 0 ? (
                            <Empty description="暂无执行器注册"/>
                        ) : (
                            <Table
                                size="small"
                                rowKey={(item) => item.executorId}
                                dataSource={data.items}
                                pagination={{pageSize: 8}}
                                onRow={(record) => ({
                                    onClick: () => setSelectedExecutorId(record.executorId),
                                })}
                                rowClassName={(record) => (
                                    record.executorId === selectedExecutorId ? '!bg-github-bg-subtle cursor-pointer' : 'cursor-pointer'
                                )}
                                columns={[
                                    {
                                        title: 'Executor',
                                        dataIndex: 'executorId',
                                        render: (v: string) => <Text code>{v}</Text>,
                                    },
                                    {
                                        title: '状态',
                                        dataIndex: 'status',
                                        width: 120,
                                        render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>,
                                    },
                                    {
                                        title: '在线',
                                        dataIndex: 'isOnline',
                                        width: 90,
                                        render: (v: boolean) => (v ? <Tag color="success">online</Tag> : <Tag>offline</Tag>),
                                    },
                                    {
                                        title: '当前任务',
                                        dataIndex: 'currentJobId',
                                        width: 220,
                                        render: (v: string | null) => (v ? <Text code>{v}</Text> : '-'),
                                    },
                                    {
                                        title: '插件数',
                                        width: 90,
                                        render: (_v: unknown, row: RuntimeExecutorRead) => extractPlugins(row).length,
                                    },
                                    {
                                        title: '可派发/待停止',
                                        width: 140,
                                        render: (_v: unknown, row: RuntimeExecutorRead) => `${row.pendingAssignCount}/${row.pendingStopCount}`,
                                    },
                                    {
                                        title: '最后心跳',
                                        dataIndex: 'lastSeenAt',
                                        width: 180,
                                        render: (v: string | null) => formatDateTime(v),
                                    },
                                ]}
                            />
                        )}
                    </Card>
                </Col>

                <Col xs={24} xl={9}>
                    <Card className="!border-github-border !bg-github-panel" title="执行器详情" loading={detailLoading}>
                        {!selectedExecutor ? (
                            <Empty description="请选择执行器查看详情"/>
                        ) : (
                            <Space direction="vertical" className="w-full" size={12}>
                                <Descriptions size="small" column={1}>
                                    <Descriptions.Item label="Executor ID">
                                        <Text code>{selectedExecutor.executorId}</Text>
                                    </Descriptions.Item>
                                    <Descriptions.Item label="版本">{selectedExecutor.version}</Descriptions.Item>
                                    <Descriptions.Item label="状态">
                                        <Tag color={STATUS_COLOR[selectedExecutor.status] || 'default'}>{selectedExecutor.status}</Tag>
                                    </Descriptions.Item>
                                    <Descriptions.Item label="当前任务">
                                        {selectedExecutor.currentJobId || '-'}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="最后心跳">
                                        {formatDateTime(selectedExecutor.lastSeenAt)}
                                    </Descriptions.Item>
                                </Descriptions>

                                {selectedExecutor.lastError ? (
                                    <Alert type="error" showIcon message={selectedExecutor.lastError}/>
                                ) : null}

                                <Card
                                    size="small"
                                    className="!border-github-border !bg-github-panel"
                                    title={`插件能力 (${plugins.length})`}
                                >
                                    {plugins.length === 0 ? (
                                        <Empty description="未上报插件能力" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
                                    ) : (
                                        <Table
                                            size="small"
                                            rowKey={(item) => item.pluginId}
                                            pagination={false}
                                            dataSource={plugins}
                                            columns={[
                                                {
                                                    title: 'Plugin',
                                                    dataIndex: 'displayName',
                                                    render: (v: string, row: RuntimeExecutorPluginCapability) => (
                                                        <Space direction="vertical" size={0}>
                                                            <Text>{v}</Text>
                                                            <Text type="secondary">{row.pluginId}</Text>
                                                        </Space>
                                                    ),
                                                },
                                                {
                                                    title: '策略',
                                                    dataIndex: 'supportedStrategies',
                                                    render: (v: string[]) => (
                                                        <div className="flex flex-wrap gap-1">
                                                            {(v || []).slice(0, 3).map((item) => <Tag key={item}>{item}</Tag>)}
                                                            {(v || []).length > 3 ? <Tag>+{(v || []).length - 3}</Tag> : null}
                                                        </div>
                                                    ),
                                                },
                                            ]}
                                        />
                                    )}
                                </Card>
                            </Space>
                        )}
                    </Card>
                </Col>
            </Row>
        </div>
    );
};

export default RuntimeExecutors;
