import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Tag, Button, Typography, Space } from 'antd';
import { useNavigate } from 'react-router-dom';
import { Project } from '../types';
import { api } from '../services/api';
import { PlusOutlined, BarChartOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const ProjectList: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    api.getProjects().then(setProjects);
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={2}>Projects</Title>
        <Button type="primary" icon={<PlusOutlined />}>
          New Project
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
                <Button type="link" onClick={() => navigate(`/projects/${project.id}`)}>Open</Button>,
                <Button type="link" icon={<BarChartOutlined />}>Stats</Button>
              ]}
            >
              <Paragraph ellipsis={{ rows: 2 }}>{project.description}</Paragraph>
              <Row gutter={16}>
                <Col span={12}>
                  <Statistic title="Labeled" value={project.stats.labeledSamples} suffix={`/ ${project.stats.totalSamples}`} valueStyle={{ fontSize: '16px' }} />
                </Col>
                <Col span={12}>
                  <Statistic title="Accuracy" value={project.stats.accuracy} precision={2} valueStyle={{ fontSize: '16px', color: '#3f8600' }} />
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
};

export default ProjectList;
