import React, { useEffect, useState } from 'react';
import { Modal, Input, Form } from 'antd';

export interface CommitModalProps {
  open: boolean;
  onCancel: () => void;
  onCommit: (message: string) => Promise<void> | void;
  loading?: boolean;
}

const CommitModal: React.FC<CommitModalProps> = ({ open, onCancel, onCommit, loading }) => {
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!open) {
      setMessage('');
    }
  }, [open]);

  return (
    <Modal
      title="Commit Drafts"
      open={open}
      onCancel={onCancel}
      onOk={() => onCommit(message.trim())}
      okText="Commit"
      okButtonProps={{ disabled: message.trim().length === 0, loading }}
      cancelButtonProps={{ disabled: loading }}
    >
      <Form layout="vertical">
        <Form.Item label="Commit message" required>
          <Input.TextArea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Describe this annotation milestone..."
            rows={4}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default CommitModal;
