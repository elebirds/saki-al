import React, {useCallback, useMemo, useState} from 'react';
import {Button, Card, Form, Input, message, Modal, Select, Switch, Tag, Tooltip, Typography} from 'antd';
import {useNavigate} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {Dataset} from '../../types';
import {api} from '../../services/api';
import {usePermission, useSystemCapabilities} from '../../hooks';
import {DatabaseOutlined, PlusOutlined} from '@ant-design/icons';
import {PaginatedList} from '../../components/common/PaginatedList';

const {Paragraph, Title, Text} = Typography;
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

    const formatRelativeTime = useCallback((value?: string) => {
        if (!value) return t('common.placeholder');
        const date = new Date(value);
        const diffMs = Date.now() - date.getTime();
        const minutes = Math.floor(diffMs / 60000);
        if (minutes < 1) return t('common.time.justNow');
        if (minutes < 60) return t('common.time.minutesAgo', {count: minutes});
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return t('common.time.hoursAgo', {count: hours});
        const days = Math.floor(hours / 24);
        if (days < 7) return t('common.time.daysAgo', {count: days});
        const weeks = Math.floor(days / 7);
        if (weeks < 5) return t('common.time.weeksAgo', {count: weeks});
        const months = Math.floor(days / 30);
        return t('common.time.monthsAgo', {count: months});
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
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {items.map((dataset) => (
                    <div key={dataset.id} className="min-w-0">
                        <Card
                            className="!border-github-border !bg-github-panel hover:!border-github-border-muted"
                            onClick={() => navigate(`/datasets/${dataset.id}`)}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-4">
                                <div>
                                    <div className="text-base font-semibold text-github-text">{dataset.name}</div>
                                    <Text type="secondary" className="text-sm">
                                        {dataset.description || t('dataset.list.noDescription')}
                                    </Text>
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <Tag color={getDatasetTypeColor(dataset.type)}>
                                        {getDatasetTypeLabel(dataset.type)}
                                    </Tag>
                                    <Tag color={dataset.isPublic ? 'blue' : 'default'}>
                                        {dataset.isPublic ? t('dataset.visibility.public') : t('dataset.visibility.private')}
                                    </Tag>
                                </div>
                            </div>
                            <div className="mt-4 grid grid-cols-2 gap-4 text-xs text-github-muted sm:grid-cols-4">
                                <div>
                                    <div className="text-github-text font-semibold">{getDatasetTypeLabel(dataset.type)}</div>
                                    <div>{t('dataset.list.type')}</div>
                                </div>
                                <div>
                                    <div className="text-github-text font-semibold">
                                        {dataset.isPublic ? t('dataset.visibility.public') : t('dataset.visibility.private')}
                                    </div>
                                    <div>{t('dataset.list.visibility')}</div>
                                </div>
                                <div>
                                    <div className="text-github-text font-semibold">{formatRelativeTime(dataset.createdAt)}</div>
                                    <div>{t('user.profile.createdAt')}</div>
                                </div>
                                <div>
                                    <div className="text-github-text font-semibold">{formatRelativeTime(dataset.updatedAt)}</div>
                                    <div>{t('user.profile.updatedAt')}</div>
                                </div>
                            </div>
                        </Card>
                    </div>
                ))}
            </div>
            {showNoMore ? (
                <div className="mt-4 text-sm text-github-muted text-center">{t('dataset.list.noMore')}</div>
            ) : null}
        </>
    ), [formatRelativeTime, getDatasetTypeColor, getDatasetTypeLabel, navigate, t, showNoMore]);

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
                        mode: 'list',
                        itemHeight: 170,
                        rowGap: 16,
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
                    initialValues={{type: 'classic', isPublic: false}}
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
                    <Form.Item
                        name="isPublic"
                        label={t('dataset.list.visibility')}
                        valuePropName="checked"
                        extra={t('dataset.list.visibilityHelp')}
                    >
                        <Switch
                            checkedChildren={t('dataset.visibility.public')}
                            unCheckedChildren={t('dataset.visibility.private')}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default DatasetList;
