import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Select, message, Space, Popconfirm, Tag, Typography, Spin } from 'antd';
import { UserAddOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { ResourceMember, User } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';
import { useResourcePermission } from '../../hooks';

const { Title } = Typography;

interface AvailableRole {
  id: string;
  name: string;
  displayName: string;
  description?: string;
}

interface DatasetMembersProps {
  datasetId: string;
  ownerId?: string;
}

const DatasetMembers: React.FC<DatasetMembersProps> = ({ datasetId, ownerId }) => {
  const { t } = useTranslation();
  const [members, setMembers] = useState<ResourceMember[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [availableRoles, setAvailableRoles] = useState<AvailableRole[]>([]);
  const [loading, setLoading] = useState(false);
  const [rolesLoading, setRolesLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingMember, setEditingMember] = useState<ResourceMember | null>(null);
  const [form] = Form.useForm();

  // Permission hook
  const { can, isOwner } = useResourcePermission('dataset', datasetId, ownerId);
  const canManageMembers = can('dataset:assign');

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

  const fetchAvailableRoles = async () => {
    setRolesLoading(true);
    try {
      const data = await api.getAvailableDatasetRoles(datasetId);
      setAvailableRoles(data);
    } catch (error) {
      console.error('Failed to fetch available roles:', error);
    } finally {
      setRolesLoading(false);
    }
  };

  useEffect(() => {
    fetchMembers();
    fetchUsers();
    fetchAvailableRoles();
  }, [datasetId]);

  const handleAdd = () => {
    setEditingMember(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (member: ResourceMember) => {
    setEditingMember(member);
    form.setFieldsValue({
      roleId: member.roleId,
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
        await api.updateDatasetMemberRole(datasetId, editingMember.userId, { roleId: values.roleId });
        message.success(t('datasetMembers.updateRoleSuccess'));
      } else {
        await api.addDatasetMember(datasetId, { userId: values.userId, roleId: values.roleId });
        message.success(t('datasetMembers.addMemberSuccess'));
      }
      setIsModalOpen(false);
      fetchMembers();
    } catch (error: any) {
      message.error(error.message || t('common.operationFailed'));
    }
  };

  // Role colors based on role name
  const getRoleColor = (roleName?: string): string => {
    const colors: Record<string, string> = {
      'dataset_owner': 'gold',
      'dataset_manager': 'blue',
      'dataset_annotator': 'green',
      'dataset_reviewer': 'cyan',
      'dataset_viewer': 'default',
      'dataset_senior_annotator': 'lime',
    };
    return colors[roleName || ''] || 'default';
  };

  // Get member user IDs to filter available users
  const memberUserIds = new Set(members.map(m => m.userId));

  // Check if a member is the owner (by comparing with ownerId)
  const isDatasetOwner = (userId: string) => userId === ownerId;

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
      key: 'role',
      render: (_: any, record: ResourceMember) => (
        <Tag color={getRoleColor(record.roleName)}>
          {record.roleDisplayName || record.roleName || '-'}
        </Tag>
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      render: (_: any, record: ResourceMember) => {
        const isOwnerMember = isDatasetOwner(record.userId);
        return (
          <Space size="middle">
            <Button 
              type="link" 
              icon={<EditOutlined />} 
              onClick={() => handleEdit(record)}
              disabled={isOwnerMember || !canManageMembers}
            >
              {t('common.edit')}
            </Button>
            <Popconfirm
              title={t('datasetMembers.removeConfirm')}
              onConfirm={() => handleDelete(record.userId)}
              okText={t('common.yes')}
              cancelText={t('common.no')}
              disabled={isOwnerMember || !canManageMembers}
            >
              <Button 
                type="link" 
                danger 
                icon={<DeleteOutlined />}
                disabled={isOwnerMember || !canManageMembers}
              >
                {t('common.delete')}
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={5}>{t('datasetMembers.title')}</Title>
        {canManageMembers && (
          <Button type="primary" icon={<UserAddOutlined />} onClick={handleAdd}>
            {t('datasetMembers.addMember')}
          </Button>
        )}
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
        {rolesLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <Spin tip={t('common.loading')} />
          </div>
        ) : (
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
              name="roleId"
              label={t('common.role')}
              rules={[{ required: true, message: t('datasetMembers.selectRoleRequired') }]}
            >
              <Select placeholder={t('datasetMembers.selectRole')}>
                {availableRoles
                  .filter(role => {
                    // Don't show owner role when editing (owner can't be changed)
                    if (editingMember && role.name === 'dataset_owner') return false;
                    return true;
                  })
                  .map(role => (
                    <Select.Option key={role.id} value={role.id}>
                      <div>
                        <span>{role.displayName}</span>
                        {role.description && (
                          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
                            {role.description}
                          </span>
                        )}
                      </div>
                    </Select.Option>
                  ))}
              </Select>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default DatasetMembers;
