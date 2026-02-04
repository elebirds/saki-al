import React, { useState } from 'react';
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
    <div className="py-5 text-center">
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.1s] [animation-fill-mode:both]">
        <RocketOutlined className="mb-6 text-[64px] text-[#1890ff]" />
      </div>
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.2s] [animation-fill-mode:both]">
        <Title level={2}>{t('auth.setup.welcomeTitle')}</Title>
      </div>
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.3s] [animation-fill-mode:both]">
        <Paragraph type="secondary" className="mb-8 text-base">
          {t('auth.setup.welcomeDescription')}
        </Paragraph>
      </div>
      
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.4s] [animation-fill-mode:both]">
        <List
          size="large"
          dataSource={[
            t('auth.setup.feature1'),
            t('auth.setup.feature2'),
            t('auth.setup.feature3'),
          ]}
          renderItem={(item, index) => (
            <List.Item
              className="border-0 py-3 animate-[fadeInLeft_0.5s_ease-out] [animation-fill-mode:both]"
              style={{ animationDelay: `${0.5 + index * 0.1}s` }}
            >
              <CheckCircleOutlined className="mr-3 text-[#52c41a]" />
              {item}
            </List.Item>
          )}
          className="mx-auto mb-8 max-w-[400px] text-left"
        />
      </div>

      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.7s] [animation-fill-mode:both]">
        <Button 
          type="primary" 
          size="large" 
          icon={<ArrowRightOutlined />}
          onClick={() => changeStep('createAdmin')}
          className="min-w-[200px]"
        >
          {t('auth.setup.getStarted')}
        </Button>
      </div>
    </div>
  );

  const renderCreateAdminStep = () => (
    <>
      <div
        className="mb-8 text-center animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.1s] [animation-fill-mode:both]"
      >
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

        <Form.Item className="mt-6">
          <div className="flex gap-3">
            <Button 
              onClick={() => changeStep('welcome')}
              className="flex-1"
            >
              {t('auth.setup.back')}
            </Button>
            <Button 
              type="primary" 
              htmlType="submit" 
              loading={loading} 
              className="flex-[2]"
            >
              {t('auth.setup.initializeButton')}
            </Button>
          </div>
        </Form.Item>
      </Form>
    </>
  );

  const renderReadyStep = () => (
    <div className="py-5 text-center">
      <div className="animate-[scaleIn_0.6s_ease-out] [animation-delay:0.1s] [animation-fill-mode:both]">
        <CheckCircleOutlined className="mb-6 text-[64px] text-[#52c41a]" />
      </div>
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.2s] [animation-fill-mode:both]">
        <Title level={2}>{t('auth.setup.readyTitle')}</Title>
      </div>
      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.3s] [animation-fill-mode:both]">
        <Paragraph type="secondary" className="mb-8 text-base">
          {t('auth.setup.readyDescription')}
        </Paragraph>
      </div>
      
      <div
        className="mx-auto mb-8 max-w-[400px] rounded-lg bg-[#f0f2f5] p-6 text-left animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.4s] [animation-fill-mode:both]"
      >
        <Paragraph className="mb-2">
          <strong>{t('auth.setup.readyInfo')}</strong>
        </Paragraph>
        <Paragraph type="secondary" className="text-sm">
          {t('auth.setup.readyHint')}
        </Paragraph>
      </div>

      <div className="animate-[fadeInUp_0.6s_ease-out] [animation-delay:0.5s] [animation-fill-mode:both]">
        <Button 
          type="primary" 
          size="large" 
          onClick={() => navigate('/login')}
          className="min-w-[200px]"
        >
          {t('auth.setup.goToLogin')}
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen items-center justify-center bg-[#f0f2f5]">
      <Card className="w-[600px]">
        <div className="p-10">
          <div className="mb-10">
            <Steps
              current={getCurrentStepIndex()}
              items={[
                { title: t('auth.setup.stepWelcome'), status: currentStep === 'welcome' ? 'process' : currentStep === 'createAdmin' || currentStep === 'ready' ? 'finish' : 'wait' },
                { title: t('auth.setup.stepCreateAdmin'), status: currentStep === 'createAdmin' ? 'process' : currentStep === 'ready' ? 'finish' : 'wait' },
                { title: t('auth.setup.stepReady'), status: currentStep === 'ready' ? 'finish' : 'wait' },
              ]}
            />
          </div>

          <div
            className={`relative min-h-[400px] transition-[opacity,transform] duration-300 ${
              isAnimating ? 'opacity-0 translate-y-5' : 'opacity-100 translate-y-0'
            }`}
          >
            {currentStep === 'welcome' && renderWelcomeStep()}
            {currentStep === 'createAdmin' && renderCreateAdminStep()}
            {currentStep === 'ready' && renderReadyStep()}
          </div>
        </div>
      </Card>
    </div>
  );
};

export default Setup;
