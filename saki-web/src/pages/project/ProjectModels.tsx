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
import {useTranslation} from 'react-i18next';
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
    const {t} = useTranslation();
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
            message.error(error?.message || t('project.models.messages.loadListFailed'));
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
            message.error(error?.message || t('project.models.messages.loadDetailFailed'));
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

    useEffect(() => {
        const modelId = String(searchParams.get('modelId') || '').trim();
        if (!modelId) return;
        setDetailOpen(true);
        setDetailModelId(modelId);
        void loadModelDetail(modelId);
    }, [loadModelDetail, searchParams]);

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
            message.success(t('project.models.messages.publishSuccess', {name: created.name}));
            setPublishOpen(false);
            publishForm.resetFields();
            await loadModels();
        } catch (error: any) {
            if (error?.errorFields) return;
            message.error(error?.message || t('project.models.messages.publishFailed'));
        } finally {
            setPublishing(false);
        }
    }, [loadModels, projectId, publishForm]);

    const onPromote = useCallback(async (modelId: string) => {
        setPromotingId(modelId);
        try {
            await api.promoteModel(modelId, 'production');
            message.success(t('project.models.messages.promoteSuccess'));
            await loadModels();
        } catch (error: any) {
            message.error(error?.message || t('project.models.messages.promoteFailed'));
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
            message.error(error?.message || t('project.models.messages.getDownloadUrlFailed'));
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
                            placeholder={t('project.models.searchPlaceholder')}
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
                                {label: t('project.models.allStatus'), value: 'all'},
                                {label: 'candidate', value: 'candidate'},
                                {label: 'production', value: 'production'},
                                {label: 'archived', value: 'archived'},
                            ]}
                        />
                    </Space>
                    <Space wrap>
                        <Button icon={<ReloadOutlined/>} onClick={() => void loadModels()}>
                            {t('project.models.refresh')}
                        </Button>
                        <Button type="primary" onClick={() => setPublishOpen(true)}>
                            {t('project.models.publishModel')}
                        </Button>
                    </Space>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel" title={t('project.models.title')}>
                {models.length === 0 ? (
                    <Empty description={t('project.models.empty')}/>
                ) : (
                    <Table<ProjectModel>
                        rowKey={(row) => row.id}
                        dataSource={models}
                        pagination={{pageSize: 10, showSizeChanger: false}}
                        size="small"
                        columns={[
                            {title: t('project.models.table.name'), dataIndex: 'name'},
                            {title: t('project.models.table.version'), dataIndex: 'versionTag', width: 150},
                            {title: t('project.models.table.plugin'), dataIndex: 'pluginId', width: 180},
                            {
                                title: t('project.models.table.status'),
                                dataIndex: 'status',
                                width: 140,
                                render: (value: string) => <Tag color={STATUS_COLOR[value] || 'default'}>{value}</Tag>,
                            },
                            {
                                title: t('project.models.table.sourceRound'),
                                width: 140,
                                render: (_: unknown, row: ProjectModel) => (
                                    <Text code>{shortId(row.sourceRoundId)}</Text>
                                ),
                            },
                            {
                                title: t('project.models.table.primaryArtifact'),
                                width: 160,
                                render: (_: unknown, row: ProjectModel) => (
                                    <Text>{String(row.primaryArtifactName || '-')}</Text>
                                ),
                            },
                            {
                                title: t('project.models.table.createdAt'),
                                dataIndex: 'createdAt',
                                width: 180,
                                render: (value: string) => formatDateTime(value),
                            },
                            {
                                title: t('project.models.table.actions'),
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
                                            {t('project.models.actions.detail')}
                                        </Button>
                                        <Button
                                            size="small"
                                            loading={downloadingId === row.id}
                                            onClick={() => void onDownloadPrimary(row)}
                                        >
                                            {t('project.models.actions.downloadPrimary')}
                                        </Button>
                                        {row.status === 'candidate' ? (
                                            <Button
                                                size="small"
                                                type="primary"
                                                loading={promotingId === row.id}
                                                onClick={() => void onPromote(row.id)}
                                            >
                                                {t('project.models.actions.promoteProduction')}
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
                title={t('project.models.publishModal.title')}
                onCancel={() => setPublishOpen(false)}
                onOk={() => void onPublish()}
                okText={t('project.models.publishModal.okText')}
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
                        label={t('project.models.table.sourceRound')}
                        name="roundId"
                        rules={[{required: true, message: t('project.models.publishModal.sourceRoundRequired')}]}
                        extra={t('project.models.publishModal.sourceRoundExtra')}
                    >
                        <AutoComplete
                            showSearch
                            options={roundOptions}
                            placeholder={t('project.models.publishModal.sourceRoundPlaceholder')}
                            filterOption={(input, option) =>
                                String(option?.label || '').toLowerCase().includes(input.toLowerCase())
                            }
                        />
                    </Form.Item>
                    <Form.Item label={t('project.models.publishModal.modelName')} name="name">
                        <Input placeholder={t('project.models.publishModal.modelNamePlaceholder')}/>
                    </Form.Item>
                    <Form.Item label={t('project.models.publishModal.primaryArtifactName')} name="primaryArtifactName">
                        <Input placeholder={t('project.models.publishModal.primaryArtifactNamePlaceholder')}/>
                    </Form.Item>
                    <Form.Item label={t('project.models.publishModal.versionTag')} name="versionTag" extra={t('project.models.publishModal.versionTagExtra')}>
                        <Input placeholder={t('project.models.publishModal.versionTagPlaceholder')}/>
                    </Form.Item>
                    <Form.Item label={t('project.models.publishModal.status')} name="status">
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
                title={detailModel
                    ? t('project.models.detailDrawer.titleWithName', {name: detailModel.name})
                    : t('project.models.detailDrawer.titleWithId', {id: shortId(detailModelId)})}
            >
                {detailLoading ? (
                    <div className="flex min-h-[220px] items-center justify-center">
                        <Spin/>
                    </div>
                ) : !detailModel ? (
                    <Empty description={t('project.models.detailDrawer.empty')}/>
                ) : (
                    <div className="flex flex-col gap-4">
                        <Descriptions size="small" column={1}>
                            <Descriptions.Item label="ID">{detailModel.id}</Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.status')}>
                                <Tag color={STATUS_COLOR[detailModel.status] || 'default'}>{detailModel.status}</Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.plugin')}>{detailModel.pluginId}</Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.sourceRound')}>{detailModel.sourceRoundId || '-'}</Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.sourceTask')}>{detailModel.sourceTaskId || '-'}</Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.primaryArtifact')}>{detailModel.primaryArtifactName}</Descriptions.Item>
                            <Descriptions.Item label={t('project.models.detailDrawer.labels.createdAt')}>{formatDateTime(detailModel.createdAt)}</Descriptions.Item>
                        </Descriptions>

                        <Card size="small" title={t('project.models.detailDrawer.metrics')}>
                            <pre className="m-0 whitespace-pre-wrap break-all text-xs">
                                {JSON.stringify(detailModel.metrics || {}, null, 2)}
                            </pre>
                        </Card>

                        <Card size="small" title={t('project.models.detailDrawer.artifacts')}>
                            <Table
                                rowKey={(row: any) => row.name}
                                size="small"
                                pagination={false}
                                dataSource={detailArtifacts}
                                columns={[
                                    {title: t('project.models.detailDrawer.table.name'), dataIndex: 'name'},
                                    {title: t('project.models.detailDrawer.table.type'), dataIndex: 'kind', width: 160},
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
