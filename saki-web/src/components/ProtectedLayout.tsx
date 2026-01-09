import React from 'react';
import { Layout, Menu, theme, Select, Button } from 'antd';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogoutOutlined } from '@ant-design/icons';
import { useAuthStore } from '../store/authStore';
import { api } from '../services/api';
import { useEffect } from 'react';
import { usePermission } from '../hooks';

const { Header, Content, Footer } = Layout;

const ProtectedLayout: React.FC = () => {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const {
    token: { colorBgContainer },
  } = theme.useToken();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const setToken = useAuthStore((state) => state.setToken);
  
  // Permission check
  const { can, isSuperAdmin } = usePermission();
  const canManageUsers = can('user:read') || isSuperAdmin;

  useEffect(() => {
    let interval: number;
    if (isAuthenticated) {
      // Refresh token every 5 minutes
      interval = setInterval(async () => {
        try {
          console.log('Refreshing token...');
          const response = await api.refreshToken();
          setToken(response.accessToken);
          console.log('Token refreshed');
        } catch (error) {
          console.error('Token refresh failed', error);
          // If refresh fails (e.g. 401), the interceptor will handle logout
        }
      }, 5 * 60 * 1000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isAuthenticated, setToken]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // 如果用户需要更改密码，且不在更改密码页面，强制跳转
  if (user?.mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
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
              ...(canManageUsers
                ? [{ key: '3', label: <Link to="/users">{t('userManagement.title')}</Link> }] 
                : []),
              { key: '2', label: <Link to="/about">{t('app.about')}</Link> },
            ]}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Select
            defaultValue={i18n.language}
            style={{ width: 120 }}
            onChange={changeLanguage}
            options={[
              { value: 'en', label: 'English' },
              { value: 'zh', label: '中文' },
            ]}
          />
          <span style={{ color: 'white' }}>{user?.fullName || user?.email}</span>
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

export default ProtectedLayout;
