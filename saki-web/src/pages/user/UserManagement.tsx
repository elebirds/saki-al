import React, { useEffect, useState, useRef } from 'react';
import { Table, Button, Modal, Form, Input, Checkbox, message, Space, Popconfirm, Tag, Select, Spin, Tooltip, Result } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, KeyOutlined } from '@ant-design/icons';
import { User, Role, UserSystemRole } from '../../types';
import { api } from '../../services/api';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../store/authStore';
import { usePermission } from '../../hooks';

const UserManagement: React.FC = () => {
  const { t } = useTranslation();
  const currentUser = useAuthStore((state) => state.user);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(false);
  const [rolesLoading, setRolesLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isRoleModalOpen, setIsRoleModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [userRoles, setUserRoles] = useState<UserSystemRole[]>([]);
  const [tableHeight, setTableHeight] = useState<number>(500);
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [form] = Form.useForm();
  const [roleForm] = Form.useForm();
  
  // Permission checks
  const { can, isSuperAdmin, isLoading: permissionLoading } = usePermission();
  const canReadUsers = can('user:read') || isSuperAdmin;
  const canCreateUser = can('user:create') || isSuperAdmin;
  const canUpdateUser = can('user:update') || isSuperAdmin;
  const canDeleteUser = can('user:delete') || isSuperAdmin;
  const canManageRoles = can('user:manage') || isSuperAdmin;

  const fetchUsers = async () => {
    if (!canReadUsers) return;
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

  const fetchRoles = async () => {
    if (!canManageRoles) return;
    setRolesLoading(true);
    try {
      const data = await api.getRoles('system');
      setRoles(data);
    } catch (error) {
      console.error('Failed to fetch roles:', error);
    } finally {
      setRolesLoading(false);
    }
  };

  const fetchUserRoles = async (userId: string) => {
    try {
      const data = await api.getUserRoles(userId);
      setUserRoles(data);
    } catch (error) {
      console.error('Failed to fetch user roles:', error);
    }
  };

  useEffect(() => {
    if (!permissionLoading && canReadUsers) {
      fetchUsers();
    }
    if (!permissionLoading && canManageRoles) {
      fetchRoles();
    }
  }, [permissionLoading, canReadUsers, canManageRoles]);

  // 计算表格高度
  useEffect(() => {
    const updateTableHeight = () => {
      if (tableContainerRef.current) {
        const containerHeight = tableContainerRef.current.clientHeight;
        // 减去：表格头部(约55px) + 分页器(约64px)
        const calculatedHeight = containerHeight - 119;
        setTableHeight(Math.max(300, calculatedHeight)); // 最小高度300px
      }
    };

    // 使用 setTimeout 确保 DOM 已渲染
    const timeoutId = setTimeout(updateTableHeight, 0);
    window.addEventListener('resize', updateTableHeight);
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener('resize', updateTableHeight);
    };
  }, [users]); // 当数据变化时重新计算

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
    } catch (error: any) {
      message.error(error.message || t('userManagement.deleteError'));
    }
  };

  const handleManageRoles = async (user: User) => {
    setSelectedUserId(user.id);
    await fetchUserRoles(user.id);
    setIsRoleModalOpen(true);
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

  const handleAssignRole = async () => {
    if (!selectedUserId) return;
    try {
      const values = await roleForm.validateFields();
      await api.assignUserRole(selectedUserId, { roleId: values.roleId });
      message.success(t('userManagement.roleAssigned'));
      await fetchUserRoles(selectedUserId);
      roleForm.resetFields();
      fetchUsers(); // Refresh user list to update role display
    } catch (error: any) {
      message.error(error.message || t('common.operationFailed'));
    }
  };

  const handleRevokeRole = async (roleId: string) => {
    if (!selectedUserId) return;
    try {
      await api.revokeUserRole(selectedUserId, roleId);
      message.success(t('userManagement.roleRevoked'));
      await fetchUserRoles(selectedUserId);
      fetchUsers(); // Refresh user list to update role display
    } catch (error: any) {
      message.error(error.message || t('common.operationFailed'));
    }
  };

  // Get role color based on role name
  const getRoleColor = (roleName: string): string => {
    const colors: Record<string, string> = {
      'super_admin': 'red',
      'admin': 'gold',
      'user': 'blue',
    };
    return colors[roleName] || 'default';
  };

  // Check if user has super_admin role
  const isUserSuperAdmin = (user: User): boolean => {
    return user.systemRoles?.some(r => r.name === 'super_admin') ?? false;
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
      key: 'systemRoles',
      render: (_: any, record: User) => (
        <Space wrap>
          {record.systemRoles?.map(role => (
            <Tag key={role.id} color={getRoleColor(role.name)}>
              {role.displayName}
            </Tag>
          )) || <Tag>-</Tag>}
        </Space>
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      render: (_: any, record: User) => {
        const isSuperAdminUser = isUserSuperAdmin(record);
        const canEditThisUser = canUpdateUser && (!isSuperAdminUser || isSuperAdmin);
        const canDeleteThisUser = canDeleteUser && (!isSuperAdminUser || isSuperAdmin) && record.id !== currentUser?.id;
        
        return (
          <Space size="middle">
            {canEditThisUser ? (
              <Button type="link" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
                {t('common.edit')}
              </Button>
            ) : (
              <Tooltip title={t('common.noPermission')}>
                <Button type="link" icon={<EditOutlined />} disabled>
                  {t('common.edit')}
                </Button>
              </Tooltip>
            )}
            
            {canManageRoles && (
              <Button type="link" icon={<KeyOutlined />} onClick={() => handleManageRoles(record)}>
                {t('userManagement.manageRoles')}
              </Button>
            )}
            
            {canDeleteThisUser ? (
              <Popconfirm
                title={t('userManagement.deleteConfirm')}
                onConfirm={() => handleDelete(record.id)}
                okText={t('common.yes')}
                cancelText={t('common.no')}
              >
                <Button type="link" danger icon={<DeleteOutlined />}>
                  {t('common.delete')}
                </Button>
              </Popconfirm>
            ) : (
              <Tooltip title={record.id === currentUser?.id ? t('userManagement.cannotDeleteSelf') : t('common.noPermission')}>
                <Button type="link" danger icon={<DeleteOutlined />} disabled>
                  {t('common.delete')}
                </Button>
              </Tooltip>
            )}
          </Space>
        );
      },
    },
  ];

  // Get assigned role IDs for the selected user
  const assignedRoleIds = new Set(userRoles.map(ur => ur.roleId));

  // Show loading state while permissions are being loaded
  if (permissionLoading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <Spin size="large" tip={t('common.loading')} />
      </div>
    );
  }

  // Show no permission message if user can't read users
  if (!canReadUsers) {
    return (
      <div style={{ padding: '24px' }}>
        <Result
          status="403"
          title="403"
          subTitle={t('common.noPermission')}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: '24px', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <h2 style={{ margin: 0 }}>{t('userManagement.title')}</h2>
        {canCreateUser ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            {t('userManagement.addUser')}
          </Button>
        ) : (
          <Tooltip title={t('common.noPermission')}>
            <Button type="primary" icon={<PlusOutlined />} disabled>
              {t('userManagement.addUser')}
            </Button>
          </Tooltip>
        )}
      </div>
      <div ref={tableContainerRef} style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Table 
          columns={columns} 
          dataSource={users} 
          rowKey="id" 
          loading={loading}
          scroll={{ 
            y: tableHeight,
            x: 'max-content' 
          }}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total, range) => 
              range 
                ? `${range[0]}-${range[1]} ${t('common.of')} ${total} ${t('common.items')}`
                : `${total} ${t('common.items')}`,
            pageSizeOptions: ['10', '20', '50', '100'],
          }}
        />
      </div>

      {/* User Edit Modal */}
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
        </Form>
      </Modal>

      {/* Role Management Modal */}
      <Modal
        title={t('userManagement.manageRoles')}
        open={isRoleModalOpen}
        onCancel={() => setIsRoleModalOpen(false)}
        footer={null}
        width={600}
      >
        {rolesLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <Spin tip={t('common.loading')} />
          </div>
        ) : (
          <>
            {/* Current Roles */}
            <div style={{ marginBottom: 24 }}>
              <h4>{t('userManagement.currentRoles')}</h4>
              {userRoles.length === 0 ? (
                <p style={{ color: '#999' }}>{t('userManagement.noRoles')}</p>
              ) : (
                <Space wrap>
                  {userRoles.map(ur => {
                    const role = roles.find(r => r.id === ur.roleId);
                    const canRevoke = isSuperAdmin || (role?.name !== 'super_admin');
                    return (
                      <Tag 
                        key={ur.id} 
                        color={getRoleColor(ur.roleName || '')}
                        closable={canRevoke}
                        onClose={(e) => {
                          e.preventDefault();
                          handleRevokeRole(ur.roleId);
                        }}
                      >
                        {ur.roleDisplayName || ur.roleName}
                      </Tag>
                    );
                  })}
                </Space>
              )}
            </div>

            {/* Assign New Role */}
            <div>
              <h4>{t('userManagement.assignRole')}</h4>
              <Form form={roleForm} layout="inline" onFinish={handleAssignRole}>
                <Form.Item
                  name="roleId"
                  rules={[{ required: true, message: t('userManagement.selectRole') }]}
                  style={{ flex: 1, marginRight: 8 }}
                >
                  <Select placeholder={t('userManagement.selectRole')} style={{ width: '100%' }}>
                    {roles
                      .filter(role => {
                        // Filter out already assigned roles
                        if (assignedRoleIds.has(role.id)) return false;
                        // Only super_admin can assign super_admin role
                        if (role.name === 'super_admin' && !isSuperAdmin) return false;
                        return true;
                      })
                      .map(role => (
                        <Select.Option key={role.id} value={role.id}>
                          <Tag color={getRoleColor(role.name)} style={{ marginRight: 8 }}>
                            {role.displayName}
                          </Tag>
                          {role.description && (
                            <span style={{ color: '#999', fontSize: 12 }}>
                              {role.description}
                            </span>
                          )}
                        </Select.Option>
                      ))}
                  </Select>
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit">
                    {t('userManagement.assign')}
                  </Button>
                </Form.Item>
              </Form>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
};

export default UserManagement;
