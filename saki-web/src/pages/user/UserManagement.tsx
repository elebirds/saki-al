import React, { useEffect, useState } from 'react';
import { Table, Button, Modal, Form, Input, Checkbox, message, Space, Popconfirm, Tag } from 'antd';
import { User } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';

const UserManagement: React.FC = () => {
  const { t } = useTranslation();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await api.getUsers();
      setUsers(data);
    } catch (error) {
      message.error(t('Failed to fetch users'));
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
      message.success(t('User deleted successfully'));
      fetchUsers();
    } catch (error) {
      message.error(t('Failed to delete user'));
    }
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingUser) {
        await api.updateUser(editingUser.id, values);
        message.success(t('User updated successfully'));
      } else {
        await api.createUser(values);
        message.success(t('User created successfully'));
      }
      setIsModalOpen(false);
      fetchUsers();
    } catch (error) {
      message.error(t('Operation failed'));
    }
  };

  const columns = [
    {
      title: t('Email'),
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: t('Full Name'),
      dataIndex: 'fullName',
      key: 'fullName',
    },
    {
      title: t('Status'),
      key: 'isActive',
      dataIndex: 'isActive',
      render: (isActive: boolean) => (
        <Tag color={isActive ? 'green' : 'red'}>
          {isActive ? t('Active') : t('Inactive')}
        </Tag>
      ),
    },
    {
      title: t('Role'),
      key: 'isSuperuser',
      dataIndex: 'isSuperuser',
      render: (isSuperuser: boolean) => (
        <Tag color={isSuperuser ? 'gold' : 'blue'}>
          {isSuperuser ? t('Admin') : t('User')}
        </Tag>
      ),
    },
    {
      title: t('Actions'),
      key: 'action',
      render: (_: any, record: User) => (
        <Space size="middle">
          <Button type="link" onClick={() => handleEdit(record)}>
            {t('Edit')}
          </Button>
          <Popconfirm
            title={t('Are you sure to delete this user?')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('Yes')}
            cancelText={t('No')}
          >
            <Button type="link" danger>
              {t('Delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>{t('User Management')}</h2>
        <Button type="primary" onClick={handleAdd}>
          {t('Add User')}
        </Button>
      </div>
      <Table columns={columns} dataSource={users} rowKey="id" loading={loading} />

      <Modal
        title={editingUser ? t('Edit User') : t('Add User')}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={() => setIsModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="email"
            label={t('Email')}
            rules={[{ required: true, type: 'email', message: t('Please input a valid email!') }]}
          >
            <Input disabled={!!editingUser} />
          </Form.Item>
          <Form.Item
            name="fullName"
            label={t('Full Name')}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={t('Password')}
            rules={[{ required: !editingUser, message: t('Please input password!') }]}
            help={editingUser ? t('Leave empty to keep current password') : undefined}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="isActive"
            valuePropName="checked"
            initialValue={true}
          >
            <Checkbox>{t('Active')}</Checkbox>
          </Form.Item>
          <Form.Item
            name="isSuperuser"
            valuePropName="checked"
            initialValue={false}
          >
            <Checkbox>{t('Superuser')}</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default UserManagement;
