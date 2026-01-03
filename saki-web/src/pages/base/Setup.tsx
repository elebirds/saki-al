import React, { useState, useEffect } from 'react';
import { Form, Input, Button, Card, Typography, message, Steps, List } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined, RocketOutlined, CheckCircleOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';

const { Title, Paragraph } = Typography;

type SetupStep = 'welcome' | 'createAdmin' | 'ready';

const Setup: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState<SetupStep>('welcome');
  const [loading, setLoading] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);
  const [form] = Form.useForm();

  // 处理步骤切换动画
  const changeStep = (newStep: SetupStep) => {
    setIsAnimating(true);
    setTimeout(() => {
      setCurrentStep(newStep);
      setTimeout(() => {
        setIsAnimating(false);
      }, 50); // 短暂延迟后开始淡入
    }, 300); // 淡出动画时间
  };

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      await api.setupSystem(values.email, values.password, values.fullName);
      changeStep('ready');
    } catch (error: any) {
      message.error(error.message || t('auth.setup.initializeFailed'));
    } finally {
      setLoading(false);
    }
  };

  const getCurrentStepIndex = () => {
    switch (currentStep) {
      case 'welcome': return 0;
      case 'createAdmin': return 1;
      case 'ready': return 2;
      default: return 0;
    }
  };

  const renderWelcomeStep = () => (
    <div style={{ textAlign: 'center', padding: '20px 0' }}>
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.1s',
        animationFillMode: 'both'
      }}>
        <RocketOutlined style={{ fontSize: '64px', color: '#1890ff', marginBottom: '24px' }} />
      </div>
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.2s',
        animationFillMode: 'both'
      }}>
        <Title level={2}>{t('auth.setup.welcomeTitle')}</Title>
      </div>
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.3s',
        animationFillMode: 'both'
      }}>
        <Paragraph type="secondary" style={{ fontSize: '16px', marginBottom: '32px' }}>
          {t('auth.setup.welcomeDescription')}
        </Paragraph>
      </div>
      
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.4s',
        animationFillMode: 'both'
      }}>
        <List
          size="large"
          dataSource={[
            t('auth.setup.feature1'),
            t('auth.setup.feature2'),
            t('auth.setup.feature3'),
          ]}
          renderItem={(item, index) => (
            <List.Item style={{ 
              border: 'none', 
              padding: '12px 0',
              animation: 'fadeInLeft 0.5s ease-out',
              animationDelay: `${0.5 + index * 0.1}s`,
              animationFillMode: 'both'
            }}>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: '12px' }} />
              {item}
            </List.Item>
          )}
          style={{ marginBottom: '32px', textAlign: 'left', maxWidth: '400px', margin: '0 auto 32px' }}
        />
      </div>

      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.7s',
        animationFillMode: 'both'
      }}>
        <Button 
          type="primary" 
          size="large" 
          icon={<ArrowRightOutlined />}
          onClick={() => changeStep('createAdmin')}
          style={{ minWidth: '200px' }}
        >
          {t('auth.setup.getStarted')}
        </Button>
      </div>
    </div>
  );

  const renderCreateAdminStep = () => (
    <>
      <div style={{ 
        textAlign: 'center', 
        marginBottom: '32px',
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.1s',
        animationFillMode: 'both'
      }}>
        <Title level={3}>{t('auth.setup.createAdminTitle')}</Title>
        <Paragraph type="secondary">
          {t('auth.setup.createAdminDescription')}
        </Paragraph>
      </div>

      <Form
        form={form}
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
          rules={[
            { required: true, message: t('auth.setup.passwordRequired') },
            { min: 6, message: t('auth.setup.passwordMinLength') }
          ]}
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

        <Form.Item style={{ marginTop: '24px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <Button 
              onClick={() => changeStep('welcome')}
              style={{ flex: 1 }}
            >
              {t('auth.setup.back')}
            </Button>
            <Button 
              type="primary" 
              htmlType="submit" 
              loading={loading} 
              style={{ flex: 2 }}
            >
              {t('auth.setup.initializeButton')}
            </Button>
          </div>
        </Form.Item>
      </Form>
    </>
  );

  const renderReadyStep = () => (
    <div style={{ textAlign: 'center', padding: '20px 0' }}>
      <div style={{
        animation: 'scaleIn 0.6s ease-out',
        animationDelay: '0.1s',
        animationFillMode: 'both'
      }}>
        <CheckCircleOutlined style={{ fontSize: '64px', color: '#52c41a', marginBottom: '24px' }} />
      </div>
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.2s',
        animationFillMode: 'both'
      }}>
        <Title level={2}>{t('auth.setup.readyTitle')}</Title>
      </div>
      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.3s',
        animationFillMode: 'both'
      }}>
        <Paragraph type="secondary" style={{ fontSize: '16px', marginBottom: '32px' }}>
          {t('auth.setup.readyDescription')}
        </Paragraph>
      </div>
      
      <div style={{ 
        background: '#f0f2f5', 
        padding: '24px', 
        borderRadius: '8px', 
        marginBottom: '32px',
        textAlign: 'left',
        maxWidth: '400px',
        margin: '0 auto 32px',
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.4s',
        animationFillMode: 'both'
      }}>
        <Paragraph style={{ marginBottom: '8px' }}>
          <strong>{t('auth.setup.readyInfo')}</strong>
        </Paragraph>
        <Paragraph type="secondary" style={{ fontSize: '14px' }}>
          {t('auth.setup.readyHint')}
        </Paragraph>
      </div>

      <div style={{
        animation: 'fadeInUp 0.6s ease-out',
        animationDelay: '0.5s',
        animationFillMode: 'both'
      }}>
        <Button 
          type="primary" 
          size="large" 
          onClick={() => navigate('/login')}
          style={{ minWidth: '200px' }}
        >
          {t('auth.setup.goToLogin')}
        </Button>
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 600, padding: '40px' }}>
        <Steps
          current={getCurrentStepIndex()}
          items={[
            { title: t('auth.setup.stepWelcome'), status: currentStep === 'welcome' ? 'process' : currentStep === 'createAdmin' || currentStep === 'ready' ? 'finish' : 'wait' },
            { title: t('auth.setup.stepCreateAdmin'), status: currentStep === 'createAdmin' ? 'process' : currentStep === 'ready' ? 'finish' : 'wait' },
            { title: t('auth.setup.stepReady'), status: currentStep === 'ready' ? 'finish' : 'wait' },
          ]}
          style={{ marginBottom: '40px' }}
        />

        <div
          style={{
            minHeight: '400px',
            position: 'relative',
            transition: 'opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
            opacity: isAnimating ? 0 : 1,
            transform: isAnimating ? 'translateY(20px)' : 'translateY(0)',
          }}
        >
          {currentStep === 'welcome' && renderWelcomeStep()}
          {currentStep === 'createAdmin' && renderCreateAdminStep()}
          {currentStep === 'ready' && renderReadyStep()}
        </div>
      </Card>
    </div>
  );
};

export default Setup;
