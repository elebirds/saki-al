import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Select, message, Space, Popconfirm, Tag, Typography } from 'antd';
import { UserAddOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { DatasetMember, ResourceRole, User } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';

const { Title } = Typography;

interface DatasetMembersProps {
  datasetId: string;
}

const DatasetMembers: React.FC<DatasetMembersProps> = ({ datasetId }) => {
  const { t } = useTranslation();
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
      message.error(error.message || t('datasetMembers.fetchError'));
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
      message.success(t('datasetMembers.removeSuccess'));
      fetchMembers();
    } catch (error: any) {
      message.error(error.message || t('datasetMembers.removeError'));
    }
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingMember) {
        await api.updateDatasetMemberRole(datasetId, editingMember.userId, { role: values.role });
        message.success(t('datasetMembers.updateRoleSuccess'));
      } else {
        await api.addDatasetMember(datasetId, { userId: values.userId, role: values.role });
        message.success(t('datasetMembers.addMemberSuccess'));
      }
      setIsModalOpen(false);
      fetchMembers();
    } catch (error: any) {
      message.error(error.message || t('common.operationFailed'));
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
    'owner': t('datasetMembers.roles.owner'),
    'manager': t('datasetMembers.roles.manager'),
    'annotator': t('datasetMembers.roles.annotator'),
    'reviewer': t('datasetMembers.roles.reviewer'),
    'viewer': t('datasetMembers.roles.viewer'),
  };

  // Get member user IDs to filter available users
  const memberUserIds = new Set(members.map(m => m.userId));

  const columns = [
    {
      title: t('common.email'),
      dataIndex: 'userEmail',
      key: 'userEmail',
    },
    {
      title: t('common.fullName'),
      dataIndex: 'userFullName',
      key: 'userFullName',
    },
    {
      title: t('common.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: ResourceRole) => (
        <Tag color={roleColors[role]}>
          {roleLabels[role]}
        </Tag>
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      render: (_: any, record: DatasetMember) => (
        <Space size="middle">
          <Button 
            type="link" 
            icon={<EditOutlined />} 
            onClick={() => handleEdit(record)}
            disabled={record.role === 'owner'}
          >
            {t('common.edit')}
          </Button>
          <Popconfirm
            title={t('datasetMembers.removeConfirm')}
            onConfirm={() => handleDelete(record.userId)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            disabled={record.role === 'owner'}
          >
            <Button 
              type="link" 
              danger 
              icon={<DeleteOutlined />}
              disabled={record.role === 'owner'}
            >
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={5}>{t('datasetMembers.title')}</Title>
        <Button type="primary" icon={<UserAddOutlined />} onClick={handleAdd}>
          {t('datasetMembers.addMember')}
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
        title={editingMember ? t('datasetMembers.editMemberRole') : t('datasetMembers.addMember')}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={() => setIsModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          {!editingMember && (
            <Form.Item
              name="userId"
              label={t('datasetMembers.user')}
              rules={[{ required: true, message: t('datasetMembers.selectUserRequired') }]}
            >
              <Select
                showSearch
                placeholder={t('datasetMembers.selectUser')}
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
            label={t('common.role')}
            rules={[{ required: true, message: t('datasetMembers.selectRoleRequired') }]}
            initialValue="viewer"
          >
            <Select disabled={editingMember?.role === 'owner'}>
              <Select.Option value="viewer">{t('datasetMembers.roles.viewer')}</Select.Option>
              <Select.Option value="reviewer">{t('datasetMembers.roles.reviewer')}</Select.Option>
              <Select.Option value="annotator">{t('datasetMembers.roles.annotator')}</Select.Option>
              <Select.Option value="manager">{t('datasetMembers.roles.manager')}</Select.Option>
              {!editingMember && (
                <Select.Option value="owner">{t('datasetMembers.roles.owner')}</Select.Option>
              )}
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default DatasetMembers;

