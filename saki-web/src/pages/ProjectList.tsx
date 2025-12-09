import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Tag, Button, Typography, Modal, Form, Input, Select, message } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Project } from '../types';
import { api } from '../services/api';
import { PlusOutlined, BarChartOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;
const { Option } = Select;

const ProjectList: React.FC = () => {
  const { t } = useTranslation();
  const [projects, setProjects] = useState<Project[]>([]);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = () => {
    api.getProjects().then(setProjects);
  };

  const handleCreate = async (values: any) => {
    try {
      await api.createProject({
        name: values.name,
        description: values.description,
        taskType: values.taskType,
        labels: [],
        alConfig: { strategy: 'random', batchSize: 10 },
        modelConfig: { architecture: 'resnet18' }
      });
      message.success(t('projectList.createSuccess'));
      setIsModalVisible(false);
      form.resetFields();
      loadProjects();
    } catch (error) {
      message.error(t('projectList.createError'));
    }
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={2}>{t('projectList.title')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalVisible(true)}>
          {t('projectList.newProject')}
        </Button>
      </div>
      
      <Row gutter={[16, 16]}>
        {projects.map((project) => (
          <Col xs={24} sm={12} md={8} lg={6} key={project.id}>
            <Card
              hoverable
              title={project.name}
              extra={<Tag color={project.taskType === 'detection' ? 'blue' : 'green'}>{project.taskType}</Tag>}
              actions={[
                <Button type="link" onClick={() => navigate(`/projects/${project.id}`)}>{t('projectList.open')}</Button>,
                <Button type="link" icon={<BarChartOutlined />}>{t('projectList.stats')}</Button>
              ]}
            >
              <Paragraph ellipsis={{ rows: 2 }}>{project.description}</Paragraph>
              <Row gutter={16}>
                <Col span={12}>
                  <Statistic title={t('projectList.labeled')} value={project.stats?.labeledSamples || 0} suffix={`/ ${project.stats?.totalSamples || 0}`} valueStyle={{ fontSize: '16px' }} />
                </Col>
                <Col span={12}>
                  <Statistic title={t('projectList.accuracy')} value={project.stats?.accuracy || 0} precision={2} valueStyle={{ fontSize: '16px', color: '#3f8600' }} />
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      <Modal
        title={t('projectList.newProject')}
        open={isModalVisible}
        onCancel={() => setIsModalVisible(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label={t('projectList.projectName')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label={t('projectList.description')}>
            <Input.TextArea />
          </Form.Item>
          <Form.Item name="taskType" label={t('projectList.taskType')} rules={[{ required: true }]}>
            <Select>
              <Option value="classification">Classification</Option>
              <Option value="detection">Detection</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ProjectList;
