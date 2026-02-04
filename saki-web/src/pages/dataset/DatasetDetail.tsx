import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Typography, Space, Card, List, Tag, Tabs, message, Select, Tooltip, Popconfirm } from 'antd';
import { useTranslation } from 'react-i18next';
import { Dataset, Sample } from '../../types';
import { api } from '../../services/api';
import { UploadOutlined, SettingOutlined, FileTextOutlined, ArrowLeftOutlined, SortAscendingOutlined, SortDescendingOutlined, DeleteOutlined } from '@ant-design/icons';
import UploadProgressModal from '../../components/UploadProgressModal';
import DatasetSettings from '../../components/settings/DatasetSettings';
import SampleAssetModal from '../../components/dataset/SampleAssetModal';
import { useUpload, useSystemCapabilities, useResourcePermission } from '../../hooks';
import { PaginatedList } from '../../components/common/PaginatedList';

const { Title } = Typography;
const { Sider, Content } = Layout;
const { Option } = Select;

const DatasetDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [sampleMeta, setSampleMeta] = useState({ total: 0, limit: 8, offset: 0, size: 0 });
  const [sampleRefreshKey, setSampleRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState('data');
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sortBy, setSortBy] = useState<string>('createdAt');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [selectedSample, setSelectedSample] = useState<Sample | null>(null);
  const [assetModalOpen, setAssetModalOpen] = useState(false);
  
  // Use refs to store latest sort params
  const sortByRef = useRef(sortBy);
  const sortOrderRef = useRef(sortOrder);
  
  useEffect(() => {
    sortByRef.current = sortBy;
    sortOrderRef.current = sortOrder;
  }, [sortBy, sortOrder]);
  
  // Permission hook
  const { can, role, isOwner } = useResourcePermission('dataset', id);
  
  // System capabilities
  const { getDatasetTypeLabel, getDatasetTypeColor } = useSystemCapabilities();

  // Initialize upload hook
  const { progress, upload, cancel, reset, isUploading } = useUpload(id || '', {
    onFileComplete: (result) => {
      if (result.status === 'success') {
        console.log(`File uploaded: ${result.filename}`);
      }
    },
    onComplete: (result) => {
      message.success(t('upload.completeMessage', { 
        success: result.uploaded, 
        total: result.uploaded + result.errors 
      }));
      // Refresh samples after upload
      if (id) {
        setSampleRefreshKey((v) => v + 1);
        loadDataset(id);
      }
    },
    onError: (error) => {
      message.error(error);
    },
  });

  // Load dataset
  const loadDataset = useCallback(async (datasetId: string) => {
    try {
      const d = await api.getDataset(datasetId);
      if (d) setDataset(d);
    } catch (error) {
      console.error('Failed to load dataset:', error);
      message.error(t('datasetDetail.loadError'));
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
      );
    } catch (error) {
      console.error('Failed to load samples:', error);
      message.error(t('datasetDetail.loadSamplesError'));
      throw error;
    }
  }, [id, t]);

  // Load dataset and samples
  useEffect(() => {
    if (id) {
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
  }, [sortBy, sortOrder, id]);

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!dataset || !e.target.files || e.target.files.length === 0) return;
    
    reset();
    setUploadModalOpen(true);
    await upload(Array.from(e.target.files));
    
    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleUploadModalClose = () => {
    if (!isUploading) {
      setUploadModalOpen(false);
      reset();
    }
  };

  const handleUploadCancel = () => {
    cancel();
  };

  const handleDeleteSample = async (sample: Sample) => {
    if (!dataset) return;
    try {
      await api.deleteSample(dataset.id, sample.id);
      message.success(t('datasetDetail.deleteSampleSuccess'));
      setSampleRefreshKey((v) => v + 1);
      loadDataset(dataset.id);
    } catch (error) {
      message.error(t('datasetDetail.deleteSampleError'));
    }
  };

  if (!dataset) return <div>{t('common.loading')}</div>;

  // Determine file accept type based on dataset type
  const getAcceptType = () => {
    switch (dataset.type) {
      case 'fedo':
        return '.txt';
      case 'classic':
      default:
        return 'image/*';
    }
  };

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
        style={{ cursor: 'pointer' }}
        cover={
            <img 
              alt="sample" 
              src={item.primaryAssetUrl}
              style={{ height: 150, objectFit: 'cover' }}
              onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                e.currentTarget.style.display = 'none';
              }}
            />
        }
        size="small"
        actions={[
          canDelete ? (
            <Popconfirm
              title={t('datasetDetail.deleteSampleConfirm')}
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
                style={{ color: '#ff4d4f' }}
              />
            </Popconfirm>
          ) : (
            <Tooltip title={t('common.noPermission')}>
              <DeleteOutlined key="delete" style={{ color: '#ccc', cursor: 'not-allowed' }} />
            </Tooltip>
          ),
        ]}
      >
        <Card.Meta 
          title={
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {item.name}
            </span>
          }
          description={item.remark && <span style={{ fontSize: '12px', color: '#999' }}>{item.remark}</span>}
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
      label: t('datasetDetail.dataPool'),
      children: (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div style={{ flexShrink: 0, marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Title level={5} style={{ margin: 0 }}>{t('datasetDetail.dataPool')} ({totalSamples})</Title>
            <Space>
              <Select
                value={sortBy}
                onChange={setSortBy}
                style={{ width: 140 }}
                size="small"
              >
                <Option value="name">{t('datasetDetail.sortByName')}</Option>
                <Option value="createdAt">{t('datasetDetail.sortByCreatedAt')}</Option>
                <Option value="updatedAt">{t('datasetDetail.sortByUpdatedAt')}</Option>
              </Select>
              <Button
                icon={sortOrder === 'asc' ? <SortAscendingOutlined /> : <SortDescendingOutlined />}
                onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                size="small"
              >
                {sortOrder === 'asc' ? t('datasetDetail.sortAsc') : t('datasetDetail.sortDesc')}
              </Button>
            </Space>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', paddingRight: '10px' }}>
            <PaginatedList<Sample>
              fetchData={fetchSamples}
              initialPageSize={8}
              pageSizeOptions={['8', '12', '20', '32', '50']}
              refreshKey={`${id}-${sortBy}-${sortOrder}-${sampleRefreshKey}`}
              resetPageOnRefresh
              onMetaChange={(meta) => setSampleMeta(meta)}
              renderItems={(items) => (
                items.length === 0 ? (
                  <Card>
                    <div style={{ textAlign: 'center', padding: 40 }}>
                      <FileTextOutlined style={{ fontSize: 48, color: '#ccc', marginBottom: 16 }} />
                      <Title level={5} style={{ color: '#999' }}>{t('datasetDetail.noSamples')}</Title>
                      {canUpload ? (
                        <Button type="primary" icon={<UploadOutlined />} onClick={handleUploadClick}>
                          {t('datasetDetail.uploadData')}
                        </Button>
                      ) : (
                        <Tooltip title={t('common.noPermission')}>
                          <Button type="primary" icon={<UploadOutlined />} disabled>
                            {t('datasetDetail.uploadData')}
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
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 16 }}>
                  <span style={{ fontSize: 12, color: '#666' }}>
                    {t('datasetDetail.pageStatus', {
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
      label: t('datasetDetail.settings'),
      children: (
        <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }}>
          <DatasetSettings 
            dataset={dataset} 
            onUpdate={(updatedDataset: Dataset) => setDataset(updatedDataset)} 
          />
        </div>
      ),
    }] : []),
  ];

  return (
    <Layout style={{ background: '#fff', height: '100%' }}>
      <Sider width={300} theme="light" style={{ borderRight: '1px solid #f0f0f0', padding: '20px', overflowY: 'auto' }}>
        <Button 
          type="text" 
          icon={<ArrowLeftOutlined />} 
          onClick={() => navigate('/')}
          style={{ marginBottom: 16 }}
        >
          {t('datasetDetail.backToList')}
        </Button>
        
        <Title level={4}>{dataset.name}</Title>
        <Space style={{ marginBottom: 8 }}>
          <Tag color={getDatasetTypeColor(dataset.type)}>
            {getDatasetTypeLabel(dataset.type)}
          </Tag>
          {isOwner && <Tag color="gold">{t('common.owner')}</Tag>}
          {role && !isOwner && <Tag>{role.displayName}</Tag>}
        </Space>
        {dataset.description && (
          <div style={{ marginBottom: 16, fontSize: 12, color: '#666' }}>
            {dataset.description}
          </div>
        )}
        
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {canUpload ? (
            <Button block icon={<UploadOutlined />} onClick={handleUploadClick}>
              {t('datasetDetail.uploadData')}
            </Button>
          ) : (
            <Tooltip title={t('common.noPermission')}>
              <Button block icon={<UploadOutlined />} disabled>
                {t('datasetDetail.uploadData')}
              </Button>
            </Tooltip>
          )}
          
          <input 
            type="file" 
            ref={fileInputRef} 
            style={{ display: 'none' }} 
            multiple 
            accept={getAcceptType()} 
            onChange={handleFileChange} 
          />

          {canEdit && (
            <Button block icon={<SettingOutlined />} onClick={() => setActiveTab('settings')}>
              {t('datasetDetail.settings')}
            </Button>
          )}
        </Space>
      </Sider>
      <Content style={{ padding: '24px', height: '100%', overflow: 'hidden' }}>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} className="full-height-tabs" />
        
        {/* Upload Progress Modal */}
        <UploadProgressModal
          open={uploadModalOpen}
          progress={progress}
          onClose={handleUploadModalClose}
          onCancel={handleUploadCancel}
        />

        {/* Sample Asset Modal */}
        <SampleAssetModal
          open={assetModalOpen}
          sample={selectedSample}
          onClose={() => {
            setAssetModalOpen(false);
            setSelectedSample(null);
          }}
        />
      </Content>
    </Layout>
  );
};

export default DatasetDetail;
