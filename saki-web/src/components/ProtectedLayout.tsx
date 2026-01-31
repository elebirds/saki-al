import React from 'react';
import { Layout, Menu, theme, Select, Button, Dropdown } from 'antd';
import { Link, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { useAuthStore } from '../store/authStore';
import { api } from '../services/api';
import { useEffect } from 'react';
import { usePermission } from '../hooks';

const { Header, Content, Footer } = Layout;

const ProtectedLayout: React.FC = () => {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
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
  const canManageRoles = can('role:read') || isSuperAdmin;

  useEffect(() => {
    let interval: number;
    if (isAuthenticated) {
      // Refresh token every 5 minutes
      interval = setInterval(async () => {
        try {
          console.log('Refreshing token...');
          const response = await api.refreshToken();
          const setTokens = useAuthStore.getState().setTokens;
          setTokens(response.accessToken, response.refreshToken);
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
  }, [isAuthenticated]);

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

  // 根据当前路径确定选中的菜单项
  const getSelectedKeys = () => {
    const pathname = location.pathname;
    if (pathname === '/users') {
      return ['3'];
    } else if (pathname === '/roles') {
      return ['4'];
    } else if (pathname === '/about') {
      return ['2'];
    } else if (pathname === '/' || pathname.startsWith('/datasets') || pathname.startsWith('/workspace')) {
      return ['1'];
    }
    // 默认选中数据集
    return ['1'];
  };

  // Handle user menu click
  const handleUserMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'profile') {
      navigate('/profile');
    } else if (key === 'logout') {
      logout();
    }
  };

  // User menu items
  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: t('userProfile.title'),
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t('auth.logout'),
    },
  ];

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
            selectedKeys={getSelectedKeys()}
            items={[
              { key: '1', label: <Link to="/">{t('app.datasets')}</Link> },
              ...(canManageUsers
                ? [{ key: '3', label: <Link to="/users">{t('userManagement.title')}</Link> }] 
                : []),
              ...(canManageRoles
                ? [{ key: '4', label: <Link to="/roles">{t('roleManagement.title')}</Link> }] 
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
          <Dropdown menu={{ items: userMenuItems, onClick: handleUserMenuClick }} placement="bottomRight">
            <Button type="text" style={{ color: 'white', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <UserOutlined />
              <span>{user?.fullName || user?.email}</span>
            </Button>
          </Dropdown>
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
