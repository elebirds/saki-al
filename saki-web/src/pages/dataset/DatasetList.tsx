import React, {useCallback, useMemo, useState} from 'react';
import {Button, Card, Form, Input, message, Modal, Select, Tag, Tooltip, Typography} from 'antd';
import {useNavigate} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {Dataset} from '../../types';
import {api} from '../../services/api';
import {usePermission, useSystemCapabilities} from '../../hooks';
import {DatabaseOutlined, PlusOutlined} from '@ant-design/icons';
import {PaginatedList} from '../../components/common/PaginatedList';

const {Paragraph, Title} = Typography;
const {Option} = Select;

const DatasetList: React.FC = () => {
    const {t} = useTranslation();
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const [showNoMore, setShowNoMore] = useState(false);
    const [form] = Form.useForm();
    const navigate = useNavigate();

    // Permission hook
    const {can} = usePermission();
    const canCreate = can('dataset:create');

    // Load available types from backend
    const {getDatasetTypeLabel, getDatasetTypeColor, availableTypes} = useSystemCapabilities();

    const fetchDatasets = useCallback(async (page: number, pageSize: number) => {
        try {
            return await api.getDatasets(page, pageSize);
        } catch (error) {
            message.error(t('dataset.list.loadError'));
            throw error;
        }
    }, [t]);

    const handleCreate = async (values: any) => {
        try {
            await api.createDataset(values);
            message.success(t('dataset.list.createSuccess'));
            setIsModalVisible(false);
            form.resetFields();
            setRefreshKey((v) => v + 1);
        } catch (error) {
            message.error(t('dataset.list.createError'));
        }
    };

    const renderDatasets = useCallback((items: Dataset[], _loading?: boolean) => (
        <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
                {items.map((dataset) => (
                    <div key={dataset.id} className="min-w-0">
                        <Card
                            hoverable
                            title={
                                <div className="flex items-center gap-2 min-w-0">
                                    <DatabaseOutlined/>
                                    <span className="truncate">{dataset.name}</span>
                                </div>
                            }
                            extra={
                                <Tag color={getDatasetTypeColor(dataset.type)}>
                                    {getDatasetTypeLabel(dataset.type)}
                                </Tag>
                            }
                            actions={[
                                <Button type="link" onClick={() => navigate(`/datasets/${dataset.id}`)}>
                                    {t('dataset.list.open')}
                                </Button>,
                            ]}
                        >
                            <Paragraph ellipsis={{rows: 2}} className="min-h-[44px]">
                                {dataset.description || t('dataset.list.noDescription')}
                            </Paragraph>
                        </Card>
                    </div>
                ))}
            </div>
            {showNoMore ? (
                <div className="mt-4 text-sm text-github-muted text-center">{t('dataset.list.noMore')}</div>
            ) : null}
        </>
    ), [getDatasetTypeColor, getDatasetTypeLabel, navigate, t, showNoMore]);

    const emptyFallback = useMemo(() => (
        <Card>
            <div className="p-10 text-center">
                <DatabaseOutlined className="mb-4 text-[48px] text-gray-300"/>
                <Title level={4} className="!text-gray-500">{t('dataset.list.empty')}</Title>
                <Paragraph className="!text-gray-500">{t('dataset.list.emptyHint')}</Paragraph>
                {canCreate && (
                    <Button type="primary" icon={<PlusOutlined/>} onClick={() => setIsModalVisible(true)}>
                        {t('dataset.list.newDataset')}
                    </Button>
                )}
            </div>
        </Card>
    ), [canCreate, t]);

    return (
        <div className="h-full flex flex-col">
            <div className="flex items-center justify-between mb-6 flex-shrink-0">
                <span className="m-0 font-semibold">{t('dataset.list.title')}</span>
                {canCreate ? (
                    <Button type="primary" icon={<PlusOutlined/>} onClick={() => setIsModalVisible(true)}>
                        {t('dataset.list.newDataset')}
                    </Button>
                ) : (
                    <Tooltip title={t('common.noPermission')}>
                        <Button type="primary" icon={<PlusOutlined/>} disabled>
                            {t('dataset.list.newDataset')}
                        </Button>
                    </Tooltip>
                )}
            </div>

            <div className="flex-1 min-h-0">
                <PaginatedList<Dataset>
                    fetchData={fetchDatasets}
                    renderItems={(items, loading) => renderDatasets(items, loading)}
                    emptyFallback={emptyFallback}
                    refreshKey={refreshKey}
                    resetPageOnRefresh
                    initialPageSize={8}
                    pageSizeOptions={['8', '12', '20', '32', '50']}
                    adaptivePageSize={{
                        enabled: true,
                        mode: 'grid',
                        itemMinWidth: 240,
                        itemHeight: 220,
                        rowGap: 16,
                        colGap: 16,
                    }}
                    paginationProps={{
                        showTotal: (tot, range) => range ? `${range[0]}-${range[1]} ${t('common.of')} ${tot} ${t('common.items')}` : `${tot} ${t('common.items')}`,
                    }}
                    onMetaChange={(meta) => {
                        if (meta.total > 0) {
                            setShowNoMore(meta.offset + meta.size >= meta.total);
                        } else {
                            setShowNoMore(false);
                        }
                    }}
                    onError={() => message.error(t('dataset.list.loadError'))}
                    renderPaginationWrapper={(node) => (
                        <div className="mt-auto flex justify-end pt-4">{node}</div>
                    )}
                />
            </div>

            <Modal
                title={t('dataset.list.newDataset')}
                open={isModalVisible}
                onCancel={() => setIsModalVisible(false)}
                onOk={() => form.submit()}
            >
                <Form
                    form={form}
                    layout="vertical"
                    onFinish={handleCreate}
                    initialValues={{type: 'classic'}}
                >
                    <Form.Item
                        name="name"
                        label={t('dataset.list.datasetName')}
                        rules={[{required: true, message: t('dataset.list.nameRequired')}]}
                    >
                        <Input placeholder={t('dataset.list.namePlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="description" label={t('dataset.list.description')}>
                        <Input.TextArea placeholder={t('dataset.list.descriptionPlaceholder')} rows={3}/>
                    </Form.Item>
                    <Form.Item
                        name="type"
                        label={
                            <span>
                  {t('dataset.list.type')}&nbsp;
                                <Tooltip title={t('dataset.list.typeHelp')}>
                    <span className="cursor-help text-gray-500">ⓘ</span>
                  </Tooltip>
                </span>
                        }
                        rules={[{required: true}]}
                    >
                        <Select>
                            {availableTypes?.datasetTypes.map(system => (
                                <Option key={system.value} value={system.value}>
                                    <Tooltip title={system.description} placement="right">
                                        {system.label}
                                    </Tooltip>
                                </Option>
                            ))}
                        </Select>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default DatasetList;
