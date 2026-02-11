import React, {useEffect, useState} from 'react';
import {Button, Card, Form, Input, message, Result, Spin, Typography} from 'antd';
import {LockOutlined, MailOutlined, UserOutlined} from '@ant-design/icons';
import {Link, useNavigate} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';

const {Title} = Typography;

const Register: React.FC = () => {
    const {t} = useTranslation();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [allowSelfRegister, setAllowSelfRegister] = useState<boolean | null>(null);

    useEffect(() => {
        let active = true;
        const loadSystemStatus = async () => {
            try {
                const status = await api.getSystemStatus();
                if (active) {
                    setAllowSelfRegister(Boolean(status.allowSelfRegister));
                }
            } catch {
                if (active) {
                    setAllowSelfRegister(false);
                }
            }
        };
        loadSystemStatus();
        return () => {
            active = false;
        };
    }, []);

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

    if (allowSelfRegister === null) {
        return (
            <div className="flex h-screen items-center justify-center bg-[#f0f2f5]">
                <Spin size="large"/>
            </div>
        );
    }

    if (!allowSelfRegister) {
        return (
            <div className="flex h-screen items-center justify-center bg-[#f0f2f5]">
                <Card className="w-[420px]">
                    <Result
                        status="403"
                        title={t('auth.register.disabledTitle')}
                        subTitle={t('auth.register.disabledSubtitle')}
                        extra={
                            <Button type="primary" onClick={() => navigate('/login')}>
                                {t('auth.register.loginLink')}
                            </Button>
                        }
                    />
                </Card>
            </div>
        );
    }

    return (
        <div className="flex h-screen items-center justify-center bg-[#f0f2f5]">
            <Card className="w-[400px]">
                <div className="mb-6 text-center">
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
                            {required: true, message: t('auth.register.emailRequired')},
                            {type: 'email', message: t('auth.register.emailInvalid')}
                        ]}
                    >
                        <Input prefix={<MailOutlined/>} placeholder={t('auth.register.email')}/>
                    </Form.Item>

                    <Form.Item
                        name="fullName"
                        label={t('auth.register.fullName')}
                        rules={[{required: true, message: t('auth.register.fullNameRequired')}]}
                    >
                        <Input prefix={<UserOutlined/>} placeholder={t('auth.register.fullName')}/>
                    </Form.Item>

                    <Form.Item
                        name="password"
                        label={t('auth.register.password')}
                        rules={[{required: true, message: t('auth.register.passwordRequired')}]}
                    >
                        <Input.Password prefix={<LockOutlined/>} placeholder={t('auth.register.password')}/>
                    </Form.Item>

                    <Form.Item
                        name="confirm"
                        label={t('auth.register.confirmPassword')}
                        dependencies={['password']}
                        hasFeedback
                        rules={[
                            {required: true, message: t('auth.register.confirmPasswordRequired')},
                            ({getFieldValue}) => ({
                                validator(_, value) {
                                    if (!value || getFieldValue('password') === value) {
                                        return Promise.resolve();
                                    }
                                    return Promise.reject(new Error(t('auth.register.passwordMismatch')));
                                },
                            }),
                        ]}
                    >
                        <Input.Password prefix={<LockOutlined/>} placeholder={t('auth.register.confirmPassword')}/>
                    </Form.Item>

                    <Form.Item>
                        <Button type="primary" htmlType="submit" block loading={loading}>
                            {t('auth.register.registerButton')}
                        </Button>
                    </Form.Item>

                    <div className="text-center">
                        {t('auth.register.alreadyHaveAccount')} <Link to="/login">{t('auth.register.loginLink')}</Link>
                    </div>
                </Form>
            </Card>
        </div>
    );
};

export default Register;
