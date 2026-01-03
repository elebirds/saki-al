import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../store/authStore';
import { api } from '../../services/api';

const { Title } = Typography;

const Login: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setToken = useAuthStore((state) => state.setToken);
  const setUser = useAuthStore((state) => state.setUser);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const loginResponse = await api.login(values.email, values.password);
      setToken(loginResponse.accessToken);
      
      // Fetch user details
      const user = await api.getCurrentUser();
      setUser(user);
      
      // 如果用户需要更改密码，跳转到更改密码页面
      if (loginResponse.mustChangePassword) {
        message.warning(t('auth.login.mustChangePassword'));
        navigate('/change-password');
        return;
      }
      
      message.success(t('auth.login.loginSuccess'));
      navigate('/');
    } catch (error: any) {
      message.error(error.message || t('auth.login.loginFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={2}>{t('app.title')}</Title>
          <Typography.Text type="secondary">{t('auth.login.subtitle')}</Typography.Text>
        </div>
        
        <Form
          name="login"
          initialValues={{ remember: true }}
          onFinish={onFinish}
          size="large"
        >
          <Form.Item
            name="email"
            rules={[{ required: true, message: t('auth.login.emailRequired') }]}
          >
            <Input prefix={<UserOutlined />} placeholder={t('auth.login.email')} />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t('auth.login.passwordRequired') }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.login.password')} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {t('auth.login.loginButton')}
            </Button>
          </Form.Item>
          
          <div style={{ textAlign: 'center' }}>
            {t('auth.login.or')} <Link to="/register">{t('auth.login.registerLink')}</Link>
          </div>
        </Form>
      </Card>
    </div>
  );
};

export default Login;
