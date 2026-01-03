import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Input, Checkbox, message, Space, Popconfirm, Tag, Select } from 'antd';
import { User, GlobalRole } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../store/authStore';

const UserManagement: React.FC = () => {
  const { t } = useTranslation();
  const currentUser = useAuthStore((state) => state.user);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();
  
  // Check if current user can manage roles
  const canManageRoles = currentUser?.globalRole === 'super_admin' || currentUser?.globalRole === 'admin';

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await api.getUsers();
      setUsers(data);
    } catch (error) {
      message.error(t('userManagement.fetchError'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleAdd = () => {
    setEditingUser(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (user: User) => {
    setEditingUser(user);
    form.setFieldsValue({
      ...user,
      password: '', // Don't fill password
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteUser(id);
      message.success(t('userManagement.deleteSuccess'));
      fetchUsers();
    } catch (error) {
      message.error(t('userManagement.deleteError'));
    }
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      // Remove password if empty
      if (values.password === '') {
        delete values.password;
      }
      if (editingUser) {
        await api.updateUser(editingUser.id, values);
        message.success(t('userManagement.updateSuccess'));
      } else {
        await api.createUser(values);
        message.success(t('userManagement.createSuccess'));
      }
      setIsModalOpen(false);
      fetchUsers();
    } catch (error: any) {
      message.error(error.message || t('common.operationFailed'));
    }
  };

  const columns = [
    {
      title: t('common.email'),
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: t('common.fullName'),
      dataIndex: 'fullName',
      key: 'fullName',
    },
    {
      title: t('common.status'),
      key: 'isActive',
      dataIndex: 'isActive',
      render: (isActive: boolean) => (
        <Tag color={isActive ? 'green' : 'red'}>
          {isActive ? t('common.active') : t('common.inactive')}
        </Tag>
      ),
    },
    {
      title: t('common.role'),
      key: 'globalRole',
      dataIndex: 'globalRole',
      render: (role: GlobalRole) => {
        const roleColors: Record<GlobalRole, string> = {
          'super_admin': 'red',
          'admin': 'gold',
          'annotator': 'blue',
          'viewer': 'default',
        };
        const roleLabels: Record<GlobalRole, string> = {
          'super_admin': t('userManagement.roles.superAdmin'),
          'admin': t('userManagement.roles.admin'),
          'annotator': t('userManagement.roles.annotator'),
          'viewer': t('userManagement.roles.viewer'),
        };
        return (
          <Tag color={roleColors[role]}>
            {roleLabels[role]}
          </Tag>
        );
      },
    },
    {
      title: t('common.actions'),
      key: 'action',
      render: (_: any, record: User) => (
        <Space size="middle">
          <Button type="link" onClick={() => handleEdit(record)}>
            {t('common.edit')}
          </Button>
          <Popconfirm
            title={t('userManagement.deleteConfirm')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button type="link" danger>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>{t('userManagement.title')}</h2>
        <Button type="primary" onClick={handleAdd}>
          {t('userManagement.addUser')}
        </Button>
      </div>
      <Table columns={columns} dataSource={users} rowKey="id" loading={loading} />

      <Modal
        title={editingUser ? t('userManagement.editUser') : t('userManagement.addUser')}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={() => setIsModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="email"
            label={t('common.email')}
            rules={[{ required: true, type: 'email', message: t('userManagement.emailRequired') }]}
          >
            <Input disabled={!!editingUser} />
          </Form.Item>
          <Form.Item
            name="fullName"
            label={t('common.fullName')}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={t('common.password')}
            rules={[{ required: !editingUser, message: t('userManagement.passwordRequired') }]}
            help={editingUser ? t('userManagement.passwordHelp') : undefined}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="isActive"
            valuePropName="checked"
            initialValue={true}
          >
            <Checkbox>{t('common.active')}</Checkbox>
          </Form.Item>
          {canManageRoles && (
            <Form.Item
              name="globalRole"
              label={t('userManagement.globalRole')}
              initialValue="viewer"
            >
              <Select>
                <Select.Option value="viewer">{t('userManagement.roles.viewer')}</Select.Option>
                <Select.Option value="annotator">{t('userManagement.roles.annotator')}</Select.Option>
                <Select.Option value="admin">{t('userManagement.roles.admin')}</Select.Option>
                {currentUser?.globalRole === 'super_admin' && (
                  <Select.Option value="super_admin">{t('userManagement.roles.superAdmin')}</Select.Option>
                )}
              </Select>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default UserManagement;
