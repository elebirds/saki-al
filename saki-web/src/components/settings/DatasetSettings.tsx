import React, { useState } from 'react';
import { Form, Input, Button, Space, message, Card, Popconfirm, Divider, Tabs } from 'antd';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Dataset } from '../../types';
import { api } from '../../services/api';
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons';
import DatasetMembers from './DatasetMembers';
import { useResourcePermission } from '../../hooks';

interface DatasetSettingsProps {
  dataset: Dataset;
  onUpdate: (dataset: Dataset) => void;
}

const DatasetSettings: React.FC<DatasetSettingsProps> = ({ dataset, onUpdate }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('basic');

  // Permission check
  const { can } = useResourcePermission('dataset', dataset.id);
  const canManageMembers = can('dataset:assign');

  React.useEffect(() => {
    form.setFieldsValue({
      name: dataset.name,
      description: dataset.description,
    });
  }, [dataset, form]);

  const handleSave = async (values: any) => {
    setLoading(true);
    try {
      const updated = await api.updateDataset(dataset.id, {
        name: values.name,
        description: values.description,
      });
      onUpdate(updated);
      message.success(t('datasetSettings.successMessage'));
    } catch (error) {
      message.error(t('datasetSettings.errorMessage'));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    try {
      await api.deleteDataset(dataset.id);
      message.success(t('datasetSettings.deleteSuccess'));
      navigate('/');
    } catch (error) {
      message.error(t('datasetSettings.deleteError'));
    }
  };

  const tabItems = [
    {
      key: 'basic',
      label: t('datasetSettings.basicInfo'),
      children: (
        <Card title={t('datasetSettings.basicInfo')}>
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSave}
          >
            <Form.Item
              label={t('datasetSettings.datasetName')}
              name="name"
              rules={[
                { required: true, message: t('datasetSettings.nameRequired') },
                { min: 1, max: 100 },
              ]}
            >
              <Input placeholder={t('datasetSettings.namePlaceholder')} />
            </Form.Item>

            <Form.Item
              label={t('datasetSettings.description')}
              name="description"
            >
              <Input.TextArea
                placeholder={t('datasetSettings.descriptionPlaceholder')}
                rows={4}
              />
            </Form.Item>

            <Form.Item>
              <Space>
                <Button type="primary" icon={<SaveOutlined />} htmlType="submit" loading={loading}>
                  {t('datasetSettings.saveBasicInfo')}
                </Button>
              </Space>
            </Form.Item>
          </Form>

          <Divider />

          <Card title={t('datasetSettings.dangerZone')} className="!border !border-red-500">
            <p>{t('datasetSettings.deleteConfirmDesc')}</p>
            <Popconfirm
              title={t('datasetSettings.deleteConfirm')}
              description={t('datasetSettings.deleteConfirmDesc')}
              onConfirm={handleDelete}
              okText={t('common.yes')}
              cancelText={t('common.no')}
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />}>
                {t('datasetSettings.deleteDataset')}
              </Button>
            </Popconfirm>
          </Card>
        </Card>
      ),
    },
    ...(canManageMembers ? [{
      key: 'members',
      label: t('datasetMembers.title'),
      children: (
        <DatasetMembers datasetId={dataset.id} ownerId={dataset.ownerId} />
      ),
    }] : []),
  ];

  return (
    <div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  );
};

export default DatasetSettings;
