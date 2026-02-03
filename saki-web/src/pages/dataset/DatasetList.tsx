import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Tag, Button, Typography, Modal, Form, Input, Select, message, Spin, Tooltip, } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Dataset } from '../../types';
import { api } from '../../services/api';
import { useSystemCapabilities, usePermission } from '../../hooks';
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
  
  // Permission hook
  const { can } = usePermission();
  const canCreate = can('dataset:create');
  
  // Load available types from backend
  const { getDatasetTypeLabel, getDatasetTypeColor, availableTypes } = useSystemCapabilities();

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
      await api.createDataset(values);
      message.success(t('datasetList.createSuccess'));
      setIsModalVisible(false);
      form.resetFields();
      loadDatasets();
    } catch (error) {
      message.error(t('datasetList.createError'));
    }
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={2}>{t('datasetList.title')}</Title>
        {canCreate ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
            {t('datasetList.newDataset')}
          </Button>
        ) : (
          <Tooltip title={t('common.noPermission')}>
            <Button type="primary" icon={<PlusOutlined />} disabled>
              {t('datasetList.newDataset')}
            </Button>
          </Tooltip>
        )}
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
                  <Tag color={getDatasetTypeColor(dataset.type)}>
                    {getDatasetTypeLabel(dataset.type)}
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
                  {canCreate && (
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
                      {t('datasetList.newDataset')}
                    </Button>
                  )}
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
              name="type" 
              label={
                <span>
                  {t('datasetList.type')}&nbsp;
                  <Tooltip title={t('datasetList.typeHelp')}>
                    <span style={{ color: '#999', cursor: 'help' }}>ⓘ</span>
                  </Tooltip>
                </span>
              } 
              rules={[{ required: true }]}
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
