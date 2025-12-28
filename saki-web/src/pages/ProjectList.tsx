import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Tag, Button, Typography, Modal, Form, Input, Select, message, Spin, Tooltip } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Project, AnnotationSystemType } from '../types';
import { api } from '../services/api';
import { useSystemCapabilities } from '../hooks';
import { PlusOutlined, BarChartOutlined, InfoCircleOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;
const { Option } = Select;

const ProjectList: React.FC = () => {
  const { t } = useTranslation();
  const [projects, setProjects] = useState<Project[]>([]);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();
  
  // Load available types from backend
  const { availableTypes, loading: typesLoading } = useSystemCapabilities();

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
        annotationSystem: values.annotationSystem as AnnotationSystemType,
        labels: [],
        queryStrategyId: 'least_confidence', // Default
        baseModelId: values.taskType === 'classification' ? 'resnet50' : 'yolov5', // Default
        alConfig: { batchSize: 10 },
        modelConfig: {},
        annotationConfig: {},
      });
      message.success(t('projectList.createSuccess'));
      setIsModalVisible(false);
      form.resetFields();
      loadProjects();
    } catch (error) {
      message.error(t('projectList.createError'));
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
              extra={
                <span>
                  <Tag color={project.taskType === 'detection' ? 'blue' : 'green'}>{project.taskType || 'classification'}</Tag>
                  <Tag color={getAnnotationSystemColor(project.annotationSystem)}>{project.annotationSystem || 'classic'}</Tag>
                </span>
              }
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
        {typesLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <Spin tip={t('common.loading')} />
          </div>
        ) : (
          <Form form={form} layout="vertical" onFinish={handleCreate} initialValues={{ taskType: 'classification', annotationSystem: 'classic' }}>
            <Form.Item name="name" label={t('projectList.projectName')} rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="description" label={t('projectList.description')}>
              <Input.TextArea />
            </Form.Item>
            <Form.Item 
              name="taskType" 
              label={
                <span>
                  {t('projectList.taskType')}&nbsp;
                  <Tooltip title={t('projectList.taskTypeHelp')}>
                    <InfoCircleOutlined style={{ color: '#999' }} />
                  </Tooltip>
                </span>
              } 
              rules={[{ required: true }]}
            >
              <Select>
                {availableTypes?.taskTypes.map(type => (
                  <Option key={type.value} value={type.value}>
                    <Tooltip title={type.description} placement="right">
                      {type.label}
                    </Tooltip>
                  </Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item 
              name="annotationSystem" 
              label={
                <span>
                  {t('projectList.annotationSystem')}&nbsp;
                  <Tooltip title={t('projectList.annotationSystemHelp')}>
                    <InfoCircleOutlined style={{ color: '#999' }} />
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

export default ProjectList;
