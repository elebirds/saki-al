import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, Steps } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined, RocketOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../../services/api';

const { Title, Paragraph } = Typography;

const Setup: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      await api.setupSystem(values.email, values.password, values.fullName);
      message.success('System initialized successfully! Please log in with your admin account.');
      navigate('/login');
    } catch (error: any) {
      message.error(error.message || 'Setup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 600, padding: '20px' }}>
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <RocketOutlined style={{ fontSize: '48px', color: '#1890ff', marginBottom: '16px' }} />
          <Title level={2}>Welcome to Saki</Title>
          <Paragraph type="secondary">
            It looks like this is your first time running Saki. <br />
            Let's set up your administrator account to get started.
          </Paragraph>
        </div>

        <Steps
          current={0}
          items={[
            { title: 'Welcome', status: 'finish' },
            { title: 'Create Admin', status: 'process' },
            { title: 'Ready', status: 'wait' },
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
            label="Admin Email"
            rules={[
              { required: true, message: 'Please input your Email!' },
              { type: 'email', message: 'Please enter a valid email!' }
            ]}
          >
            <Input prefix={<MailOutlined />} placeholder="admin@example.com" />
          </Form.Item>

          <Form.Item
            name="fullName"
            label="Full Name"
            rules={[{ required: true, message: 'Please input your full name!' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="Administrator" />
          </Form.Item>

          <Form.Item
            name="password"
            label="Password"
            rules={[{ required: true, message: 'Please input your Password!' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="Strong Password" />
          </Form.Item>
          
          <Form.Item
            name="confirm"
            label="Confirm Password"
            dependencies={['password']}
            hasFeedback
            rules={[
              { required: true, message: 'Please confirm your password!' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('The two passwords that you entered do not match!'));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="Confirm Password" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} size="large">
              Initialize System
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default Setup;
