import React, { useState } from 'react';
import { Form, Input, Button, Card, Select, Space, Tag, InputNumber, message, ColorPicker } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Project, LabelConfig } from '../types';

interface ProjectSettingsProps {
  project: Project;
  onUpdate: (updatedProject: Project) => void;
}

const ProjectSettings: React.FC<ProjectSettingsProps> = ({ project, onUpdate }) => {
  const [form] = Form.useForm();
  const [labels, setLabels] = useState<LabelConfig[]>(project.labels || []);
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#1677ff');

  const handleSave = (values: any) => {
    const updatedProject = {
      ...project,
      ...values,
      labels,
    };
    // In a real app, we would make an API call here
    console.log('Saving project settings:', updatedProject);
    onUpdate(updatedProject);
    message.success('Settings saved successfully');
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
        <Card title="Basic Information" style={{ marginBottom: 24 }}>
          <Form.Item label="Project Name" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Description" name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Card>

        <Card title="Label Management" style={{ marginBottom: 24 }}>
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
              placeholder="New Label Name"
              value={newLabelName}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewLabelName(e.target.value)}
              onPressEnter={handleAddLabel}
              style={{ width: 200 }}
            />
            <ColorPicker value={newLabelColor} onChange={(c: any) => setNewLabelColor(c)} />
            <Button type="dashed" onClick={handleAddLabel} icon={<PlusOutlined />}>
              Add Label
            </Button>
          </Space>
        </Card>

        <Card title="Active Learning Configuration" style={{ marginBottom: 24 }}>
          <Form.Item label="Query Strategy" name="alConfig.strategy">
            <Select>
              <Select.Option value="least_confidence">Least Confidence</Select.Option>
              <Select.Option value="margin_sampling">Margin Sampling</Select.Option>
              <Select.Option value="entropy_sampling">Entropy Sampling</Select.Option>
              <Select.Option value="random">Random Sampling</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="Query Batch Size" name="alConfig.batchSize" help="Number of samples to query in each iteration">
            <InputNumber min={1} max={1000} />
          </Form.Item>
        </Card>

        <Card title="Model Configuration" style={{ marginBottom: 24 }}>
          <Form.Item label="Model Architecture" name="modelConfig.architecture">
            <Select>
              <Select.Option value="resnet18">ResNet-18</Select.Option>
              <Select.Option value="resnet50">ResNet-50</Select.Option>
              <Select.Option value="efficientnet_b0">EfficientNet-B0</Select.Option>
              <Select.Option value="yolov5">YOLOv5 (Detection)</Select.Option>
              <Select.Option value="faster_rcnn">Faster R-CNN (Detection)</Select.Option>
            </Select>
          </Form.Item>
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" size="large" block>
            Save Settings
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
};

export default ProjectSettings;
