import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';

const { Title } = Typography;

const Register: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      await api.register(values.email, values.password, values.fullName);
      message.success(t('auth.register.registerSuccess'));
      navigate('/login');
    } catch (error: any) {
      message.error(error.message || t('auth.register.registerFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={2}>{t('auth.register.title')}</Title>
          <Typography.Text type="secondary">{t('auth.register.subtitle')}</Typography.Text>
        </div>
        
        <Form
          name="register"
          onFinish={onFinish}
          size="large"
          layout="vertical"
        >
          <Form.Item
            name="email"
            label={t('auth.register.email')}
            rules={[
              { required: true, message: t('auth.register.emailRequired') },
              { type: 'email', message: t('auth.register.emailInvalid') }
            ]}
          >
            <Input prefix={<MailOutlined />} placeholder={t('auth.register.email')} />
          </Form.Item>

          <Form.Item
            name="fullName"
            label={t('auth.register.fullName')}
            rules={[{ required: true, message: t('auth.register.fullNameRequired') }]}
          >
            <Input prefix={<UserOutlined />} placeholder={t('auth.register.fullName')} />
          </Form.Item>

          <Form.Item
            name="password"
            label={t('auth.register.password')}
            rules={[{ required: true, message: t('auth.register.passwordRequired') }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.register.password')} />
          </Form.Item>
          
          <Form.Item
            name="confirm"
            label={t('auth.register.confirmPassword')}
            dependencies={['password']}
            hasFeedback
            rules={[
              { required: true, message: t('auth.register.confirmPasswordRequired') },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('auth.register.passwordMismatch')));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.register.confirmPassword')} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {t('auth.register.registerButton')}
            </Button>
          </Form.Item>
          
          <div style={{ textAlign: 'center' }}>
            {t('auth.register.alreadyHaveAccount')} <Link to="/login">{t('auth.register.loginLink')}</Link>
          </div>
        </Form>
      </Card>
    </div>
  );
};

export default Register;
