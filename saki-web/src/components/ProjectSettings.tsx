import React, { useState, useEffect } from 'react';
import { Form, Input, Button, Card, Select, Space, Tag, InputNumber, message, ColorPicker, Popconfirm, Tooltip } from 'antd';
import { PlusOutlined, DeleteOutlined, LockOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Project, LabelConfig, QueryStrategy, BaseModel, TypeInfo } from '../types';
import { api } from '../services/api';
import { useSystemCapabilities } from '../hooks/useSystemCapabilities';

interface ProjectSettingsProps {
  project: Project;
  onUpdate: (updatedProject: Project) => void;
}

const ProjectSettings: React.FC<ProjectSettingsProps> = ({ project, onUpdate }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [labels, setLabels] = useState<LabelConfig[]>(project.labels || []);
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#1677ff');
  const [strategies, setStrategies] = useState<QueryStrategy[]>([]);
  const [baseModels, setBaseModels] = useState<BaseModel[]>([]);
  const { availableTypes } = useSystemCapabilities();

  useEffect(() => {
    api.getStrategies().then(setStrategies);
    api.getBaseModels().then(setBaseModels);
  }, []);

  const handleSave = async (values: any) => {
    try {
      const updatedProject = await api.updateProject(project.id, {
        ...values,
        labels,
      });
      onUpdate(updatedProject);
      message.success(t('projectSettings.successMessage'));
    } catch (error) {
      message.error('Failed to update project');
    }
  };

  const handleDelete = async () => {
    try {
      await api.deleteProject(project.id);
      message.success('Project deleted');
      navigate('/');
    } catch (error) {
      message.error('Failed to delete project');
    }
  };

  const handleAddLabel = () => {
    if (newLabelName && !labels.some(l => l.name === newLabelName)) {
      setLabels([...labels, { name: newLabelName, color: typeof newLabelColor === 'string' ? newLabelColor : (newLabelColor as any).toHexString() }]);
      setNewLabelName('');
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
          taskType: project.taskType || 'classification',
          queryStrategyId: project.queryStrategyId,
          baseModelId: project.baseModelId,
          'alConfig.batchSize': project.alConfig?.batchSize || 10,
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
          <Form.Item label={t('projectSettings.taskType')} name="taskType">
            <Select>
              {(availableTypes?.taskTypes || []).map((type: TypeInfo) => (
                <Select.Option key={type.value} value={type.value}>
                  {type.label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item 
            label={
              <span>
                {t('projectSettings.annotationSystem')}
                <Tooltip title={t('projectSettings.annotationSystemReadonly')}>
                  <LockOutlined style={{ marginLeft: 8, color: '#999' }} />
                </Tooltip>
              </span>
            }
          >
            <Select 
              value={project.annotationSystem || 'classic'} 
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
        </Card>

        {project.annotationSystem === 'fedo' && (
          <Card title={t('projectSettings.fedoConfig') || 'FEDO Settings'} style={{ marginBottom: 24 }}>
            <Form.Item 
              label={t('projectSettings.thumbnailView') || 'Thumbnail View'}
              name={['annotationConfig', 'thumbnailView']}
              initialValue={project.annotationConfig?.thumbnailView || 'time_energy'}
            >
              <Select>
                <Select.Option value="time_energy">Time-Energy View</Select.Option>
                <Select.Option value="l_wd">L-ωd View</Select.Option>
              </Select>
            </Form.Item>
          </Card>
        )}

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
          <Form.Item label={t('projectSettings.queryStrategy')} name="queryStrategyId">
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
          <Form.Item label={t('projectSettings.baseModel')} name="baseModelId">
            <Select>
              {baseModels
                .filter(m => m.taskType === project.taskType)
                .map(m => (
                  <Select.Option key={m.id} value={m.id}>{m.name}</Select.Option>
                ))}
            </Select>
          </Form.Item>
        </Card>

        <Form.Item>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button type="primary" htmlType="submit">
              {t('projectSettings.saveSettings')}
            </Button>
            <Popconfirm
              title="Are you sure you want to delete this project?"
              description="This action cannot be undone."
              onConfirm={handleDelete}
              okText="Yes"
              cancelText="No"
            >
              <Button type="primary" danger icon={<DeleteOutlined />}>
                Delete Project
              </Button>
            </Popconfirm>
          </div>
        </Form.Item>
      </Form>
    </div>
  );
};

export default ProjectSettings;
