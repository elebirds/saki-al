import React, {useCallback, useEffect, useRef, useState} from 'react';
import {useNavigate, useParams} from 'react-router-dom';
import {Button, Card, Input, List, message, Popconfirm, Select, Tabs, Tag, Tooltip, Typography} from 'antd';
import {useTranslation} from 'react-i18next';
import {Dataset, Sample} from '../../types';
import {api} from '../../services/api';
import {
    ArrowLeftOutlined,
    DeleteOutlined,
    FileTextOutlined,
    SettingOutlined,
    SortAscendingOutlined,
    SortDescendingOutlined,
    UploadOutlined
} from '@ant-design/icons';
import DatasetSettings from '../../components/settings/DatasetSettings';
import SampleAssetModal from '../../components/dataset/SampleAssetModal';
import {useResourcePermission, useSystemCapabilities} from '../../hooks';
import {PaginatedList} from '../../components/common/PaginatedList';

const {Title} = Typography;
const {Option} = Select;

const DatasetDetail: React.FC = () => {
    const {t} = useTranslation();
    const {id} = useParams<{ id: string }>();
    const navigate = useNavigate();
    const [dataset, setDataset] = useState<Dataset | null>(null);
    const [sampleMeta, setSampleMeta] = useState({total: 0, limit: 8, offset: 0, size: 0});
    const [sampleRefreshKey, setSampleRefreshKey] = useState(0);
    const [activeTab, setActiveTab] = useState('data');
    const [sortBy, setSortBy] = useState<string>('createdAt');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [searchQuery, setSearchQuery] = useState('');
    const [searchInput, setSearchInput] = useState('');
    const [selectedSample, setSelectedSample] = useState<Sample | null>(null);
    const [assetModalOpen, setAssetModalOpen] = useState(false);

    // Use refs to store latest sort params
    const sortByRef = useRef(sortBy);
    const sortOrderRef = useRef(sortOrder);
    const searchQueryRef = useRef(searchQuery);

    useEffect(() => {
        sortByRef.current = sortBy;
        sortOrderRef.current = sortOrder;
        searchQueryRef.current = searchQuery;
    }, [sortBy, sortOrder, searchQuery]);

    // Permission hook
    const {can, role, isOwner} = useResourcePermission('dataset', id);

    // System capabilities
    const {getDatasetTypeLabel, getDatasetTypeColor} = useSystemCapabilities();

    // Load dataset
    const loadDataset = useCallback(async (datasetId: string) => {
        try {
            const d = await api.getDataset(datasetId);
            if (d) setDataset(d);
        } catch (error) {
            console.error('Failed to load dataset:', error);
            message.error(t('dataset.detail.loadError'));
        }
    }, [t]);

    // Load samples
    const fetchSamples = useCallback(async (page: number, pageSize: number) => {
        if (!id) throw new Error('Dataset id is required');
        try {
            return await api.getSamples(
                id,
                page,
                pageSize,
                sortByRef.current,
                sortOrderRef.current,
                searchQueryRef.current || undefined,
            );
        } catch (error) {
            console.error('Failed to load samples:', error);
            message.error(t('dataset.detail.loadSamplesError'));
            throw error;
        }
    }, [id, t]);

    // Load dataset and samples
    useEffect(() => {
        if (id) {
            setSearchQuery('');
            setSearchInput('');
            loadDataset(id);
            setSampleRefreshKey((v) => v + 1);
        }
    }, [id, loadDataset]);

    // Reload samples when sort settings change
    const isInitialMountRef = useRef(true);
    useEffect(() => {
        if (isInitialMountRef.current) {
            isInitialMountRef.current = false;
            return;
        }
        if (id) {
            setSampleRefreshKey((v) => v + 1);
        }
    }, [sortBy, sortOrder, searchQuery, id]);

    const handleSearch = useCallback((value: string) => {
        setSearchQuery(value.trim());
    }, []);

    const handleOpenImportWorkspace = () => {
        if (!dataset) return;
        navigate(`/datasets/${dataset.id}/import`);
    };

    const handleDeleteSample = async (sample: Sample) => {
        if (!dataset) return;
        try {
            await api.deleteSample(dataset.id, sample.id);
            message.success(t('dataset.detail.deleteSampleSuccess'));
            setSampleRefreshKey((v) => v + 1);
            loadDataset(dataset.id);
        } catch (error) {
            message.error(t('dataset.detail.deleteSampleError'));
        }
    };

    if (!dataset) return <div>{t('common.loading')}</div>;

    // Render sample item
    const renderSampleItem = (item: Sample) => {
        const handleSampleClick = () => {
            // Open asset modal instead of navigating to workspace
            setSelectedSample(item);
            setAssetModalOpen(true);
        };

        const canDelete = can('sample:delete');

        return (
            <Card
                hoverable
                onClick={handleSampleClick}
                className="cursor-pointer"
                cover={
                    <img
                        alt={t('common.sample')}
                        src={item.primaryAssetUrl}
                        className="h-[150px] w-full object-cover"
                        onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                            e.currentTarget.style.display = 'none';
                        }}
                    />
                }
                size="small"
                actions={[
                    canDelete ? (
                        <Popconfirm
                            title={t('dataset.detail.deleteSampleConfirm')}
                            onConfirm={(e) => {
                                e?.stopPropagation();
                                handleDeleteSample(item);
                            }}
                            onCancel={(e) => e?.stopPropagation()}
                            okText={t('common.yes')}
                            cancelText={t('common.no')}
                        >
                            <DeleteOutlined
                                key="delete"
                                onClick={(e) => e.stopPropagation()}
                                className="text-red-500"
                            />
                        </Popconfirm>
                    ) : (
                        <Tooltip title={t('common.noPermission')}>
                            <DeleteOutlined key="delete" className="cursor-not-allowed text-gray-300"/>
                        </Tooltip>
                    ),
                ]}
            >
                <Card.Meta
                    title={
                        <span className="block truncate">
              {item.name}
            </span>
                    }
                    description={item.remark && <span className="text-xs text-gray-500">{item.remark}</span>}
                />
            </Card>
        );
    };

    // Calculate completion stats (mock for now)
    const totalSamples = sampleMeta.total;
    const totalSamplePages = Math.max(1, Math.ceil(sampleMeta.total / (sampleMeta.limit || 1)));
    // Check permissions for various actions
    const canUpload = can('sample:create');
    const canEdit = can('dataset:update');

    const items = [
        {
            key: 'data',
            label: t('dataset.detail.dataPool'),
            children: (
                <div className="flex min-h-0 flex-col">
                    <div className="mb-4 flex flex-shrink-0 items-center justify-between gap-3">
                        <Title level={5} className="!m-0">{t('dataset.detail.dataPool')} ({totalSamples})</Title>
                        <div className="flex flex-nowrap items-center gap-2">
                            <Input.Search
                                allowClear
                                value={searchInput}
                                placeholder={t('dataset.detail.searchByNamePlaceholder')}
                                onSearch={handleSearch}
                                onChange={(e) => {
                                    const nextValue = e.target.value;
                                    setSearchInput(nextValue);
                                    if (!nextValue) {
                                        handleSearch('');
                                    }
                                }}
                                className="w-[220px]"
                                size="small"
                            />
                            <Select
                                value={sortBy}
                                onChange={setSortBy}
                                className="w-[140px]"
                                size="small"
                            >
                                <Option value="name">{t('dataset.detail.sortByName')}</Option>
                                <Option value="createdAt">{t('dataset.detail.sortByCreatedAt')}</Option>
                                <Option value="updatedAt">{t('dataset.detail.sortByUpdatedAt')}</Option>
                            </Select>
                            <Button
                                icon={sortOrder === 'asc' ? <SortAscendingOutlined/> : <SortDescendingOutlined/>}
                                onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                                size="small"
                            >
                                {sortOrder === 'asc' ? t('dataset.detail.sortAsc') : t('dataset.detail.sortDesc')}
                            </Button>
                        </div>
                    </div>
                    <div className="flex-1 min-h-0 pr-2.5">
                        <PaginatedList<Sample>
                            fetchData={fetchSamples}
                            initialPageSize={8}
                            pageSizeOptions={['8', '12', '20', '32', '50']}
                            adaptivePageSize={{
                                enabled: true,
                                mode: 'grid',
                                itemMinWidth: 260,
                                itemHeight: 250,
                                rowGap: 16,
                                colGap: 16,
                            }}
                            refreshKey={`${id}-${sortBy}-${sortOrder}-${searchQuery}-${sampleRefreshKey}`}
                            resetPageOnRefresh
                            onMetaChange={(meta) => setSampleMeta(meta)}
                            renderItems={(items) => (
                                items.length === 0 ? (
                                    <Card>
                                        <div className="p-10 text-center">
                                            <FileTextOutlined className="mb-4 text-[48px] text-gray-300"/>
                                            <Title level={5}
                                                   className="!text-gray-500">{t('dataset.detail.noSamples')}</Title>
                                            {canUpload ? (
                                                <Button type="primary" icon={<UploadOutlined/>}
                                                        onClick={handleOpenImportWorkspace}>
                                                    {t('dataset.detail.openImportWorkspace')}
                                                </Button>
                                            ) : (
                                                <Tooltip title={t('common.noPermission')}>
                                                    <Button type="primary" icon={<UploadOutlined/>} disabled>
                                                        {t('dataset.detail.openImportWorkspace')}
                                                    </Button>
                                                </Tooltip>
                                            )}
                                        </div>
                                    </Card>
                                ) : (
                                    <List
                                        grid={{
                                            gutter: 16,
                                            xs: 1,
                                            sm: 2,
                                            md: 2,
                                            lg: 3,
                                            xl: 4,
                                            xxl: 4,
                                        }}
                                        dataSource={items}
                                        renderItem={(item) => (
                                            <List.Item>
                                                {renderSampleItem(item)}
                                            </List.Item>
                                        )}
                                    />
                                )
                            )}
                            renderPaginationWrapper={(node) => (
                                <div className="mt-4 flex items-center justify-between">
                  <span className="text-xs text-gray-600">
                    {t('dataset.detail.pageStatus', {
                        defaultValue: 'Page {{page}} / {{pages}} · {{total}} items',
                        page: Math.floor(sampleMeta.offset / (sampleMeta.limit || 1)) + 1,
                        pages: totalSamplePages,
                        total: totalSamples,
                    })}
                  </span>
                                    {node}
                                </div>
                            )}
                            paginationProps={{
                                showTotal: (tot, range) => range ? `${range[0]}-${range[1]} ${t('common.of')} ${tot} ${t('common.items')}` : `${tot} ${t('common.items')}`,
                            }}
                        />
                    </div>
                </div>
            ),
        },
        ...(canEdit ? [{
            key: 'settings',
            label: t('dataset.detail.settings'),
            children: (
                <div className="pr-2.5">
                    <DatasetSettings
                        dataset={dataset}
                        onUpdate={(updatedDataset: Dataset) => setDataset(updatedDataset)}
                    />
                </div>
            ),
        }] : []),
    ];

    return (
        <div className="flex h-full bg-transparent">
            <aside className="w-1/5 shrink-0 border-r border-github-border p-5">
                <Button
                    type="text"
                    icon={<ArrowLeftOutlined/>}
                    onClick={() => navigate('/')}
                    className="mb-4"
                >
                    {t('dataset.detail.backToList')}
                </Button>

                <Title level={4}>{dataset.name}</Title>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Tag color={getDatasetTypeColor(dataset.type)}>
                        {getDatasetTypeLabel(dataset.type)}
                    </Tag>
                    {isOwner && <Tag color="gold">{t('common.owner')}</Tag>}
                    {role && !isOwner && <Tag>{role.displayName}</Tag>}
                </div>
                {dataset.description && (
                    <div className="mb-4 text-xs text-gray-600">{dataset.description}</div>
                )}

                <div className="flex w-full flex-col gap-6">
                    {canUpload ? (
                        <Button block icon={<UploadOutlined/>} onClick={handleOpenImportWorkspace}>
                            {t('dataset.detail.openImportWorkspace')}
                        </Button>
                    ) : (
                        <Tooltip title={t('common.noPermission')}>
                            <Button block icon={<UploadOutlined/>} disabled>
                                {t('dataset.detail.openImportWorkspace')}
                            </Button>
                        </Tooltip>
                    )}

                    {canEdit && (
                        <Button block icon={<SettingOutlined/>} onClick={() => setActiveTab('settings')}>
                            {t('dataset.detail.settings')}
                        </Button>
                    )}
                </div>
            </aside>
            <main className="h-full w-4/5 min-w-0 bg-transparent p-6">
                <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} className="full-height-tabs"/>

                {/* Sample Asset Modal */}
                <SampleAssetModal
                    open={assetModalOpen}
                    sample={selectedSample}
                    onClose={() => {
                        setAssetModalOpen(false);
                        setSelectedSample(null);
                    }}
                />
            </main>
        </div>
    );
};

export default DatasetDetail;
