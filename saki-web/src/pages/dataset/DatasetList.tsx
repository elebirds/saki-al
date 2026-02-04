import React, { useCallback, useMemo, useState } from 'react';
import { Card, Col, Row, Tag, Button, Typography, Modal, Form, Input, Select, message, Tooltip } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Dataset } from '../../types';
import { api } from '../../services/api';
import { useSystemCapabilities, usePermission } from '../../hooks';
import { PlusOutlined, DatabaseOutlined } from '@ant-design/icons';
import { PaginatedList } from '../../components/common/PaginatedList';

const { Paragraph, Text, Title } = Typography;
const { Option } = Select;

const DatasetList: React.FC = () => {
  const { t } = useTranslation();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [showNoMore, setShowNoMore] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  
  // Permission hook
  const { can } = usePermission();
  const canCreate = can('dataset:create');
  
  // Load available types from backend
  const { getDatasetTypeLabel, getDatasetTypeColor, availableTypes } = useSystemCapabilities();

  const fetchDatasets = useCallback(async (page: number, pageSize: number) => {
    try {
      return await api.getDatasets(page, pageSize);
    } catch (error) {
      message.error(t('datasetList.loadError'));
      throw error;
    }
  }, [t]);

  const handleCreate = async (values: any) => {
    try {
      await api.createDataset(values);
      message.success(t('datasetList.createSuccess'));
      setIsModalVisible(false);
      form.resetFields();
      setRefreshKey((v) => v + 1);
    } catch (error) {
      message.error(t('datasetList.createError'));
    }
  };

  const renderDatasets = useCallback((items: Dataset[], _loading?: boolean) => (
    <>
      <Row gutter={[16, 16]}>
        {items.map((dataset) => (
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
      </Row>
      {showNoMore ? (
        <div className="mt-4 text-sm text-github-muted text-center">没有更多内容了～</div>
      ) : null}
    </>
  ), [getDatasetTypeColor, getDatasetTypeLabel, navigate, t, showNoMore]);

  const emptyFallback = useMemo(() => (
    <Row>
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
    </Row>
  ), [canCreate, t]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-6 flex-shrink-0">
        <Text className="text-sm font-semibold text-github-text">{t('datasetList.title')}</Text>
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
      
      <div className="flex-1 min-h-0">
        <PaginatedList<Dataset>
          fetchData={fetchDatasets}
          renderItems={(items, loading) => renderDatasets(items, loading)}
          emptyFallback={emptyFallback}
          refreshKey={refreshKey}
          resetPageOnRefresh
          initialPageSize={8}
          pageSizeOptions={['8', '12', '20', '32', '50']}
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
          onError={() => message.error(t('datasetList.loadError'))}
          renderPaginationWrapper={(node) => (
            <div className="mt-auto flex justify-end pt-4">{node}</div>
          )}
        />
      </div>

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
