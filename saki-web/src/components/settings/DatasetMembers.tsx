import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Select, message, Space, Popconfirm, Tag, Typography } from 'antd';
import { UserAddOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { DatasetMember, DatasetMemberCreate, DatasetMemberUpdate, ResourceRole, User } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../store/authStore';

const { Title } = Typography;

interface DatasetMembersProps {
  datasetId: string;
}

const DatasetMembers: React.FC<DatasetMembersProps> = ({ datasetId }) => {
  const { t } = useTranslation();
  const currentUser = useAuthStore((state) => state.user);
  const [members, setMembers] = useState<DatasetMember[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingMember, setEditingMember] = useState<DatasetMember | null>(null);
  const [form] = Form.useForm();

  const fetchMembers = async () => {
    setLoading(true);
    try {
      const data = await api.getDatasetMembers(datasetId);
      setMembers(data);
    } catch (error: any) {
      message.error(error.message || t('Failed to fetch members'));
    } finally {
      setLoading(false);
    }
  };

  const fetchUsers = async () => {
    try {
      const data = await api.getUsers();
      setUsers(data);
    } catch (error) {
      console.error('Failed to fetch users:', error);
    }
  };

  useEffect(() => {
    fetchMembers();
    fetchUsers();
  }, [datasetId]);

  const handleAdd = () => {
    setEditingMember(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (member: DatasetMember) => {
    setEditingMember(member);
    form.setFieldsValue({
      role: member.role,
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (userId: string) => {
    try {
      await api.removeDatasetMember(datasetId, userId);
      message.success(t('Member removed successfully'));
      fetchMembers();
    } catch (error: any) {
      message.error(error.message || t('Failed to remove member'));
    }
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingMember) {
        await api.updateDatasetMemberRole(datasetId, editingMember.userId, { role: values.role });
        message.success(t('Member role updated successfully'));
      } else {
        await api.addDatasetMember(datasetId, { userId: values.userId, role: values.role });
        message.success(t('Member added successfully'));
      }
      setIsModalOpen(false);
      fetchMembers();
    } catch (error: any) {
      message.error(error.message || t('Operation failed'));
    }
  };

  const roleColors: Record<ResourceRole, string> = {
    'owner': 'red',
    'manager': 'gold',
    'annotator': 'blue',
    'reviewer': 'cyan',
    'viewer': 'default',
  };

  const roleLabels: Record<ResourceRole, string> = {
    'owner': t('Owner'),
    'manager': t('Manager'),
    'annotator': t('Annotator'),
    'reviewer': t('Reviewer'),
    'viewer': t('Viewer'),
  };

  // Get member user IDs to filter available users
  const memberUserIds = new Set(members.map(m => m.userId));

  const columns = [
    {
      title: t('Email'),
      dataIndex: 'userEmail',
      key: 'userEmail',
    },
    {
      title: t('Full Name'),
      dataIndex: 'userFullName',
      key: 'userFullName',
    },
    {
      title: t('Role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: ResourceRole) => (
        <Tag color={roleColors[role]}>
          {roleLabels[role]}
        </Tag>
      ),
    },
    {
      title: t('Actions'),
      key: 'action',
      render: (_: any, record: DatasetMember) => (
        <Space size="middle">
          <Button 
            type="link" 
            icon={<EditOutlined />} 
            onClick={() => handleEdit(record)}
            disabled={record.role === 'owner'}
          >
            {t('Edit')}
          </Button>
          <Popconfirm
            title={t('Are you sure to remove this member?')}
            onConfirm={() => handleDelete(record.userId)}
            okText={t('Yes')}
            cancelText={t('No')}
            disabled={record.role === 'owner'}
          >
            <Button 
              type="link" 
              danger 
              icon={<DeleteOutlined />}
              disabled={record.role === 'owner'}
            >
              {t('Remove')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={5}>{t('Dataset Members')}</Title>
        <Button type="primary" icon={<UserAddOutlined />} onClick={handleAdd}>
          {t('Add Member')}
        </Button>
      </div>
      <Table 
        columns={columns} 
        dataSource={members} 
        rowKey="userId" 
        loading={loading}
        pagination={false}
      />

      <Modal
        title={editingMember ? t('Edit Member Role') : t('Add Member')}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={() => setIsModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          {!editingMember && (
            <Form.Item
              name="userId"
              label={t('User')}
              rules={[{ required: true, message: t('Please select a user!') }]}
            >
              <Select
                showSearch
                placeholder={t('Select a user')}
                optionFilterProp="children"
                filterOption={(input, option) =>
                  (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                }
                options={users
                  .filter(u => !memberUserIds.has(u.id))
                  .map(u => ({
                    value: u.id,
                    label: `${u.email}${u.fullName ? ` (${u.fullName})` : ''}`,
                  }))}
              />
            </Form.Item>
          )}
          <Form.Item
            name="role"
            label={t('Role')}
            rules={[{ required: true, message: t('Please select a role!') }]}
            initialValue="viewer"
          >
            <Select disabled={editingMember?.role === 'owner'}>
              <Select.Option value="viewer">{t('Viewer')}</Select.Option>
              <Select.Option value="reviewer">{t('Reviewer')}</Select.Option>
              <Select.Option value="annotator">{t('Annotator')}</Select.Option>
              <Select.Option value="manager">{t('Manager')}</Select.Option>
              {!editingMember && (
                <Select.Option value="owner">{t('Owner')}</Select.Option>
              )}
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default DatasetMembers;

