import React, {useEffect, useState} from 'react';
import {Button, Result} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate} from 'react-router-dom';
import {api} from '../../services/api';

const NetworkError: React.FC = () => {
    const {t} = useTranslation();
    const navigate = useNavigate();
    const [isChecking, setIsChecking] = useState(false);

    // 定期检查服务器是否恢复
    useEffect(() => {
        const checkServerStatus = async () => {
            try {
                setIsChecking(true);
                // 尝试调用一个简单的 API 来检查服务器状态
                await api.getSystemStatus();
                // 如果成功，说明服务器已恢复，自动导航回之前的页面或主页
                const returnPath = sessionStorage.getItem('networkErrorReturnPath') || '/';
                sessionStorage.removeItem('networkErrorReturnPath');
                navigate(returnPath, {replace: true});
            } catch (error) {
                // 服务器仍未恢复，继续等待
                setIsChecking(false);
            }
        };

        // 立即检查一次
        checkServerStatus();

        // 每3秒检查一次
        const interval = setInterval(checkServerStatus, 10000);

        return () => {
            clearInterval(interval);
        };
    }, [navigate]);

    const handleRetry = () => {
        const returnPath = sessionStorage.getItem('networkErrorReturnPath') || '/';
        sessionStorage.removeItem('networkErrorReturnPath');
        navigate(returnPath, {replace: true});
    };

    return (
        <div className="flex h-screen items-center justify-center bg-github-panel">
            <Result
                status="500"
                title={t('common.networkErrorTitle')}
                subTitle={
                    isChecking
                        ? t('common.checkingConnection')
                        : t('common.networkError')
                }
                extra={
                    <Button type="primary" onClick={handleRetry} loading={isChecking}>
                        {t('common.retry')}
                    </Button>
                }
            />
        </div>
    );
};

export default NetworkError;
