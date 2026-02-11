import React from 'react';
import {Button, List, Modal, Progress, Tag, Typography} from 'antd';
import {CheckCircleOutlined, CloseCircleOutlined, FileOutlined, LoadingOutlined} from '@ant-design/icons';
import {UploadFileResult, UploadProgress} from '../types';
import {useTranslation} from 'react-i18next';

const {Text} = Typography;

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
    const {t} = useTranslation();
    const {status, currentFile, totalFiles, percentage, currentFilename, results, error} = progress;

    const isUploading = status === 'uploading';
    const isComplete = status === 'complete';
    const hasError = status === 'error';

    const successCount = results.filter((r) => r.status === 'success').length;
    const errorCount = results.filter((r) => r.status === 'error').length;

    const getTitle = () => {
        if (isComplete) {
            return errorCount > 0
                ? t('upload.completeWithErrors', {success: successCount, errors: errorCount})
                : t('upload.complete', {count: successCount});
        }
        if (hasError) {
            return t('upload.failed');
        }
        return t('upload.uploading');
    };

    const getStatusIcon = (result: UploadFileResult) => {
        if (result.status === 'success') {
            return <CheckCircleOutlined className="text-green-500"/>;
        }
        return <CloseCircleOutlined className="text-red-500"/>;
    };

    return (
        <Modal
            title={getTitle()}
            open={open}
            onCancel={onClose}
            width={820}
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
            <div className="flex w-full flex-col gap-6">
                {/* Overall progress */}
                <div>
                    <div className="mb-2 flex justify-between">
                        <Text>
                            {isUploading && currentFilename && (
                                <>
                                    <LoadingOutlined className="mr-2"/>
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
                    <div className="rounded border border-[#ffccc7] bg-[#fff2f0] px-3 py-2">
                        <Text type="danger">{error}</Text>
                    </div>
                )}

                {/* File results list */}
                {results.length > 0 && (
                    <div className="max-h-[300px] overflow-y-auto">
                        <List
                            size="small"
                            dataSource={results}
                            renderItem={(item) => (
                                <List.Item className="block py-2">
                                    <div className="flex items-center gap-2">
                                        {getStatusIcon(item)}
                                        <FileOutlined/>
                                        <Text ellipsis className="max-w-[560px] flex-1">
                                            {item.filename}
                                        </Text>
                                        {item.status === 'success' && (
                                            <Tag color="success">{t('upload.success')}</Tag>
                                        )}
                                        {item.status === 'error' && (
                                            <Tag color="error">{t('upload.error')}</Tag>
                                        )}
                                    </div>
                                    {/* Show error message below filename */}
                                    {item.status === 'error' && item.error && (
                                        <div
                                            className="ml-10 mt-1 rounded border border-[#ffccc7] bg-[#fff2f0] px-2 py-1 text-xs">
                                            <Text type="danger" className="text-xs">
                                                {item.error}
                                            </Text>
                                        </div>
                                    )}
                                </List.Item>
                            )}
                        />
                    </div>
                )}

                {/* Summary when complete */}
                {isComplete && (
                    <div className="pt-2 text-center">
                        <div className="flex flex-wrap items-center justify-center gap-6">
                            <Text>
                                <CheckCircleOutlined className="mr-1 text-green-500"/>
                                {t('upload.successCount', {count: successCount})}
                            </Text>
                            {errorCount > 0 && (
                                <Text>
                                    <CloseCircleOutlined className="mr-1 text-red-500"/>
                                    {t('upload.errorCount', {count: errorCount})}
                                </Text>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </Modal>
    );
};

export default UploadProgressModal;
