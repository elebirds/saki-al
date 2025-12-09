import React, { useState, useEffect } from 'react';
import { Form, Input, Button, Card, Select, Space, Tag, InputNumber, message, ColorPicker } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { Project, LabelConfig, ALStrategy, ModelArchitecture } from '../types';
import { api } from '../services/api';

interface ProjectSettingsProps {
  project: Project;
  onUpdate: (updatedProject: Project) => void;
}

const ProjectSettings: React.FC<ProjectSettingsProps> = ({ project, onUpdate }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [labels, setLabels] = useState<LabelConfig[]>(project.labels || []);
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#1677ff');
  const [strategies, setStrategies] = useState<ALStrategy[]>([]);
  const [architectures, setArchitectures] = useState<ModelArchitecture[]>([]);

  useEffect(() => {
    api.getStrategies().then(setStrategies);
    api.getArchitectures().then(setArchitectures);
  }, []);

  const handleSave = (values: any) => {
    const updatedProject = {
      ...project,
      ...values,
      labels,
    };
    // In a real app, we would make an API call here
    console.log('Saving project settings:', updatedProject);
    onUpdate(updatedProject);
    message.success(t('projectSettings.successMessage'));
  };

  const handleAddLabel = () => {
    if (newLabelName && !labels.some(l => l.name === newLabelName)) {
      setLabels([...labels, { name: newLabelName, color: typeof newLabelColor === 'string' ? newLabelColor : (newLabelColor as any).toHexString() }]);
      setNewLabelName('');
      // Keep the color or reset? Let's keep it for convenience or maybe randomize
    }
  };

  const handleRemoveLabel = (labelName: string) => {
    setLabels(labels.filter(l => l.name !== labelName));
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: project.name,
          description: project.description,
          'alConfig.strategy': project.alConfig?.strategy || 'least_confidence',
          'alConfig.batchSize': project.alConfig?.batchSize || 10,
          'modelConfig.architecture': project.modelConfig?.architecture || 'resnet50',
        }}
        onFinish={handleSave}
      >
        <Card title={t('projectSettings.basicInfo')} style={{ marginBottom: 24 }}>
          <Form.Item label={t('projectSettings.projectName')} name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label={t('projectSettings.description')} name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Card>

        <Card title={t('projectSettings.labelManagement')} style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <Space wrap>
              {labels.map(label => (
                <div key={label.name} style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid #f0f0f0', padding: '4px 8px', borderRadius: 4 }}>
                  <ColorPicker 
                    size="small"
                    value={label.color} 
                    onChange={(c: any) => {
                      const newColor = typeof c === 'string' ? c : c.toHexString();
                      setLabels(labels.map(l => l.name === label.name ? { ...l, color: newColor } : l));
                    }} 
                  />
                  <Tag
                    closable
                    color={label.color}
                    onClose={(e) => {
                      e.preventDefault();
                      handleRemoveLabel(label.name);
                    }}
                    style={{ marginRight: 0 }}
                  >
                    {label.name}
                  </Tag>
                </div>
              ))}
            </Space>
          </div>
          <Space>
            <Input
              placeholder={t('projectSettings.newLabelName')}
              value={newLabelName}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewLabelName(e.target.value)}
              onPressEnter={handleAddLabel}
              style={{ width: 200 }}
            />
            <ColorPicker value={newLabelColor} onChange={(c: any) => setNewLabelColor(c)} />
            <Button type="dashed" onClick={handleAddLabel} icon={<PlusOutlined />}>
              {t('projectSettings.addLabel')}
            </Button>
          </Space>
        </Card>

        <Card title={t('projectSettings.alConfig')} style={{ marginBottom: 24 }}>
          <Form.Item label={t('projectSettings.queryStrategy')} name="alConfig.strategy">
            <Select>
              {strategies.map(s => (
                <Select.Option key={s.id} value={s.id}>{s.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label={t('projectSettings.batchSize')} name="alConfig.batchSize" help={t('projectSettings.batchSizeHelp')}>
            <InputNumber min={1} max={1000} />
          </Form.Item>
        </Card>

        <Card title={t('projectSettings.modelConfig')} style={{ marginBottom: 24 }}>
          <Form.Item label={t('projectSettings.modelArchitecture')} name="modelConfig.architecture">
            <Select>
              {architectures
                .filter(a => a.taskType === 'both' || a.taskType === project.taskType)
                .map(a => (
                  <Select.Option key={a.id} value={a.id}>{a.name}</Select.Option>
                ))}
            </Select>
          </Form.Item>
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" size="large" block>
            {t('projectSettings.saveSettings')}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
};

export default ProjectSettings;
