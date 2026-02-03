import React, { useState } from 'react';
import { Form, Input, Button, Space, message, Card, Popconfirm, Divider } from 'antd';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Dataset } from '../../types';
import { api } from '../../services/api';
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons';

interface DatasetSettingsProps {
  dataset: Dataset;
  onUpdate: (dataset: Dataset) => void;
}

const DatasetSettings: React.FC<DatasetSettingsProps> = ({ dataset, onUpdate }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

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
      message.success(t('datasetSettings.updateSuccess'));
    } catch (error) {
      message.error(t('datasetSettings.updateError'));
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

  return (
    <div>
      <Card title={t('datasetSettings.basicInfo')}>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
        >
          <Form.Item
            label={t('datasetSettings.name')}
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
                {t('datasetSettings.save')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Divider />

      <Card title={t('datasetSettings.dangerZone')} style={{ borderColor: '#ff4d4f' }}>
        <p>{t('datasetSettings.deleteWarning')}</p>
        <Popconfirm
          title={t('datasetSettings.deleteConfirmTitle')}
          description={t('datasetSettings.deleteConfirmDescription')}
          onConfirm={handleDelete}
          okText={t('common.yes')}
          cancelText={t('common.no')}
          okButtonProps={{ danger: true }}
        >
          <Button danger icon={<DeleteOutlined />}>
            {t('datasetSettings.delete')}
          </Button>
        </Popconfirm>
      </Card>
    </div>
  );
};

export default DatasetSettings;
