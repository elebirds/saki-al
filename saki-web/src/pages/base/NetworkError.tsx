import React from 'react';
import { Result, Button } from 'antd';
import { useTranslation } from 'react-i18next';

const NetworkError: React.FC = () => {
  const { t } = useTranslation();

  const handleRetry = () => {
    window.location.href = '/';
  };

  return (
    <div style={{ 
      height: '100vh', 
      display: 'flex', 
      justifyContent: 'center', 
      alignItems: 'center',
      background: '#f0f2f5'
    }}>
      <Result
        status="500"
        title="Network Error"
        subTitle={t('common.networkError', 'Cannot connect to the server. Please check your network connection or try again later.')}
        extra={
          <Button type="primary" onClick={handleRetry}>
            {t('common.retry', 'Retry')}
          </Button>
        }
      />
    </div>
  );
};

export default NetworkError;
