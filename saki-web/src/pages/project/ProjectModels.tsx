import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    AutoComplete,
    Button,
    Card,
    Descriptions,
    Drawer,
    Empty,
    Form,
    Input,
    Modal,
    Select,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import {ReloadOutlined} from '@ant-design/icons';
import {useParams, useSearchParams} from 'react-router-dom';

import {api} from '../../services/api';
import {Loop, ProjectModel, RuntimeRound} from '../../types';

const {Text} = Typography;

type StatusFilter = 'all' | 'candidate' | 'production' | 'archived';

const STATUS_COLOR: Record<string, string> = {
    candidate: 'processing',
    production: 'success',
    archived: 'default',
};

const formatDateTime = (value?: string | null): string => {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch {
        return String(value);
    }
};

const shortId = (value?: string | null): string => {
    const text = String(value || '').trim();
    if (!text) return '-';
    return `${text.slice(0, 8)}...`;
};

const ProjectModels: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>();
    const [searchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const [models, setModels] = useState<ProjectModel[]>([]);
    const [q, setQ] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [publishOpen, setPublishOpen] = useState(false);
    const [publishing, setPublishing] = useState(false);
    const [promotingId, setPromotingId] = useState<string | null>(null);
    const [downloadingId, setDownloadingId] = useState<string | null>(null);
    const [publishForm] = Form.useForm();
    const [detailOpen, setDetailOpen] = useState(false);
    const [detailModelId, setDetailModelId] = useState<string | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailModel, setDetailModel] = useState<ProjectModel | null>(null);
    const [roundOptions, setRoundOptions] = useState<Array<{ label: string; value: string }>>([]);

    const loadRoundOptions = useCallback(async () => {
        if (!projectId) return;
        try {
            const loopRows = await api.getProjectLoops(projectId);
            const roundLists = await Promise.all(
                loopRows.map(async (loop: Loop) => {
                    try {
                        return await api.getLoopRounds(loop.id, 200);
                    } catch {
                        return [] as RuntimeRound[];
                    }
                }),
            );
            const options: Array<{ label: string; value: string }> = [];
            roundLists.flat().forEach((row: RuntimeRound) => {
                if (String(row.state || '').toLowerCase() !== 'completed') return;
                options.push({
                    label: `Round #${row.roundIndex} / A${row.attemptIndex || 1} · ${row.id.slice(0, 8)} · ${row.pluginId}`,
                    value: row.id,
                });
            });
            const uniq = new Map<string, { label: string; value: string }>();
            options.forEach((item) => uniq.set(item.value, item));
            setRoundOptions(Array.from(uniq.values()));
        } catch {
            setRoundOptions([]);
        }
    }, [projectId]);

    const loadModels = useCallback(async () => {
        if (!projectId) return;
        setLoading(true);
        try {
            const rows = await api.getProjectModels(projectId, {
                limit: 300,
                status: statusFilter === 'all' ? undefined : statusFilter,
                q: q.trim() || undefined,
            });
            setModels(rows);
        } catch (error: any) {
            message.error(error?.message || '加载模型列表失败');
        } finally {
            setLoading(false);
        }
    }, [projectId, q, statusFilter]);

    const loadModelDetail = useCallback(async (modelId: string) => {
        setDetailLoading(true);
        try {
            const row = await api.getModel(modelId);
            setDetailModel(row);
        } catch (error: any) {
            message.error(error?.message || '加载模型详情失败');
            setDetailModel(null);
        } finally {
            setDetailLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadModels();
    }, [loadModels]);

    useEffect(() => {
        void loadRoundOptions();
    }, [loadRoundOptions]);

    useEffect(() => {
        const roundId = String(searchParams.get('roundId') || '').trim();
        if (!roundId) return;
        publishForm.setFieldsValue({
            roundId,
            primaryArtifactName: 'best.pt',
            status: 'candidate',
        });
        setPublishOpen(true);
    }, [publishForm, searchParams]);

    const onPublish = useCallback(async () => {
        if (!projectId) return;
        try {
            const values = await publishForm.validateFields();
            setPublishing(true);
            const created = await api.publishModelFromRound(projectId, {
                roundId: values.roundId,
                name: values.name || undefined,
                primaryArtifactName: values.primaryArtifactName || undefined,
                versionTag: values.versionTag || undefined,
                status: values.status || 'candidate',
            });
            message.success(`模型发布成功：${created.name}`);
            setPublishOpen(false);
            publishForm.resetFields();
            await loadModels();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || '发布模型失败');
        } finally {
            setPublishing(false);
        }
    }, [loadModels, projectId, publishForm]);

    const onPromote = useCallback(async (modelId: string) => {
        setPromotingId(modelId);
        try {
            await api.promoteModel(modelId, 'production');
            message.success('已晋升为 production');
            await loadModels();
        } catch (error: any) {
            message.error(error?.message || '晋升失败');
        } finally {
            setPromotingId(null);
        }
    }, [loadModels]);

    const onDownloadPrimary = useCallback(async (row: ProjectModel) => {
        const artifactName = String(row.primaryArtifactName || 'best.pt').trim() || 'best.pt';
        setDownloadingId(row.id);
        try {
            const payload = await api.getModelArtifactDownloadUrl(row.id, artifactName, 2);
            window.open(payload.downloadUrl, '_blank', 'noopener,noreferrer');
        } catch (error: any) {
            message.error(error?.message || '获取下载链接失败');
        } finally {
            setDownloadingId(null);
        }
    }, []);

    const detailArtifacts = useMemo(() => {
        const model = detailModel;
        if (!model || !model.artifacts || typeof model.artifacts !== 'object') return [];
        return Object.entries(model.artifacts).map(([name, payload]) => {
            const row = payload as any;
            return {
                name,
                kind: String(row?.kind || 'artifact'),
                uri: String(row?.uri || ''),
                meta: row?.meta && typeof row.meta === 'object' ? row.meta : {},
            };
        });
    }, [detailModel]);

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
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <Space wrap>
                        <Input.Search
                            allowClear
                            placeholder="按名称/插件/版本筛选"
                            value={q}
                            onChange={(event) => setQ(event.target.value)}
                            onSearch={() => void loadModels()}
                            style={{width: 280}}
                        />
                        <Select<StatusFilter>
                            value={statusFilter}
                            onChange={(value) => setStatusFilter(value)}
                            style={{width: 180}}
                            options={[
                                {label: '全部状态', value: 'all'},
                                {label: 'candidate', value: 'candidate'},
                                {label: 'production', value: 'production'},
                                {label: 'archived', value: 'archived'},
                            ]}
                        />
                    </Space>
                    <Space wrap>
                        <Button icon={<ReloadOutlined/>} onClick={() => void loadModels()}>
                            刷新
                        </Button>
                        <Button type="primary" onClick={() => setPublishOpen(true)}>
                            发布模型
                        </Button>
                    </Space>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title="模型中心">
                {models.length === 0 ? (
                    <Empty description="暂无模型"/>
                ) : (
                    <Table<ProjectModel>
                        rowKey={(row) => row.id}
                        dataSource={models}
                        pagination={{pageSize: 10, showSizeChanger: false}}
                        size="small"
                        columns={[
                            {title: '名称', dataIndex: 'name'},
                            {title: '版本', dataIndex: 'versionTag', width: 150},
                            {title: '插件', dataIndex: 'pluginId', width: 180},
                            {
                                title: '状态',
                                dataIndex: 'status',
                                width: 140,
                                render: (value: string) => <Tag color={STATUS_COLOR[value] || 'default'}>{value}</Tag>,
                            },
                            {
                                title: '来源 Round',
                                width: 140,
                                render: (_: unknown, row: ProjectModel) => (
                                    <Text code>{shortId(row.sourceRoundId)}</Text>
                                ),
                            },
                            {
                                title: '主制品',
                                width: 160,
                                render: (_: unknown, row: ProjectModel) => (
                                    <Text>{String(row.primaryArtifactName || '-')}</Text>
                                ),
                            },
                            {
                                title: '创建时间',
                                dataIndex: 'createdAt',
                                width: 180,
                                render: (value: string) => formatDateTime(value),
                            },
                            {
                                title: '操作',
                                width: 320,
                                render: (_: unknown, row: ProjectModel) => (
                                    <Space wrap>
                                        <Button
                                            size="small"
                                            onClick={() => {
                                                setDetailOpen(true);
                                                setDetailModelId(row.id);
                                                void loadModelDetail(row.id);
                                            }}
                                        >
                                            详情
                                        </Button>
                                        <Button
                                            size="small"
                                            loading={downloadingId === row.id}
                                            onClick={() => void onDownloadPrimary(row)}
                                        >
                                            下载主制品
                                        </Button>
                                        {row.status === 'candidate' ? (
                                            <Button
                                                size="small"
                                                type="primary"
                                                loading={promotingId === row.id}
                                                onClick={() => void onPromote(row.id)}
                                            >
                                                晋升 Production
                                            </Button>
                                        ) : null}
                                    </Space>
                                ),
                            },
                        ]}
                    />
                )}
            </Card>

            <Modal
                open={publishOpen}
                title="发布模型"
                onCancel={() => setPublishOpen(false)}
                onOk={() => void onPublish()}
                okText="发布"
                confirmLoading={publishing}
                destroyOnHidden
            >
                <Form
                    form={publishForm}
                    layout="vertical"
                    initialValues={{
                        primaryArtifactName: 'best.pt',
                        status: 'candidate',
                    }}
                >
                    <Form.Item
                        label="来源 Round"
                        name="roundId"
                        rules={[{required: true, message: '请选择来源 Round'}]}
                        extra="优先选择 completed Round，也支持手工输入 Round ID。"
                    >
                        <AutoComplete
                            showSearch
                            options={roundOptions}
                            placeholder="选择 completed round"
                            filterOption={(input, option) =>
                                String(option?.label || '').toLowerCase().includes(input.toLowerCase())
                            }
                        />
                    </Form.Item>
                    <Form.Item label="模型名称" name="name">
                        <Input placeholder="留空则自动生成"/>
                    </Form.Item>
                    <Form.Item label="主制品名" name="primaryArtifactName">
                        <Input placeholder="默认 best.pt"/>
                    </Form.Item>
                    <Form.Item label="版本号" name="versionTag" extra="留空按轮次自动生成（如 r3-a1）。">
                        <Input placeholder="例如 r3-a1"/>
                    </Form.Item>
                    <Form.Item label="发布状态" name="status">
                        <Select
                            options={[
                                {label: 'candidate', value: 'candidate'},
                                {label: 'production', value: 'production'},
                                {label: 'archived', value: 'archived'},
                            ]}
                        />
                    </Form.Item>
                </Form>
            </Modal>

            <Drawer
                open={detailOpen}
                onClose={() => {
                    setDetailOpen(false);
                    setDetailModelId(null);
                    setDetailModel(null);
                }}
                width={760}
                title={detailModel ? `模型详情 · ${detailModel.name}` : `模型详情 · ${shortId(detailModelId)}`}
            >
                {detailLoading ? (
                    <div className="flex min-h-[220px] items-center justify-center">
                        <Spin/>
                    </div>
                ) : !detailModel ? (
                    <Empty description="暂无详情数据"/>
                ) : (
                    <div className="flex flex-col gap-4">
                        <Descriptions size="small" column={1}>
                            <Descriptions.Item label="ID">{detailModel.id}</Descriptions.Item>
                            <Descriptions.Item label="状态">
                                <Tag color={STATUS_COLOR[detailModel.status] || 'default'}>{detailModel.status}</Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="插件">{detailModel.pluginId}</Descriptions.Item>
                            <Descriptions.Item label="来源 Round">{detailModel.sourceRoundId || '-'}</Descriptions.Item>
                            <Descriptions.Item label="来源 Step">{detailModel.sourceStepId || '-'}</Descriptions.Item>
                            <Descriptions.Item label="主制品">{detailModel.primaryArtifactName}</Descriptions.Item>
                            <Descriptions.Item label="创建时间">{formatDateTime(detailModel.createdAt)}</Descriptions.Item>
                        </Descriptions>

                        <Card size="small" title="Metrics">
                            <pre className="m-0 whitespace-pre-wrap break-all text-xs">
                                {JSON.stringify(detailModel.metrics || {}, null, 2)}
                            </pre>
                        </Card>

                        <Card size="small" title="Artifacts">
                            <Table
                                rowKey={(row: any) => row.name}
                                size="small"
                                pagination={false}
                                dataSource={detailArtifacts}
                                columns={[
                                    {title: '名称', dataIndex: 'name'},
                                    {title: '类型', dataIndex: 'kind', width: 160},
                                    {
                                        title: 'URI',
                                        dataIndex: 'uri',
                                        render: (value: string) => (
                                            <Text className="break-all" copyable>{value || '-'}</Text>
                                        ),
                                    },
                                ]}
                            />
                        </Card>
                    </div>
                )}
            </Drawer>
        </div>
    );
};

export default ProjectModels;
