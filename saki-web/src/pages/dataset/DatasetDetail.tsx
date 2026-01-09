import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Typography, Space, Card, List, Tag, Progress, Tabs, message, Select, Tooltip } from 'antd';
import { useTranslation } from 'react-i18next';
import { Dataset, Sample, User } from '../../types';
import { api } from '../../services/api';
import { HighlightOutlined, UploadOutlined, SettingOutlined, FileTextOutlined, ExportOutlined, ArrowLeftOutlined, SortAscendingOutlined, SortDescendingOutlined } from '@ant-design/icons';
import UploadProgressModal from '../../components/UploadProgressModal';
import DatasetSettings from '../../components/settings/DatasetSettings';
import { useUpload, useSortSettings, useResourcePermission } from '../../hooks';
import { Authorized } from '../../components/common';

const { Title } = Typography;
const { Sider, Content } = Layout;
const { Option } = Select;

const DatasetDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [activeTab, setActiveTab] = useState('data');
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [owner, setOwner] = useState<User | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Permission hook
  const { can, role, isOwner } = useResourcePermission('dataset', id, dataset?.ownerId);
  
  // 使用排序设置 hook
  const { sortBy, sortOrder, setSortBy, setSortOrder, sortOptions } = useSortSettings(id);

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
        loadSamples(id);
        api.getDataset(id).then((d) => {
          if (d) setDataset(d);
        });
      }
    },
    onError: (error) => {
      message.error(error);
    },
  });


  // Load samples with current sort settings
  const loadSamples = useCallback((datasetId: string) => {
    api.getSamples(datasetId, sortOptions).then(setSamples).catch((error) => {
      console.error('Failed to load samples:', error);
      message.error(t('datasetDetail.loadSamplesError'));
    });
  }, [sortOptions, t]);

  // Load dataset and samples
  useEffect(() => {
    if (id) {
      api.getDataset(id).then((d) => {
        if (d) {
          setDataset(d);
          // Fetch owner info if available
          if (d.ownerId) {
            api.getUsers().then(users => {
              const ownerUser = users.find(u => u.id === d.ownerId);
              if (ownerUser) setOwner(ownerUser);
            }).catch(() => {});
          }
        }
      });
      loadSamples(id);
    }
  }, [id, loadSamples]);

  // Reload samples when sort settings change (but not on initial mount)
  const isInitialMountRef = useRef(true);
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false;
      return;
    }
    if (id) {
      loadSamples(id);
    }
  }, [sortBy, sortOrder, id, loadSamples]);

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

  const handleExport = async () => {
    if (!dataset) return;
    try {
      const data = await api.exportDataset(dataset.id);
      // Download as JSON file
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${dataset.name}_export.json`;
      a.click();
      URL.revokeObjectURL(url);
      message.success(t('datasetDetail.exportSuccess'));
    } catch (error) {
      message.error(t('datasetDetail.exportError'));
    }
  };


  if (!dataset) return <div>{t('common.loading')}</div>;

  // Determine file accept type based on annotation system
  const getAcceptType = () => {
    switch (dataset.annotationSystem) {
      case 'fedo':
        return '.txt';
      case 'classic':
      default:
        return 'image/*';
    }
  };

  // Render sample item - uses sample.url for all annotation systems
  const renderSampleItem = (item: Sample) => {
    const handleSampleClick = () => {
      if (!dataset) return;
      // 保存当前排序设置到localStorage
      const sortSettings = {
        sortBy,
        sortOrder,
      };
      localStorage.setItem(`dataset_${dataset.id}_sort`, JSON.stringify(sortSettings));
      // 导航到工作区，并传递sampleId作为URL参数
      navigate(`/workspace/${dataset.id}?sampleId=${item.id}`);
    };

    return (
      <Card
        hoverable
        onClick={handleSampleClick}
        style={{ cursor: 'pointer' }}
        cover={
          <img 
            alt="sample" 
            src={item.url} 
            style={{ height: 150, objectFit: 'cover' }}
            onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
              e.currentTarget.style.display = 'none';
            }}
          />
        }
        size="small"
      >
        <Card.Meta 
          title={
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {item.name}
            </span>
          }
          description={<Tag color={item.status === 'labeled' ? 'green' : 'orange'}>{item.status}</Tag>}
        />
      </Card>
    );
  };

  const completionPercent = dataset.sampleCount > 0 
    ? Math.round((dataset.labeledCount / dataset.sampleCount) * 100) 
    : 0;

  // Check permissions for various actions
  const canUpload = can('sample:create');
  const canExport = can('dataset:export');
  const canEdit = can('dataset:update');

  const items = [
    {
      key: 'data',
      label: t('datasetDetail.dataPool'),
      children: (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div style={{ flexShrink: 0, marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Title level={5} style={{ margin: 0 }}>{t('datasetDetail.dataPool')}</Title>
            <Space>
              <Select
                value={sortBy}
                onChange={setSortBy}
                style={{ width: 140 }}
                size="small"
              >
                <Option value="name">{t('datasetDetail.sortByName')}</Option>
                <Option value="status">{t('datasetDetail.sortByStatus')}</Option>
                <Option value="created_at">{t('datasetDetail.sortByCreatedAt')}</Option>
                <Option value="updated_at">{t('datasetDetail.sortByUpdatedAt')}</Option>
                <Option value="remark">{t('datasetDetail.sortByRemark')}</Option>
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
            {samples.length === 0 ? (
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
                dataSource={samples}
                renderItem={(item) => (
                  <List.Item>
                    {renderSampleItem(item)}
                  </List.Item>
                )}
              />
            )}
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
          <Tag color={dataset.annotationSystem === 'fedo' ? 'purple' : 'cyan'}>
            {dataset.annotationSystem}
          </Tag>
          {isOwner && <Tag color="gold">{t('common.owner')}</Tag>}
          {role && !isOwner && <Tag>{role.displayName}</Tag>}
        </Space>
        <div style={{ marginBottom: 16, fontSize: 12, color: '#666' }}>
          {t('datasetDetail.owner')}: {owner ? (owner.fullName || owner.email) : (dataset.ownerId ? '...' + dataset.ownerId.slice(-8) : t('common.unknown'))}
        </div>
        
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Card size="small" title={t('datasetDetail.progress')}>
            <Progress percent={completionPercent} />
            <div style={{ marginTop: 10 }}>
              {t('datasetDetail.labeled')}: {dataset.labeledCount} / {dataset.sampleCount}
            </div>
          </Card>
          
          <Button 
            type="primary" 
            block 
            icon={<HighlightOutlined />} 
            onClick={() => {
              // 保存当前排序设置到localStorage
              const sortSettings = {
                sortBy,
                sortOrder,
              };
              localStorage.setItem(`dataset_${dataset.id}_sort`, JSON.stringify(sortSettings));
              navigate(`/workspace/${dataset.id}`);
            }}
            disabled={samples.length === 0}
          >
            {t('datasetDetail.startLabeling')}
          </Button>

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

          {canExport ? (
            <Button block icon={<ExportOutlined />} onClick={handleExport} disabled={dataset.labeledCount === 0}>
              {t('datasetDetail.exportData')}
            </Button>
          ) : (
            <Tooltip title={t('common.noPermission')}>
              <Button block icon={<ExportOutlined />} disabled>
                {t('datasetDetail.exportData')}
              </Button>
            </Tooltip>
          )}

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
      </Content>
    </Layout>
  );
};

export default DatasetDetail;
