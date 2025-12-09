import React, { useEffect, useState } from 'react';
import { Layout, Menu, theme, Select, Button, Spin } from 'antd';
import { BrowserRouter as Router, Routes, Route, Link, Navigate, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogoutOutlined } from '@ant-design/icons';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import AnnotationWorkspace from './pages/AnnotationWorkspace';
import Login from './pages/Login';
import Register from './pages/Register';
import Setup from './pages/Setup';
import { useAuthStore } from './store/authStore';
import { api } from './services/api';

const { Header, Content, Footer } = Layout;

// Component to handle system initialization check
const SystemCheck: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await api.getSystemStatus();
        setInitialized(status.initialized);
        
        // If not initialized and not already on setup page, go to setup
        if (!status.initialized && location.pathname !== '/setup') {
          navigate('/setup');
        }
        // If initialized and trying to access setup, go to login
        if (status.initialized && location.pathname === '/setup') {
          navigate('/login');
        }
      } catch (error) {
        console.error("Failed to check system status", error);
      } finally {
        setLoading(false);
      }
    };
    checkStatus();
  }, [navigate, location.pathname]);

  if (loading) {
    return <div style={{ height: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center' }}><Spin size="large" /></div>;
  }

  return <>{children}</>;
};

const ProtectedLayout: React.FC = () => {
  const { t, i18n } = useTranslation();
  const {
    token: { colorBgContainer },
  } = theme.useToken();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const changeLanguage = (lng: string) => {
    i18n.changeLanguage(lng);
  };

  return (
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ color: 'white' }}>{user?.full_name || user?.email}</span>
          <Select
            defaultValue={i18n.language}
            style={{ width: 120 }}
            onChange={changeLanguage}
            options={[
              { value: 'en', label: 'English' },
              { value: 'zh', label: '中文' },
            ]}
          />
          <Button type="text" icon={<LogoutOutlined />} style={{ color: 'white' }} onClick={logout} />
        </div>
      </Header>
      <Content style={{ padding: '0 50px', marginTop: '20px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="site-layout-content" style={{ background: colorBgContainer, padding: 24, flex: 1, overflow: 'hidden' }}>
          <Outlet />
        </div>
      </Content>
      <Footer style={{ textAlign: 'center', flexShrink: 0 }}>{t('app.footer')}</Footer>
    </Layout>
  );
};

const App: React.FC = () => {
  const { t } = useTranslation();
  return (
    <Router>
      <SystemCheck>
        <Routes>
          <Route path="/setup" element={<Setup />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<ProjectList />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/workspace/:projectId" element={<AnnotationWorkspace />} />
            <Route path="/about" element={<div><h2>{t('app.about')}</h2><p>Saki is a visual active learning framework.</p></div>} />
          </Route>
        </Routes>
      </SystemCheck>
    </Router>
  );
};

export default App;
