import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Typography, Space, Card, List, Tag, Progress, Tabs, message } from 'antd';
import { useTranslation } from 'react-i18next';
import { Project, Sample } from '../types';
import { api } from '../services/api';
import { PlayCircleOutlined, HighlightOutlined, UploadOutlined, SettingOutlined } from '@ant-design/icons';
import ProjectSettings from '../components/ProjectSettings';

const { Title } = Typography;
const { Sider, Content } = Layout;

const ProjectDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [activeTab, setActiveTab] = useState('data');
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (id) {
      api.getProject(id).then((p) => {
        if (p) setProject(p);
      });
      api.getSamples(id).then(setSamples);
    }
  }, [id]);

  const handleProjectUpdate = (updatedProject: Project) => {
    setProject(updatedProject);
    // In a real app, we would also trigger a refetch or update the backend here if not done in the component
  };

  const handleTrain = async () => {
    if (!project) return;
    try {
      await api.trainProject(project.id);
      message.success('Training started');
    } catch (error) {
      message.error('Failed to start training');
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!project || !e.target.files || e.target.files.length === 0) return;
    try {
      await api.uploadSamples(project.id, Array.from(e.target.files));
      message.success('Samples uploaded');
      // Refresh samples
      api.getSamples(project.id).then(setSamples);
    } catch (error) {
      message.error('Failed to upload samples');
    }
  };

  if (!project) return <div>{t('workspace.loading')}</div>;

  const items = [
    {
      key: 'data',
      label: t('projectDetail.dataPool'),
      children: (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Title level={5} style={{ flexShrink: 0 }}>{t('projectDetail.dataPool')}</Title>
          <div style={{ flex: 1, overflowY: 'auto', paddingRight: '10px' }}>
            <List
              grid={{
                gutter: 16,
                xs: 1,
                sm: 2,
                md: 2,
                lg: 3,
                xl: 4,
                xxl: 4,
              }}
              dataSource={samples}
              renderItem={(item) => (
                <List.Item>
                  <Card
                    hoverable
                    cover={<img alt="example" src={item.url} style={{ height: 150, objectFit: 'cover' }} />}
                    size="small"
                  >
                    <Card.Meta 
                      title={<Tag color={item.status === 'labeled' ? 'green' : 'orange'}>{item.status}</Tag>}
                      description={`Score: ${item.score?.toFixed(4)}`}
                    />
                  </Card>
                </List.Item>
              )}
            />
          </div>
        </div>
      ),
    },
    {
      key: 'settings',
      label: t('projectDetail.settings'),
      children: (
        <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }}>
          <ProjectSettings project={project} onUpdate={handleProjectUpdate} />
        </div>
      ),
    },
  ];

  return (
    <Layout style={{ background: '#fff', height: '100%' }}>
      <Sider width={300} theme="light" style={{ borderRight: '1px solid #f0f0f0', padding: '20px', overflowY: 'auto' }}>
        <Title level={4}>{project.name}</Title>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Card size="small" title={t('projectDetail.progress')}>
            <Progress percent={Math.round((project.stats.labeledSamples / project.stats.totalSamples) * 100)} />
            <div style={{ marginTop: 10 }}>
              {t('projectDetail.labeled')}: {project.stats.labeledSamples} / {project.stats.totalSamples}
            </div>
          </Card>
          
          <Button type="primary" block icon={<HighlightOutlined />} onClick={() => navigate(`/workspace/${project.id}`)}>
            {t('projectDetail.startLabeling')}
          </Button>
          <Button block icon={<PlayCircleOutlined />} onClick={handleTrain}>
            {t('projectDetail.trainModel')}
          </Button>
          <Button block icon={<UploadOutlined />} onClick={handleUploadClick}>
            {t('projectDetail.uploadData')}
          </Button>
          <input 
            type="file" 
            ref={fileInputRef} 
            style={{ display: 'none' }} 
            multiple 
            accept="image/*" 
            onChange={handleFileChange} 
          />
          <Button block icon={<SettingOutlined />} onClick={() => setActiveTab('settings')}>
            {t('projectDetail.settings')}
          </Button>
        </Space>
      </Sider>
      <Content style={{ padding: '24px', height: '100%', overflow: 'hidden' }}>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} className="full-height-tabs" />
      </Content>
    </Layout>
  );
};

export default ProjectDetail;
