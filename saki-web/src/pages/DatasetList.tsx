import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Tag, Button, Typography, Modal, Form, Input, Select, message, Spin, Tooltip, Progress } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Dataset, AnnotationSystemType } from '../types';
import { api } from '../services/api';
import { useSystemCapabilities } from '../hooks';
import { PlusOutlined, DatabaseOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;
const { Option } = Select;

const DatasetList: React.FC = () => {
  const { t } = useTranslation();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  
  // Load available types from backend
  const { availableTypes, loading: typesLoading } = useSystemCapabilities();

  useEffect(() => {
    loadDatasets();
  }, []);

  const loadDatasets = async () => {
    setLoading(true);
    try {
      const data = await api.getDatasets();
      setDatasets(data);
    } catch (error) {
      message.error(t('datasetList.loadError'));
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      await api.createDataset({
        name: values.name,
        description: values.description,
        annotationSystem: values.annotationSystem as AnnotationSystemType,
      });
      message.success(t('datasetList.createSuccess'));
      setIsModalVisible(false);
      form.resetFields();
      loadDatasets();
    } catch (error) {
      message.error(t('datasetList.createError'));
    }
  };

  // Get annotation system tag color
  const getAnnotationSystemColor = (system: string | undefined) => {
    switch (system) {
      case 'fedo': return 'purple';
      case 'classic': return 'cyan';
      default: return 'default';
    }
  };

  // Calculate completion percentage
  const getCompletionPercent = (dataset: Dataset) => {
    if (dataset.sampleCount === 0) return 0;
    return Math.round((dataset.labeledCount / dataset.sampleCount) * 100);
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={2}>{t('datasetList.title')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
          {t('datasetList.newDataset')}
        </Button>
      </div>
      
      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          {datasets.map((dataset) => (
            <Col xs={24} sm={12} md={8} lg={6} key={dataset.id}>
              <Card
                hoverable
                title={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <DatabaseOutlined />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{dataset.name}</span>
                  </div>
                }
                extra={
                  <Tag color={getAnnotationSystemColor(dataset.annotationSystem)}>
                    {dataset.annotationSystem || 'classic'}
                  </Tag>
                }
                actions={[
                  <Button type="link" onClick={() => navigate(`/datasets/${dataset.id}`)}>
                    {t('datasetList.open')}
                  </Button>,
                ]}
              >
                <Paragraph ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>
                  {dataset.description || t('datasetList.noDescription')}
                </Paragraph>
                
                <div style={{ marginBottom: 12 }}>
                  <Progress 
                    percent={getCompletionPercent(dataset)} 
                    size="small" 
                    status={getCompletionPercent(dataset) === 100 ? 'success' : 'active'}
                  />
                </div>
                
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic 
                      title={t('datasetList.samples')} 
                      value={dataset.sampleCount || 0} 
                      valueStyle={{ fontSize: '16px' }} 
                    />
                  </Col>
                  <Col span={12}>
                    <Statistic 
                      title={t('datasetList.labeled')} 
                      value={dataset.labeledCount || 0} 
                      valueStyle={{ fontSize: '16px', color: '#3f8600' }} 
                    />
                  </Col>
                </Row>
              </Card>
            </Col>
          ))}
          
          {datasets.length === 0 && !loading && (
            <Col span={24}>
              <Card>
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <DatabaseOutlined style={{ fontSize: 48, color: '#ccc', marginBottom: 16 }} />
                  <Title level={4} style={{ color: '#999' }}>{t('datasetList.empty')}</Title>
                  <Paragraph style={{ color: '#999' }}>{t('datasetList.emptyHint')}</Paragraph>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
                    {t('datasetList.newDataset')}
                  </Button>
                </div>
              </Card>
            </Col>
          )}
        </Row>
      </Spin>

      <Modal
        title={t('datasetList.newDataset')}
        open={isModalVisible}
        onCancel={() => setIsModalVisible(false)}
        onOk={() => form.submit()}
      >
        {typesLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <Spin tip={t('common.loading')} />
          </div>
        ) : (
          <Form 
            form={form} 
            layout="vertical" 
            onFinish={handleCreate} 
            initialValues={{ annotationSystem: 'classic' }}
          >
            <Form.Item 
              name="name" 
              label={t('datasetList.datasetName')} 
              rules={[{ required: true, message: t('datasetList.nameRequired') }]}
            >
              <Input placeholder={t('datasetList.namePlaceholder')} />
            </Form.Item>
            <Form.Item name="description" label={t('datasetList.description')}>
              <Input.TextArea placeholder={t('datasetList.descriptionPlaceholder')} rows={3} />
            </Form.Item>
            <Form.Item 
              name="annotationSystem" 
              label={
                <span>
                  {t('datasetList.annotationSystem')}&nbsp;
                  <Tooltip title={t('datasetList.annotationSystemHelp')}>
                    <span style={{ color: '#999', cursor: 'help' }}>ⓘ</span>
                  </Tooltip>
                </span>
              } 
              rules={[{ required: true }]}
            >
              <Select>
                {availableTypes?.annotationSystems.map(system => (
                  <Option key={system.value} value={system.value}>
                    <Tooltip title={system.description} placement="right">
                      {system.label}
                    </Tooltip>
                  </Option>
                ))}
              </Select>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default DatasetList;
