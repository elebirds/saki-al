import React, { useState, useEffect, useCallback } from 'react';
import { Form, Input, Button, Card, Select, Space, Tag, message, ColorPicker, Popconfirm, Tooltip, Modal, Badge, Spin, Tabs } from 'antd';
import { PlusOutlined, DeleteOutlined, LockOutlined, EditOutlined, ExclamationCircleOutlined, TeamOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Dataset, Label, LabelCreate, TypeInfo } from '../../types';
import { api } from '../../services/api';
import { useSystemCapabilities, useResourcePermission } from '../../hooks';
import DatasetMembers from './DatasetMembers';

interface DatasetSettingsProps {
  dataset: Dataset;
  onUpdate: (updatedDataset: Dataset) => void;
}

const DatasetSettings: React.FC<DatasetSettingsProps> = ({ dataset, onUpdate }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [labels, setLabels] = useState<Label[]>([]);
  const [loadingLabels, setLoadingLabels] = useState(true);
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#1677ff');
  const [editingLabel, setEditingLabel] = useState<Label | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');
  const { availableTypes } = useSystemCapabilities();
  
  // Permission hook
  const { can } = useResourcePermission('dataset', dataset.id, dataset.ownerId);
  const canManageMembers = can('dataset:assign');
  const canDelete = can('dataset:delete');
  const canManageLabels = can('label:create');

  // Load labels on mount
  const loadLabels = useCallback(async () => {
    try {
      setLoadingLabels(true);
      const loadedLabels = await api.getLabels(dataset.id);
      setLabels(loadedLabels);
    } catch (error) {
      message.error(t('datasetSettings.loadLabelsError'));
    } finally {
      setLoadingLabels(false);
    }
  }, [dataset.id, t]);

  useEffect(() => {
    loadLabels();
  }, [loadLabels]);

  const handleSaveBasicInfo = async (values: any) => {
    try {
      const updatedDataset = await api.updateDataset(dataset.id, values);
      onUpdate(updatedDataset);
      message.success(t('datasetSettings.successMessage'));
    } catch (error) {
      message.error(t('datasetSettings.errorMessage'));
    }
  };

  const handleDeleteDataset = async () => {
    try {
      await api.deleteDataset(dataset.id);
      message.success(t('datasetDetail.deleteSuccess'));
      navigate('/');
    } catch (error) {
      message.error(t('datasetDetail.deleteError'));
    }
  };

  const handleAddLabel = async () => {
    if (!newLabelName.trim()) return;
    
    // Check for duplicate name
    if (labels.some(l => l.name === newLabelName.trim())) {
      message.warning(t('datasetSettings.labelExists'));
      return;
    }

    try {
      const newLabel: LabelCreate = {
        name: newLabelName.trim(),
        color: typeof newLabelColor === 'string' ? newLabelColor : (newLabelColor as any).toHexString(),
        sortOrder: labels.length,
      };
      const createdLabel = await api.createLabel(dataset.id, newLabel);
      setLabels([...labels, createdLabel]);
      setNewLabelName('');
      message.success(t('datasetSettings.labelCreated'));
    } catch (error: any) {
      message.error(error.response?.data?.detail || t('datasetSettings.labelCreateError'));
    }
  };

  const handleUpdateLabel = async () => {
    if (!editingLabel || !editName.trim()) return;

    try {
      const updatedLabel = await api.updateLabel(editingLabel.id, {
        name: editName.trim(),
        color: typeof editColor === 'string' ? editColor : (editColor as any).toHexString(),
      });
      setLabels(labels.map(l => l.id === updatedLabel.id ? updatedLabel : l));
      setEditingLabel(null);
      message.success(t('datasetSettings.labelUpdated'));
    } catch (error: any) {
      message.error(error.response?.data?.detail || t('datasetSettings.labelUpdateError'));
    }
  };

  const handleDeleteLabel = async (label: Label, force: boolean = false) => {
    try {
      const result = await api.deleteLabel(label.id, force);
      setLabels(labels.filter(l => l.id !== label.id));
      if (result.deletedAnnotations > 0) {
        message.success(t('datasetSettings.labelDeletedWithAnnotations', { count: result.deletedAnnotations }));
      } else {
        message.success(t('datasetSettings.labelDeleted'));
      }
    } catch (error: any) {
      // Handle 409 Conflict - label has annotations
      if (error.response?.status === 409) {
        const detail = error.response.data.detail;
        Modal.confirm({
          title: t('datasetSettings.confirmDeleteLabel'),
          icon: <ExclamationCircleOutlined />,
          content: t('datasetSettings.labelHasAnnotations', { count: detail.annotation_count || detail.annotationCount }),
          okText: t('datasetSettings.deleteWithAnnotations'),
          okType: 'danger',
          cancelText: t('common.cancel'),
          onOk: () => handleDeleteLabel(label, true),
        });
      } else {
        message.error(error.response?.data?.detail || t('datasetSettings.labelDeleteError'));
      }
    }
  };

  const openEditModal = (label: Label) => {
    setEditingLabel(label);
    setEditName(label.name);
    setEditColor(label.color);
  };

  const tabItems: Array<{ key: string; label: React.ReactNode; children: React.ReactNode }> = [
    {
      key: 'basic',
      label: t('permissions.tabs.basicInfo'),
      children: (
        <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: dataset.name,
          description: dataset.description,
        }}
        onFinish={handleSaveBasicInfo}
      >
        <Card title={t('datasetSettings.basicInfo')} style={{ marginBottom: 24 }}>
          <Form.Item 
            label={t('datasetSettings.datasetName')} 
            name="name" 
            rules={[{ required: true, message: t('datasetSettings.nameRequired') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label={t('datasetSettings.description')} name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item 
            label={
              <span>
                {t('datasetSettings.annotationSystem')}
                <Tooltip title={t('datasetSettings.annotationSystemReadonly')}>
                  <LockOutlined style={{ marginLeft: 8, color: '#999' }} />
                </Tooltip>
              </span>
            }
          >
            <Select 
              value={dataset.annotationSystem || 'classic'} 
              disabled
              style={{ backgroundColor: '#f5f5f5' }}
            >
              {(availableTypes?.annotationSystems || []).map((type: TypeInfo) => (
                <Select.Option key={type.value} value={type.value}>
                  {type.label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              {t('datasetSettings.saveBasicInfo')}
            </Button>
          </Form.Item>
        </Card>
      </Form>
      ),
    },
    {
      key: 'labels',
      label: t('permissions.tabs.labels'),
      children: (
        <Card title={t('datasetSettings.labelManagement')} style={{ marginBottom: 24 }}>
        <Spin spinning={loadingLabels}>
          <div style={{ marginBottom: 16 }}>
            {labels.length === 0 ? (
              <div style={{ color: '#999', marginBottom: 16 }}>
                {t('datasetSettings.noLabels')}
              </div>
            ) : (
              <Space wrap>
                {labels.map(label => (
                  <div 
                    key={label.id} 
                    style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: 8, 
                      border: '1px solid #f0f0f0', 
                      padding: '4px 8px', 
                      borderRadius: 4,
                      background: '#fafafa'
                    }}
                  >
                    <Badge 
                      count={label.annotationCount} 
                      size="small" 
                      style={{ backgroundColor: label.annotationCount > 0 ? '#52c41a' : '#d9d9d9' }}
                    >
                      <Tag color={label.color} style={{ marginRight: 0 }}>
                        {label.name}
                      </Tag>
                    </Badge>
                    {canManageLabels && (
                      <>
                        <Button 
                          type="text" 
                          size="small" 
                          icon={<EditOutlined />} 
                          onClick={() => openEditModal(label)}
                        />
                        <Popconfirm
                          title={t('datasetSettings.confirmDeleteLabel')}
                          description={label.annotationCount > 0 
                            ? t('datasetSettings.labelHasAnnotationsWarning', { count: label.annotationCount })
                            : undefined
                          }
                          onConfirm={() => handleDeleteLabel(label)}
                          okText={t('common.yes')}
                          cancelText={t('common.no')}
                          okButtonProps={{ danger: true }}
                        >
                          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </>
                    )}
                  </div>
                ))}
              </Space>
            )}
          </div>
        </Spin>
        
        {canManageLabels && (
          <Space>
            <Input
              placeholder={t('datasetSettings.newLabelName')}
              value={newLabelName}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewLabelName(e.target.value)}
              onPressEnter={handleAddLabel}
              style={{ width: 200 }}
            />
            <ColorPicker value={newLabelColor} onChange={(c: any) => setNewLabelColor(c)} />
            <Button type="dashed" onClick={handleAddLabel} icon={<PlusOutlined />}>
              {t('datasetSettings.addLabel')}
            </Button>
          </Space>
        )}
      </Card>
      ),
    },
  ];

  if (canManageMembers) {
    tabItems.push({
      key: 'members',
      label: (
        <span>
          <TeamOutlined /> {t('permissions.tabs.members')}
        </span>
      ),
      children: <DatasetMembers datasetId={dataset.id} ownerId={dataset.ownerId} />,
    });
  }

  if (canDelete) {
    tabItems.push({
      key: 'danger',
      label: t('permissions.tabs.dangerZone'),
      children: (
        <Card title={t('datasetSettings.dangerZone')} style={{ marginBottom: 24, borderColor: '#ff4d4f' }}>
          <Popconfirm
            title={t('datasetDetail.deleteConfirm')}
            description={t('datasetDetail.deleteConfirmDesc')}
            onConfirm={handleDeleteDataset}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true }}
          >
            <Button type="primary" danger icon={<DeleteOutlined />}>
              {t('datasetSettings.deleteDataset')}
            </Button>
          </Popconfirm>
        </Card>
      ),
    });
  }

  return (
    <div style={{ maxWidth: 800 }}>
      <Tabs items={tabItems} defaultActiveKey="basic" />
      
      {/* Edit Label Modal */}
      <Modal
        title={t('datasetSettings.editLabel')}
        open={!!editingLabel}
        onOk={handleUpdateLabel}
        onCancel={() => setEditingLabel(null)}
        okText={t('common.save')}
        cancelText={t('common.cancel')}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <label>{t('datasetSettings.labelName')}</label>
            <Input 
              value={editName} 
              onChange={(e) => setEditName(e.target.value)} 
              style={{ marginTop: 8 }}
            />
          </div>
          <div>
            <label>{t('datasetSettings.labelColor')}</label>
            <div style={{ marginTop: 8 }}>
              <ColorPicker value={editColor} onChange={(c: any) => setEditColor(c)} />
            </div>
          </div>
          {editingLabel && editingLabel.annotationCount > 0 && (
            <div style={{ color: '#666', fontSize: 12, marginTop: 8 }}>
              {t('datasetSettings.labelAnnotationCount', { count: editingLabel.annotationCount })}
            </div>
          )}
        </Space>
      </Modal>
    </div>
  );
};

export default DatasetSettings;
