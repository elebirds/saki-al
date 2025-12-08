import React from 'react';
import { Layout, Menu, theme } from 'antd';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import AnnotationWorkspace from './pages/AnnotationWorkspace';

const { Header, Content, Footer } = Layout;

const App: React.FC = () => {
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  return (
    <Router>
      <Layout className="layout" style={{ minHeight: '100vh' }}>
        <Header style={{ display: 'flex', alignItems: 'center' }}>
          <div className="demo-logo" style={{ color: 'white', fontSize: '20px', fontWeight: 'bold', marginRight: '20px' }}>
            Saki AL
          </div>
          <Menu
            theme="dark"
            mode="horizontal"
            defaultSelectedKeys={['1']}
            items={[
              { key: '1', label: <Link to="/">Projects</Link> },
              { key: '2', label: <Link to="/about">About</Link> },
            ]}
          />
        </Header>
        <Content style={{ padding: '0 50px', marginTop: '20px' }}>
          <div className="site-layout-content" style={{ background: colorBgContainer, padding: 24, minHeight: 380 }}>
            <Routes>
              <Route path="/" element={<ProjectList />} />
              <Route path="/projects/:id" element={<ProjectDetail />} />
              <Route path="/workspace/:projectId" element={<AnnotationWorkspace />} />
              <Route path="/about" element={<div><h2>About</h2><p>Saki is a visual active learning framework.</p></div>} />
            </Routes>
          </div>
        </Content>
        <Footer style={{ textAlign: 'center' }}>Saki Active Learning ©2023 Created by GitHub Copilot</Footer>
      </Layout>
    </Router>
  );
};

export default App;
