import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Typography, Space, Card, List, Tag, Progress, Tabs, message } from 'antd';
import { useTranslation } from 'react-i18next';
import { Dataset, Sample } from '../../types';
import { api } from '../../services/api';
import { HighlightOutlined, UploadOutlined, SettingOutlined, FileTextOutlined, ExportOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import UploadProgressModal from '../../components/UploadProgressModal';
import DatasetSettings from '../../components/settings/DatasetSettings';
import { useUpload } from '../../hooks';


const { Title } = Typography;
const { Sider, Content } = Layout;

const DatasetDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [activeTab, setActiveTab] = useState('data');
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Initialize upload hook
  const { progress, upload, cancel, reset, isUploading } = useUpload(id || '', {
    useStreaming: true,
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
        api.getSamples(id).then(setSamples);
        api.getDataset(id).then((d) => {
          if (d) setDataset(d);
        });
      }
    },
    onError: (error) => {
      message.error(error);
    },
  });


  useEffect(() => {
    if (id) {
      api.getDataset(id).then((d) => {
        if (d) setDataset(d);
      });
      api.getSamples(id).then(setSamples);
    }
  }, [id]);

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

  // Get preview image URL for FEDO sample
  const getFedoPreviewUrl = (sample: Sample) => {
    return `http://localhost:8000/api/v1/specialized/samples/${sample.id}/image/time_energy`;
  };

  // Render sample item based on annotation system
  const renderSampleItem = (item: Sample) => {
    if (dataset.annotationSystem === 'fedo') {
      const previewUrl = getFedoPreviewUrl(item);
      return (
        <Card
          hoverable
          cover={
            <img 
              alt="sample" 
              src={previewUrl} 
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <FileTextOutlined style={{ color: '#1890ff' }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.name || item.id}
                </span>
              </div>
            }
            description={<Tag color={item.status === 'labeled' ? 'green' : 'orange'}>{item.status}</Tag>}
          />
        </Card>
      );
    }
    // Classic image display
    return (
      <Card
        hoverable
        cover={<img alt="sample" src={item.url} style={{ height: 150, objectFit: 'cover' }} />}
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

  const items = [
    {
      key: 'data',
      label: t('datasetDetail.dataPool'),
      children: (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Title level={5} style={{ flexShrink: 0 }}>{t('datasetDetail.dataPool')}</Title>
          <div style={{ flex: 1, overflowY: 'auto', paddingRight: '10px' }}>
            {samples.length === 0 ? (
              <Card>
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <FileTextOutlined style={{ fontSize: 48, color: '#ccc', marginBottom: 16 }} />
                  <Title level={5} style={{ color: '#999' }}>{t('datasetDetail.noSamples')}</Title>
                  <Button type="primary" icon={<UploadOutlined />} onClick={handleUploadClick}>
                    {t('datasetDetail.uploadData')}
                  </Button>
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
    {
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
    },
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
        <Tag color={dataset.annotationSystem === 'fedo' ? 'purple' : 'cyan'} style={{ marginBottom: 16 }}>
          {dataset.annotationSystem}
        </Tag>
        
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
            onClick={() => navigate(`/workspace/${dataset.id}`)}
            disabled={samples.length === 0}
          >
            {t('datasetDetail.startLabeling')}
          </Button>
          <Button block icon={<UploadOutlined />} onClick={handleUploadClick}>
            {t('datasetDetail.uploadData')}
          </Button>
          <input 
            type="file" 
            ref={fileInputRef} 
            style={{ display: 'none' }} 
            multiple 
            accept={getAcceptType()} 
            onChange={handleFileChange} 
          />
          <Button block icon={<ExportOutlined />} onClick={handleExport} disabled={dataset.labeledCount === 0}>
            {t('datasetDetail.exportData')}
          </Button>
          <Button block icon={<SettingOutlined />} onClick={() => setActiveTab('settings')}>
            {t('datasetDetail.settings')}
          </Button>
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
