import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Button, Typography, Space, Card, List, Image, Tag, Progress, Tabs } from 'antd';
import { Project, Sample } from '../types';
import { api } from '../services/api';
import { PlayCircleOutlined, HighlightOutlined, UploadOutlined, SettingOutlined } from '@ant-design/icons';
import ProjectSettings from '../components/ProjectSettings';

const { Title } = Typography;
const { Sider, Content } = Layout;

const ProjectDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [activeTab, setActiveTab] = useState('data');

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

  if (!project) return <div>Loading...</div>;

  const items = [
    {
      key: 'data',
      label: 'Data Pool',
      children: (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Title level={5} style={{ flexShrink: 0 }}>Data Pool</Title>
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
      label: 'Settings',
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
          <Card size="small" title="Progress">
            <Progress percent={Math.round((project.stats.labeledSamples / project.stats.totalSamples) * 100)} />
            <div style={{ marginTop: 10 }}>
              Labeled: {project.stats.labeledSamples} / {project.stats.totalSamples}
            </div>
          </Card>
          
          <Button type="primary" block icon={<HighlightOutlined />} onClick={() => navigate(`/workspace/${project.id}`)}>
            Start Labeling
          </Button>
          <Button block icon={<PlayCircleOutlined />}>
            Train Model
          </Button>
          <Button block icon={<UploadOutlined />}>
            Upload Data
          </Button>
          <Button block icon={<SettingOutlined />} onClick={() => setActiveTab('settings')}>
            Settings
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
