import React, {useEffect, useState} from 'react';
import {Form, Input, Modal} from 'antd';
import {useTranslation} from 'react-i18next';

export interface CommitModalProps {
    open: boolean;
    onCancel: () => void;
    onCommit: (message: string) => Promise<void> | void;
    loading?: boolean;
}

const CommitModal: React.FC<CommitModalProps> = ({open, onCancel, onCommit, loading}) => {
    const {t} = useTranslation();
    const [message, setMessage] = useState('');

    useEffect(() => {
        if (!open) {
            setMessage('');
        }
    }, [open]);

    return (
        <Modal
            title={t('project.samples.commitModal.title')}
            open={open}
            onCancel={onCancel}
            onOk={() => onCommit(message.trim())}
            okText={t('project.samples.commitModal.commit')}
            okButtonProps={{disabled: message.trim().length === 0, loading}}
            cancelButtonProps={{disabled: loading}}
        >
            <Form layout="vertical">
                <Form.Item label={t('project.samples.commitModal.messageLabel')} required>
                    <Input.TextArea
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        placeholder={t('project.samples.commitModal.messagePlaceholder')}
                        rows={4}
                    />
                </Form.Item>
            </Form>
        </Modal>
    );
};

export default CommitModal;
