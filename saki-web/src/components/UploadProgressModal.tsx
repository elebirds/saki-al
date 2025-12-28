import React from 'react';
import { Modal, Progress, List, Tag, Typography, Space, Button } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, FileOutlined } from '@ant-design/icons';
import { UploadProgress, UploadFileResult } from '../types';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

interface UploadProgressModalProps {
  open: boolean;
  progress: UploadProgress;
  onClose: () => void;
  onCancel: () => void;
}

const UploadProgressModal: React.FC<UploadProgressModalProps> = ({
  open,
  progress,
  onClose,
  onCancel,
}) => {
  const { t } = useTranslation();
  const { status, currentFile, totalFiles, percentage, currentFilename, results, error } = progress;

  const isUploading = status === 'uploading';
  const isComplete = status === 'complete';
  const hasError = status === 'error';

  const successCount = results.filter((r) => r.status === 'success').length;
  const errorCount = results.filter((r) => r.status === 'error').length;

  const getTitle = () => {
    if (isComplete) {
      return errorCount > 0 
        ? t('upload.completeWithErrors', { success: successCount, errors: errorCount })
        : t('upload.complete', { count: successCount });
    }
    if (hasError) {
      return t('upload.failed');
    }
    return t('upload.uploading');
  };

  const getStatusIcon = (result: UploadFileResult) => {
    if (result.status === 'success') {
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    }
    return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
  };

  return (
    <Modal
      title={getTitle()}
      open={open}
      onCancel={onClose}
      footer={[
        isUploading && (
          <Button key="cancel" danger onClick={onCancel}>
            {t('upload.cancel')}
          </Button>
        ),
        (isComplete || hasError) && (
          <Button key="close" type="primary" onClick={onClose}>
            {t('upload.close')}
          </Button>
        ),
      ].filter(Boolean)}
      closable={!isUploading}
      maskClosable={!isUploading}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        {/* Overall progress */}
        <div>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
            <Text>
              {isUploading && currentFilename && (
                <>
                  <LoadingOutlined style={{ marginRight: 8 }} />
                  {currentFilename}
                </>
              )}
            </Text>
            <Text type="secondary">
              {currentFile} / {totalFiles}
            </Text>
          </div>
          <Progress 
            percent={Math.round(percentage)} 
            status={hasError ? 'exception' : isComplete ? 'success' : 'active'}
            strokeColor={hasError ? '#ff4d4f' : undefined}
          />
        </div>

        {/* Error message */}
        {hasError && error && (
          <div style={{ 
            padding: '8px 12px', 
            background: '#fff2f0', 
            border: '1px solid #ffccc7',
            borderRadius: 4 
          }}>
            <Text type="danger">{error}</Text>
          </div>
        )}

        {/* File results list */}
        {results.length > 0 && (
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            <List
              size="small"
              dataSource={results}
              renderItem={(item) => (
                <List.Item style={{ padding: '8px 0', display: 'block' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {getStatusIcon(item)}
                    <FileOutlined />
                    <Text ellipsis style={{ maxWidth: 280, flex: 1 }}>{item.filename}</Text>
                    {item.status === 'success' && (
                      <Tag color="success">{t('upload.success')}</Tag>
                    )}
                    {item.status === 'error' && (
                      <Tag color="error">{t('upload.error')}</Tag>
                    )}
                  </div>
                  {/* Show error message below filename */}
                  {item.status === 'error' && item.error && (
                    <div style={{ 
                      marginTop: 4, 
                      marginLeft: 40,
                      padding: '4px 8px',
                      background: '#fff2f0',
                      border: '1px solid #ffccc7',
                      borderRadius: 4,
                      fontSize: 12,
                    }}>
                      <Text type="danger" style={{ fontSize: 12 }}>{item.error}</Text>
                    </div>
                  )}
                </List.Item>
              )}
            />
          </div>
        )}

        {/* Summary when complete */}
        {isComplete && (
          <div style={{ textAlign: 'center', paddingTop: 8 }}>
            <Space size="large">
              <Text>
                <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
                {t('upload.successCount', { count: successCount })}
              </Text>
              {errorCount > 0 && (
                <Text>
                  <CloseCircleOutlined style={{ color: '#ff4d4f', marginRight: 4 }} />
                  {t('upload.errorCount', { count: errorCount })}
                </Text>
              )}
            </Space>
          </div>
        )}
      </Space>
    </Modal>
  );
};

export default UploadProgressModal;
