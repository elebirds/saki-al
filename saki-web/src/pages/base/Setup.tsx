import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, Steps } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined, RocketOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';

const { Title, Paragraph } = Typography;

const Setup: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      await api.setupSystem(values.email, values.password, values.fullName);
      message.success(t('auth.setup.initializeSuccess'));
      navigate('/login');
    } catch (error: any) {
      message.error(error.message || t('auth.setup.initializeFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 600, padding: '20px' }}>
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <RocketOutlined style={{ fontSize: '48px', color: '#1890ff', marginBottom: '16px' }} />
          <Title level={2}>{t('auth.setup.title')}</Title>
          <Paragraph type="secondary">
            {t('auth.setup.subtitle')}
          </Paragraph>
        </div>

        <Steps
          current={0}
          items={[
            { title: t('auth.setup.stepWelcome'), status: 'finish' },
            { title: t('auth.setup.stepCreateAdmin'), status: 'process' },
            { title: t('auth.setup.stepReady'), status: 'wait' },
          ]}
          style={{ marginBottom: 40 }}
        />
        
        <Form
          name="setup"
          onFinish={onFinish}
          size="large"
          layout="vertical"
        >
          <Form.Item
            name="email"
            label={t('auth.setup.adminEmail')}
            rules={[
              { required: true, message: t('auth.setup.emailRequired') },
              { type: 'email', message: t('auth.setup.emailInvalid') }
            ]}
          >
            <Input prefix={<MailOutlined />} placeholder="admin@example.com" />
          </Form.Item>

          <Form.Item
            name="fullName"
            label={t('auth.setup.fullName')}
            rules={[{ required: true, message: t('auth.setup.fullNameRequired') }]}
          >
            <Input prefix={<UserOutlined />} placeholder="Administrator" />
          </Form.Item>

          <Form.Item
            name="password"
            label={t('auth.setup.password')}
            rules={[{ required: true, message: t('auth.setup.passwordRequired') }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="Strong Password" />
          </Form.Item>
          
          <Form.Item
            name="confirm"
            label={t('auth.setup.confirmPassword')}
            dependencies={['password']}
            hasFeedback
            rules={[
              { required: true, message: t('auth.setup.confirmPasswordRequired') },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('auth.setup.passwordMismatch')));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.setup.confirmPassword')} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} size="large">
              {t('auth.setup.initializeButton')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default Setup;
