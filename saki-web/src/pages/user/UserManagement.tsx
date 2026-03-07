import React, {useCallback, useEffect, useState} from 'react';
import {
    Button,
    Checkbox,
    DatePicker,
    Form,
    Input,
    message,
    Modal,
    Popconfirm,
    Result,
    Select,
    Spin,
    Table,
    Tag,
    Tooltip
} from 'antd';
import {DeleteOutlined, EditOutlined, KeyOutlined, PlusOutlined} from '@ant-design/icons';
import dayjs, {Dayjs} from 'dayjs';
import {Role, User, UserSystemRole, UserSystemRoleAssign} from '../../types';
import {api} from '../../services/api';
import {useTranslation} from 'react-i18next';
import {useAuthStore} from '../../store/authStore';
import {usePermission} from '../../hooks';
import {PaginatedList} from '../../components/common/PaginatedList';
import {createEmptyPaginationResponse} from '../../types/pagination';

const UserManagement: React.FC = () => {
    const {t} = useTranslation();
    const currentUser = useAuthStore((state) => state.user);
    const [roles, setRoles] = useState<Role[]>([]);
    const [rolesLoading, setRolesLoading] = useState(false);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isRoleModalOpen, setIsRoleModalOpen] = useState(false);
    const [editingUser, setEditingUser] = useState<User | null>(null);
    const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
    const [userRoles, setUserRoles] = useState<UserSystemRole[]>([]);
    const [form] = Form.useForm();
    const [roleForm] = Form.useForm();
    const [refreshKey, setRefreshKey] = useState(0);

    // Permission checks
    const {can, isSuperAdmin, isLoading: permissionLoading} = usePermission();
    const canReadUsers = can('user:read') || isSuperAdmin;
    const canCreateUser = can('user:create') || isSuperAdmin;
    const canUpdateUser = can('user:update') || isSuperAdmin;
    const canDeleteUser = can('user:delete') || isSuperAdmin;
    const canReadUserRoles = can('user:role_read') || isSuperAdmin;
    const canAssignRoles = can('role:assign') || isSuperAdmin;
    const canRevokeRoles = can('role:revoke') || isSuperAdmin;

    const fetchUsers = useCallback(async (page: number, pageSize: number) => {
        if (!canReadUsers) {
            return createEmptyPaginationResponse<User>(pageSize, page);
        }
        try {
            return await api.getUsers(page, pageSize);
        } catch (error) {
            message.error(t('user.management.fetchError'));
            throw error;
        }
    }, [canReadUsers, t]);

    const fetchRoles = useCallback(async () => {
        if (!canReadUserRoles) return;
        setRolesLoading(true);
        try {
            const data = await api.getRoles('system');
            setRoles(data.items);
        } catch (error) {
            console.error('Failed to fetch roles:', error);
        } finally {
            setRolesLoading(false);
        }
    }, [canReadUserRoles]);

    const fetchUserRoles = async (userId: string) => {
        try {
            const data = await api.getUserRoles(userId);
            setUserRoles(data);
        } catch (error) {
            console.error('Failed to fetch user roles:', error);
        }
    };

    useEffect(() => {
        if (!permissionLoading && canReadUserRoles) {
            fetchRoles();
        }
    }, [permissionLoading, canReadUserRoles, fetchRoles]);

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
            message.success(t('user.management.deleteSuccess'));
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('user.management.deleteError'));
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
                message.success(t('user.management.updateSuccess'));
            } else {
                await api.createUser(values);
                message.success(t('user.management.createSuccess'));
            }
            setIsModalOpen(false);
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('common.operationFailed'));
        }
    };

    const handleAssignRole = async () => {
        if (!selectedUserId) return;
        try {
            const values = await roleForm.validateFields();
            const roleData: UserSystemRoleAssign = {
                roleId: values.roleId,
            };
            if (values.expiresAt) {
                roleData.expiresAt = (values.expiresAt as Dayjs).toISOString();
            }
            await api.assignUserRole(selectedUserId, roleData);
            message.success(t('user.management.roleAssigned'));
            await fetchUserRoles(selectedUserId);
            roleForm.resetFields();
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('common.operationFailed'));
        }
    };

    const handleRevokeRole = async (roleId: string) => {
        if (!selectedUserId) return;
        try {
            await api.revokeUserRole(selectedUserId, roleId);
            message.success(t('user.management.roleRevoked'));
            await fetchUserRoles(selectedUserId);
            setRefreshKey((v) => v + 1);
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
        return user.roles?.some(r => r.name === 'super_admin') ?? false;
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
                <div className="flex flex-wrap gap-1">
                    {record.roles?.map(role => (
                        <Tag key={role.id} color={getRoleColor(role.name)}>
                            {role.displayName}
                        </Tag>
                    )) || <Tag>-</Tag>}
                </div>
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
                    <div className="flex items-center gap-3">
                        {canEditThisUser ? (
                            <Button type="link" icon={<EditOutlined/>} onClick={() => handleEdit(record)}>
                                {t('common.edit')}
                            </Button>
                        ) : (
                            <Tooltip title={t('common.noPermission')}>
                                <Button type="link" icon={<EditOutlined/>} disabled>
                                    {t('common.edit')}
                                </Button>
                            </Tooltip>
                        )}

                        {canReadUserRoles && (
                            <Button type="link" icon={<KeyOutlined/>} onClick={() => handleManageRoles(record)}>
                                {t('user.management.manageRoles')}
                            </Button>
                        )}

                        {canDeleteThisUser ? (
                            <Popconfirm
                                title={t('user.management.deleteConfirm')}
                                onConfirm={() => handleDelete(record.id)}
                                okText={t('common.yes')}
                                cancelText={t('common.no')}
                            >
                                <Button type="link" danger icon={<DeleteOutlined/>}>
                                    {t('common.delete')}
                                </Button>
                            </Popconfirm>
                        ) : (
                            <Tooltip
                                title={record.id === currentUser?.id ? t('user.management.cannotDeleteSelf') : t('common.noPermission')}>
                                <Button type="link" danger icon={<DeleteOutlined/>} disabled>
                                    {t('common.delete')}
                                </Button>
                            </Tooltip>
                        )}
                    </div>
                );
            },
        },
    ];

    // Get assigned role IDs for the selected user
    const assignedRoleIds = new Set(userRoles.map(ur => ur.roleId));

    // Show loading state while permissions are being loaded
    if (permissionLoading) {
        return (
            <div className="p-6 text-center">
                <Spin size="large" tip={t('common.loading')}/>
            </div>
        );
    }

    // Show no permission message if user can't read users
    if (!canReadUsers) {
        return (
            <div className="p-6">
                <Result
                    status="403"
                    title="403"
                    subTitle={t('common.noPermission')}
                />
            </div>
        );
    }

    return (
        <div className="flex min-h-full flex-col p-6">
            <div className="mb-4 flex flex-shrink-0 items-center justify-between">
                <span className="m-0 font-semibold">{t('user.management.title')}</span>
                {canCreateUser ? (
                    <Button type="primary" icon={<PlusOutlined/>} onClick={handleAdd}>
                        {t('user.management.addUser')}
                    </Button>
                ) : (
                    <Tooltip title={t('common.noPermission')}>
                        <Button type="primary" icon={<PlusOutlined/>} disabled>
                            {t('user.management.addUser')}
                        </Button>
                    </Tooltip>
                )}
            </div>
            <div>
                <PaginatedList<User>
                    fetchData={fetchUsers}
                    refreshKey={refreshKey}
                    resetPageOnRefresh
                    initialPageSize={20}
                    pageSizeOptions={['10', '20', '50', '100']}
                    adaptivePageSize={{
                        enabled: true,
                        mode: 'table',
                        itemHeight: 54,
                        rowGap: 0,
                        reservedHeight: 56,
                    }}
                    renderItems={(items, loading) => (
                        <Table
                            columns={columns}
                            dataSource={items}
                            rowKey="id"
                            loading={loading}
                            scroll={{x: 'max-content'}}
                            pagination={false}
                        />
                    )}
                    paginationProps={{
                        showTotal: (total, range) =>
                            range
                                ? `${range[0]}-${range[1]} ${t('common.of')} ${total} ${t('common.items')}`
                                : `${total} ${t('common.items')}`,
                    }}
                />
            </div>

            {/* User Edit Modal */}
            <Modal
                title={editingUser ? t('user.management.editUser') : t('user.management.addUser')}
                open={isModalOpen}
                onOk={handleOk}
                onCancel={() => setIsModalOpen(false)}
            >
                <Form form={form} layout="vertical">
                    <Form.Item
                        name="email"
                        label={t('common.email')}
                        rules={[{required: true, type: 'email', message: t('user.management.emailRequired')}]}
                    >
                        <Input disabled={!!editingUser}/>
                    </Form.Item>
                    <Form.Item
                        name="fullName"
                        label={t('common.fullName')}
                    >
                        <Input/>
                    </Form.Item>
                    <Form.Item
                        name="password"
                        label={t('common.password')}
                        rules={[{required: !editingUser, message: t('user.management.passwordRequired')}]}
                        help={editingUser ? t('user.management.passwordHelp') : undefined}
                    >
                        <Input.Password/>
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
                title={t('user.management.manageRoles')}
                open={isRoleModalOpen}
                onCancel={() => setIsRoleModalOpen(false)}
                footer={null}
                width={600}
            >
                {rolesLoading ? (
                    <div className="p-5 text-center">
                        <Spin tip={t('common.loading')}/>
                    </div>
                ) : (
                    <>
                        {/* Current Roles */}
                        <div className="mb-6">
                            <h4>{t('user.management.currentRoles')}</h4>
                            {userRoles.length === 0 ? (
                                <p className="text-gray-500">{t('user.management.noRoles')}</p>
                            ) : (
                                <div className="flex w-full flex-col gap-3">
                                    {userRoles.map(ur => {
                                        const role = roles.find(r => r.id === ur.roleId);
                                        const canRevoke = canRevokeRoles && (isSuperAdmin || (role?.name !== 'super_admin'));
                                        const isExpired = ur.expiresAt && dayjs(ur.expiresAt).isBefore(dayjs());
                                        return (
                                            <div key={ur.id}
                                                 className="flex items-center justify-between rounded border border-gray-200 px-3 py-2">
                                                <div className="flex-1">
                                                    <Tag
                                                        color={isExpired ? 'red' : getRoleColor(ur.roleName || '')}
                                                        className="mr-2"
                                                    >
                                                        {ur.roleDisplayName || ur.roleName}
                                                    </Tag>
                                                    {ur.expiresAt && (
                                                        <span
                                                            className={`text-xs ${isExpired ? 'text-red-500' : 'text-gray-600'}`}>
                              {isExpired ? t('user.management.expired') : t('user.management.expiresAt')}: {dayjs(ur.expiresAt).format('YYYY-MM-DD HH:mm:ss')}
                            </span>
                                                    )}
                                                    {!ur.expiresAt && (
                                                        <span className="text-xs text-gray-500">
                              {t('user.management.noExpiration')}
                            </span>
                                                    )}
                                                </div>
                                                {canRevoke && (
                                                    <Button
                                                        type="link"
                                                        danger
                                                        size="small"
                                                        onClick={() => handleRevokeRole(ur.roleId)}
                                                    >
                                                        {t('user.management.revoke')}
                                                    </Button>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>

                        {/* Assign New Role */}
                        {canAssignRoles && (
                            <div>
                                <h4>{t('user.management.assignRole')}</h4>
                                <Form form={roleForm} layout="vertical" onFinish={handleAssignRole}>
                                    <Form.Item
                                        name="roleId"
                                        label={t('user.management.selectRole')}
                                        rules={[{required: true, message: t('user.management.selectRole')}]}
                                    >
                                        <Select placeholder={t('user.management.selectRole')} className="w-full">
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
                                                        <Tag color={getRoleColor(role.name)} className="mr-2">
                                                            {role.displayName}
                                                        </Tag>
                                                        {role.description && (
                                                            <span className="text-xs text-gray-500">
                                {role.description}
                              </span>
                                                        )}
                                                    </Select.Option>
                                                ))}
                                        </Select>
                                    </Form.Item>
                                    <Form.Item
                                        name="expiresAt"
                                        label={t('user.management.expiresAt')}
                                        tooltip={t('user.management.expiresAtTooltip')}
                                    >
                                        <DatePicker
                                            showTime
                                            format="YYYY-MM-DD HH:mm:ss"
                                            className="w-full"
                                            disabledDate={(current) => current && current < dayjs().startOf('day')}
                                            placeholder={t('user.management.expiresAtPlaceholder')}
                                        />
                                    </Form.Item>
                                    <Form.Item>
                                        <Button type="primary" htmlType="submit" block>
                                            {t('user.management.assign')}
                                        </Button>
                                    </Form.Item>
                                </Form>
                            </div>
                        )}
                    </>
                )}
            </Modal>
        </div>
    );
};

export default UserManagement;
