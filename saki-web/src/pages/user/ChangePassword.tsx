import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import { useAuthStore } from '../../store/authStore';

const { Title } = Typography;

const ChangePassword: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setUser = useAuthStore((state) => state.setUser);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      await api.changePassword(values.oldPassword, values.newPassword);
      // 更新用户信息，清除 must_change_password 标志
      const user = await api.getCurrentUser();
      setUser(user);
      message.success(t('auth.changePassword.success'));
      // 更改密码成功后，跳转到首页
      navigate('/');
    } catch (error: any) {
      message.error(error.message || t('auth.changePassword.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-[#f0f2f5]">
      <Card className="w-[400px]">
        <div className="mb-6 text-center">
          <Title level={2}>{t('auth.changePassword.title')}</Title>
          <Typography.Text type="secondary">{t('auth.changePassword.subtitle')}</Typography.Text>
        </div>
        
        <Form
          name="changePassword"
          onFinish={onFinish}
          size="large"
        >
          <Form.Item
            name="oldPassword"
            label={t('auth.changePassword.oldPassword')}
            rules={[{ required: true, message: t('auth.changePassword.oldPasswordRequired') }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.changePassword.oldPassword')} />
          </Form.Item>

          <Form.Item
            name="newPassword"
            label={t('auth.changePassword.newPassword')}
            rules={[
              { required: true, message: t('auth.changePassword.newPasswordRequired') },
              { min: 6, message: t('auth.changePassword.passwordMinLength') }
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.changePassword.newPassword')} />
          </Form.Item>

          <Form.Item
            name="confirmPassword"
            label={t('auth.changePassword.confirmPassword')}
            dependencies={['newPassword']}
            rules={[
              { required: true, message: t('auth.changePassword.confirmPasswordRequired') },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('auth.changePassword.passwordMismatch')));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder={t('auth.changePassword.confirmPassword')} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {t('auth.changePassword.submit')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default ChangePassword;
