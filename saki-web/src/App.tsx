import React from 'react';
import { Layout, Menu, theme, Select } from 'antd';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import AnnotationWorkspace from './pages/AnnotationWorkspace';

const { Header, Content, Footer } = Layout;

const App: React.FC = () => {
  const { t, i18n } = useTranslation();
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  const changeLanguage = (lng: string) => {
    i18n.changeLanguage(lng);
  };

  return (
    <Router>
      <Layout className="layout" style={{ height: '100vh', overflow: 'hidden' }}>
        <Header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div className="demo-logo" style={{ color: 'white', fontSize: '20px', fontWeight: 'bold', marginRight: '20px' }}>
              {t('app.title')}
            </div>
            <Menu
              theme="dark"
              mode="horizontal"
              defaultSelectedKeys={['1']}
              items={[
                { key: '1', label: <Link to="/">{t('app.projects')}</Link> },
                { key: '2', label: <Link to="/about">{t('app.about')}</Link> },
              ]}
            />
          </div>
          <Select
            defaultValue={i18n.language}
            style={{ width: 120 }}
            onChange={changeLanguage}
            options={[
              { value: 'en', label: 'English' },
              { value: 'zh', label: '中文' },
            ]}
          />
        </Header>
        <Content style={{ padding: '0 50px', marginTop: '20px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div className="site-layout-content" style={{ background: colorBgContainer, padding: 24, flex: 1, overflow: 'hidden' }}>
            <Routes>
              <Route path="/" element={<ProjectList />} />
              <Route path="/projects/:id" element={<ProjectDetail />} />
              <Route path="/workspace/:projectId" element={<AnnotationWorkspace />} />
              <Route path="/about" element={<div><h2>{t('app.about')}</h2><p>Saki is a visual active learning framework.</p></div>} />
            </Routes>
          </div>
        </Content>
        <Footer style={{ textAlign: 'center', flexShrink: 0 }}>{t('app.footer')}</Footer>
      </Layout>
    </Router>
  );
};

export default App;
