import React, {useCallback, useEffect, useState} from 'react';
import {
    Button,
    Card,
    Checkbox,
    ColorPicker,
    Divider,
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
    Tooltip,
    Typography
} from 'antd';
import {DeleteOutlined, EditOutlined, LockOutlined, PlusOutlined} from '@ant-design/icons';
import {Role, RoleCreate, RolePermissionCatalog, RolePermissionCreate, RoleType, RoleUpdate} from '../../types';
import {api} from '../../services/api';
import {useTranslation} from 'react-i18next';
import {usePermission} from '../../hooks';
import {PaginatedList} from '../../components/common/PaginatedList';
import {createEmptyPaginationResponse} from '../../types/pagination';

const {TextArea} = Input;
const {Text, Title} = Typography;

type PermissionOption = {
    value: string;
    label: string;
}

type PermissionCategory = {
    title: string;
    permissions: PermissionOption[];
}

const filterPermissionCategories = (
    categories: PermissionCategory[],
    allowedPermissions?: Set<string>,
) => {
    if (!allowedPermissions) return categories
    return categories
        .map((category) => ({
            ...category,
            permissions: category.permissions.filter((perm) => allowedPermissions.has(perm.value)),
        }))
        .filter((category) => category.permissions.length > 0)
}

// 获取权限分类列表（根据国际化和角色类型过滤）
const getPermissionCategories = (
    t: (key: string) => string,
    roleType?: RoleType,
    allowedPermissions?: Set<string>,
) => {
    // 系统级权限（只有系统角色可以使用）
    const systemCategories = [
        {
            title: t('role.management.permissionLabels.userManagement'),
            permissions: [
                {value: 'user:create:all', label: t('role.management.permissionLabels.userCreate')},
                {value: 'user:read:all', label: t('role.management.permissionLabels.userRead')},
                {value: 'user:update:all', label: t('role.management.permissionLabels.userUpdate')},
                {value: 'user:delete:all', label: t('role.management.permissionLabels.userDelete')},
                {value: 'user:list:all', label: t('role.management.permissionLabels.userList')},
            ],
        },
        {
            title: t('role.management.permissionLabels.roleManagement'),
            permissions: [
                {value: 'role:create:all', label: t('role.management.permissionLabels.roleCreate')},
                {value: 'role:read:all', label: t('role.management.permissionLabels.roleRead')},
                {value: 'role:update:all', label: t('role.management.permissionLabels.roleUpdate')},
                {value: 'role:delete:all', label: t('role.management.permissionLabels.roleDelete')},
                {value: 'role:assign:all', label: t('role.management.permissionLabels.roleAssign')},
                {value: 'role:revoke:all', label: t('role.management.permissionLabels.roleRevoke')},
                {value: 'role:assign_admin:all', label: t('role.management.permissionLabels.roleAssignAdmin')},
            ],
        },
        {
            title: t('role.management.permissionLabels.systemSettingsManagement'),
            permissions: [
                {value: 'system_setting:read:all', label: t('role.management.permissionLabels.systemSettingsRead')},
                {value: 'system_setting:update:all', label: t('role.management.permissionLabels.systemSettingsUpdate')},
            ],
        },
    ];

    // 资源级权限（系统角色和资源角色都可以使用，但权限范围不同）
    const resourceCategories = [
        {
            title: t('role.management.permissionLabels.userManagement'),
            permissions: [
                {value: 'user:list:assigned', label: t('role.management.permissionLabels.userList')},
            ],
        },
        {
            title: t('role.management.permissionLabels.datasetManagementAll'),
            permissions: [
                {value: 'dataset:create:all', label: t('role.management.permissionLabels.datasetCreateAll')},
                {value: 'dataset:read:all', label: t('role.management.permissionLabels.datasetReadAll')},
                {value: 'dataset:update:all', label: t('role.management.permissionLabels.datasetUpdateAll')},
                {value: 'dataset:delete:all', label: t('role.management.permissionLabels.datasetDeleteAll')},
                {value: 'dataset:assign:all', label: t('role.management.permissionLabels.datasetAssignAll')},
                {value: 'dataset:link_project:all', label: t('role.management.permissionLabels.datasetLinkProjectAll')},
                {value: 'dataset:export:all', label: t('role.management.permissionLabels.datasetExportAll')},
                {value: 'dataset:import:all', label: t('role.management.permissionLabels.datasetImportAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.datasetManagementAssigned'),
            permissions: [
                {value: 'dataset:read:assigned', label: t('role.management.permissionLabels.datasetReadAssigned')},
                {value: 'dataset:update:assigned', label: t('role.management.permissionLabels.datasetUpdateAssigned')},
                {value: 'dataset:assign:assigned', label: t('role.management.permissionLabels.datasetAssignAssigned')},
                {
                    value: 'dataset:link_project:assigned',
                    label: t('role.management.permissionLabels.datasetLinkProjectAssigned')
                },
                {value: 'dataset:export:assigned', label: t('role.management.permissionLabels.datasetExportAssigned')},
                {value: 'dataset:import:assigned', label: t('role.management.permissionLabels.datasetImportAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.sampleManagementAll'),
            permissions: [
                {value: 'sample:read:all', label: t('role.management.permissionLabels.sampleReadAll')},
                {value: 'sample:create:all', label: t('role.management.permissionLabels.sampleCreateAll')},
                {value: 'sample:delete:all', label: t('role.management.permissionLabels.sampleDeleteAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.sampleManagementAssigned'),
            permissions: [
                {value: 'sample:read:assigned', label: t('role.management.permissionLabels.sampleReadAssigned')},
                {value: 'sample:create:assigned', label: t('role.management.permissionLabels.sampleCreateAssigned')},
                {value: 'sample:delete:assigned', label: t('role.management.permissionLabels.sampleDeleteAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.labelManagementAll'),
            permissions: [
                {value: 'label:read:all', label: t('role.management.permissionLabels.labelReadAll')},
                {value: 'label:manage:all', label: t('role.management.permissionLabels.labelManageAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.labelManagementAssigned'),
            permissions: [
                {value: 'label:read:assigned', label: t('role.management.permissionLabels.labelReadAssigned')},
                {value: 'label:manage:assigned', label: t('role.management.permissionLabels.labelManageAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.annotationManagementAll'),
            permissions: [
                {value: 'annotation:read:all', label: t('role.management.permissionLabels.annotationReadAll')},
                {value: 'annotation:create:all', label: t('role.management.permissionLabels.annotationModifyAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.annotationManagementAssigned'),
            permissions: [
                {value: 'annotation:read:assigned', label: t('role.management.permissionLabels.annotationReadAssigned')},
                {
                    value: 'annotation:create:assigned',
                    label: t('role.management.permissionLabels.annotationModifyAssigned')
                },
            ],
        },
        {
            title: t('role.management.permissionLabels.projectManagementAll'),
            permissions: [
                {value: 'project:create:all', label: t('role.management.permissionLabels.projectCreateAll')},
                {value: 'project:read:all', label: t('role.management.permissionLabels.projectReadAll')},
                {value: 'project:update:all', label: t('role.management.permissionLabels.projectUpdateAll')},
                {value: 'project:archive:all', label: t('role.management.permissionLabels.projectArchiveAll')},
                {value: 'project:delete:all', label: t('role.management.permissionLabels.projectDeleteAll')},
                {value: 'project:assign:all', label: t('role.management.permissionLabels.projectAssignAll')},
                {value: 'project:export:all', label: t('role.management.permissionLabels.projectExportAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.projectManagementAssigned'),
            permissions: [
                {value: 'project:read:assigned', label: t('role.management.permissionLabels.projectReadAssigned')},
                {value: 'project:update:assigned', label: t('role.management.permissionLabels.projectUpdateAssigned')},
                {
                    value: 'project:archive:assigned',
                    label: t('role.management.permissionLabels.projectArchiveAssigned')
                },
                {value: 'project:delete:assigned', label: t('role.management.permissionLabels.projectDeleteAssigned')},
                {value: 'project:assign:assigned', label: t('role.management.permissionLabels.projectAssignAssigned')},
                {value: 'project:export:assigned', label: t('role.management.permissionLabels.projectExportAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.commitManagementAll'),
            permissions: [
                {value: 'commit:create:all', label: t('role.management.permissionLabels.commitCreateAll')},
                {value: 'commit:read:all', label: t('role.management.permissionLabels.commitReadAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.commitManagementAssigned'),
            permissions: [
                {value: 'commit:create:assigned', label: t('role.management.permissionLabels.commitCreateAssigned')},
                {value: 'commit:read:assigned', label: t('role.management.permissionLabels.commitReadAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.branchManagementAll'),
            permissions: [
                {value: 'branch:manage:all', label: t('role.management.permissionLabels.branchManageAll')},
                {value: 'branch:read:all', label: t('role.management.permissionLabels.branchReadAll')},
                {value: 'branch:switch:all', label: t('role.management.permissionLabels.branchSwitchAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.branchManagementAssigned'),
            permissions: [
                {value: 'branch:manage:assigned', label: t('role.management.permissionLabels.branchManageAssigned')},
                {value: 'branch:read:assigned', label: t('role.management.permissionLabels.branchReadAssigned')},
                {value: 'branch:switch:assigned', label: t('role.management.permissionLabels.branchSwitchAssigned')},
            ],
        },
        {
            title: t('role.management.permissionLabels.runtimeManagementAll'),
            permissions: [
                {value: 'loop:read:all', label: t('role.management.permissionLabels.loopReadAll')},
                {value: 'loop:manage:all', label: t('role.management.permissionLabels.loopManageAll')},
                {value: 'round:read:all', label: t('role.management.permissionLabels.jobReadAll')},
                {value: 'round:manage:all', label: t('role.management.permissionLabels.jobManageAll')},
                {value: 'model:read:all', label: t('role.management.permissionLabels.modelReadAll')},
                {value: 'model:manage:all', label: t('role.management.permissionLabels.modelManageAll')},
            ],
        },
        {
            title: t('role.management.permissionLabels.runtimeManagementAssigned'),
            permissions: [
                {value: 'loop:read:assigned', label: t('role.management.permissionLabels.loopReadAssigned')},
                {value: 'loop:manage:assigned', label: t('role.management.permissionLabels.loopManageAssigned')},
                {value: 'round:read:assigned', label: t('role.management.permissionLabels.jobReadAssigned')},
                {value: 'round:manage:assigned', label: t('role.management.permissionLabels.jobManageAssigned')},
                {value: 'model:read:assigned', label: t('role.management.permissionLabels.modelReadAssigned')},
                {value: 'model:manage:assigned', label: t('role.management.permissionLabels.modelManageAssigned')},
            ],
        },
    ];

    // 根据角色类型过滤权限
    if (roleType === 'system') {
        // 系统角色：返回系统级权限（:all）和资源级权限（:all）
        const allCategories = [...systemCategories, ...resourceCategories];
        return filterPermissionCategories(allCategories.map(category => ({
            ...category,
            permissions: category.permissions.filter(p => p.value.endsWith(':all')),
        })).filter(category => category.permissions.length > 0), allowedPermissions);
    } else if (roleType === 'resource') {
        // 资源角色：只返回资源级权限（:assigned），不包含系统级权限
        return filterPermissionCategories(resourceCategories.map(category => ({
            ...category,
            permissions: category.permissions.filter(p => p.value.endsWith(':assigned')),
        })).filter(category => category.permissions.length > 0), allowedPermissions);
    }

    // 没有指定类型，返回所有权限
    return filterPermissionCategories([...systemCategories, ...resourceCategories], allowedPermissions);
};

const RoleManagement: React.FC = () => {
    const {t} = useTranslation();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingRole, setEditingRole] = useState<Role | null>(null);
    const [roleTypeFilter, setRoleTypeFilter] = useState<RoleType | 'all'>('all');
    const [permissionCatalog, setPermissionCatalog] = useState<RolePermissionCatalog | null>(null);
    const [catalogLoading, setCatalogLoading] = useState(false);
    const [form] = Form.useForm();
    const [refreshKey, setRefreshKey] = useState(0);

    // Permission checks
    const {can, isSuperAdmin, isLoading: permissionLoading} = usePermission();
    const canReadRoles = can('role:read') || isSuperAdmin;
    const canCreateRole = can('role:create') || isSuperAdmin;
    const canUpdateRole = can('role:update') || isSuperAdmin;
    const canDeleteRole = can('role:delete') || isSuperAdmin;

    const fetchRoles = useCallback(async (page: number, pageSize: number) => {
        if (!canReadRoles) {
            return createEmptyPaginationResponse<Role>(pageSize, page);
        }
        try {
            const type = roleTypeFilter === 'all' ? undefined : roleTypeFilter;
            return await api.getRoles(type, page, pageSize);
        } catch (error: any) {
            message.error(error.message || t('role.management.fetchError'));
            throw error;
        }
    }, [canReadRoles, roleTypeFilter, t]);

    useEffect(() => {
        if (!permissionLoading && canReadRoles) {
            setRefreshKey((v) => v + 1);
        }
    }, [permissionLoading, canReadRoles, roleTypeFilter]);

    const loadPermissionCatalog = useCallback(async () => {
        if (!canReadRoles) return
        setCatalogLoading(true)
        try {
            const catalog = await api.getPermissionCatalog()
            setPermissionCatalog(catalog)
        } catch (error: any) {
            message.error(error.message || t('role.management.fetchError'))
        } finally {
            setCatalogLoading(false)
        }
    }, [canReadRoles, t])

    useEffect(() => {
        if (!permissionLoading && canReadRoles) {
            void loadPermissionCatalog()
        }
    }, [permissionLoading, canReadRoles, loadPermissionCatalog])

    const getAllowedPermissionSet = useCallback((roleType?: RoleType): Set<string> => {
        if (!permissionCatalog) return new Set()
        if (roleType === 'system') return new Set(permissionCatalog.systemPermissions || [])
        if (roleType === 'resource') return new Set(permissionCatalog.resourcePermissions || [])
        return new Set(permissionCatalog.allPermissions || [])
    }, [permissionCatalog])

    const handleAdd = () => {
        setEditingRole(null);
        form.resetFields();
        form.setFieldsValue({type: 'system', permissions: [], color: 'blue'});
        setIsModalOpen(true);
    };

    // 处理角色类型变更
    const handleRoleTypeChange = (type: RoleType) => {
        const currentPermissions = form.getFieldValue('permissions') || [];
        const allowed = getAllowedPermissionSet(type)
        const validPermissions = currentPermissions.filter((p: string) => allowed.has(p))
        form.setFieldsValue({permissions: validPermissions});
    };

    const handleEdit = (role: Role) => {
        setEditingRole(role);
        form.setFieldsValue({
            name: role.name,
            displayName: role.displayName,
            description: role.description,
            type: role.type,
            color: role.color || 'blue',
            permissions: role.permissions.map(p => p.permission),
        });
        setIsModalOpen(true);
    };

    const handleDelete = async (id: string) => {
        try {
            await api.deleteRole(id);
            message.success(t('role.management.deleteSuccess'));
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('role.management.deleteError'));
        }
    };

    const handleOk = async () => {
        try {
            const values = await form.validateFields();
            const roleType = values.type as RoleType;
            let permissions = values.permissions || [];
            const allowedPermissions = getAllowedPermissionSet(roleType)

            // 验证权限与角色类型匹配
            if (roleType === 'system') {
                const invalidPerms = permissions.filter((p: string) => !allowedPermissions.has(p));
                if (invalidPerms.length > 0) {
                    message.error(t('role.management.invalidPermissionsForSystemRole'));
                    return;
                }
            } else if (roleType === 'resource') {
                const invalidPerms = permissions.filter((p: string) => !allowedPermissions.has(p));
                if (invalidPerms.length > 0) {
                    message.error(t('role.management.invalidPermissionsForResourceRole'));
                    return;
                }
            }

            const permissionCreates: RolePermissionCreate[] = permissions.map((perm: string) => ({
                permission: perm,
            }));

            if (editingRole) {
                // 更新角色
                const updateData: RoleUpdate = {
                    displayName: values.displayName,
                    description: values.description,
                    color: values.color,
                    permissions: permissionCreates,
                };
                await api.updateRole(editingRole.id, updateData);
                message.success(t('role.management.updateSuccess'));
            } else {
                // 创建角色
                const createData: RoleCreate = {
                    name: values.name,
                    displayName: values.displayName,
                    description: values.description,
                    type: roleType,
                    color: values.color || 'blue',
                    permissions: permissionCreates,
                };
                await api.createRole(createData);
                message.success(t('role.management.createSuccess'));
            }
            setIsModalOpen(false);
            form.resetFields();
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('common.operationFailed'));
        }
    };

    const columns = [
        {
            title: t('role.management.name'),
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: t('role.management.displayName'),
            dataIndex: 'displayName',
            key: 'displayName',
            render: (text: string, record: Role) => (
                <div className="flex items-center gap-2">
                    <Tag color={record.color || 'blue'}>{text}</Tag>
                    {record.isSystem && (
                        <Tooltip title={t('role.management.systemRole')}>
                            <LockOutlined className="text-gray-500"/>
                        </Tooltip>
                    )}
                </div>
            ),
        },
        {
            title: t('role.management.description'),
            dataIndex: 'description',
            key: 'description',
            ellipsis: true,
        },
        {
            title: t('role.management.type'),
            dataIndex: 'type',
            key: 'type',
            render: (type: RoleType) => (
                <Tag color={type === 'system' ? 'blue' : 'green'}>
                    {type === 'system' ? t('role.management.system') : t('role.management.resource')}
                </Tag>
            ),
        },
        {
            title: t('role.management.permissionCount'),
            key: 'permissions',
            render: (_: any, record: Role) => (
                <Tag>{record.permissions?.length || 0} {t('role.management.permissions')}</Tag>
            ),
        },
        {
            title: t('common.actions'),
            key: 'action',
            render: (_: any, record: Role) => {
                const isSystemRole = record.isSystem;
                const canEditThisRole = canUpdateRole && !isSystemRole;
                const canDeleteThisRole = canDeleteRole && !isSystemRole;

                return (
                    <div className="flex items-center gap-3">
                        {canEditThisRole ? (
                            <Button type="link" icon={<EditOutlined/>} onClick={() => handleEdit(record)}>
                                {t('common.edit')}
                            </Button>
                        ) : (
                            <Tooltip
                                title={isSystemRole ? t('role.management.cannotEditSystemRole') : t('common.noPermission')}>
                                <Button type="link" icon={<EditOutlined/>} disabled>
                                    {t('common.edit')}
                                </Button>
                            </Tooltip>
                        )}

                        {canDeleteThisRole ? (
                            <Popconfirm
                                title={t('role.management.deleteConfirm')}
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
                                title={isSystemRole ? t('role.management.cannotDeleteSystemRole') : t('common.noPermission')}>
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

    // Show loading state while permissions are being loaded
    if (permissionLoading) {
        return (
            <div className="p-6 text-center">
                <Spin size="large" tip={t('common.loading')}/>
            </div>
        );
    }

    // Show no permission message if user can't read roles
    if (!canReadRoles) {
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
                <span className="m-0 font-semibold">{t('role.management.title')}</span>
                <div className="flex items-center gap-2">
                    <Select
                        value={roleTypeFilter}
                        onChange={(value) => {
                            setRoleTypeFilter(value);
                            setRefreshKey((v) => v + 1);
                        }}
                        className="w-[150px]"
                    >
                        <Select.Option value="all">{t('role.management.allTypes')}</Select.Option>
                        <Select.Option value="system">{t('role.management.system')}</Select.Option>
                        <Select.Option value="resource">{t('role.management.resource')}</Select.Option>
                    </Select>
                    {canCreateRole ? (
                        <Button type="primary" icon={<PlusOutlined/>} onClick={handleAdd}>
                            {t('role.management.addRole')}
                        </Button>
                    ) : (
                        <Tooltip title={t('common.noPermission')}>
                            <Button type="primary" icon={<PlusOutlined/>} disabled>
                                {t('role.management.addRole')}
                            </Button>
                        </Tooltip>
                    )}
                </div>
            </div>
            <div>
                <PaginatedList<Role>
                    fetchData={fetchRoles}
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

            {/* Role Edit/Create Modal */}
            <Modal
                title={editingRole ? t('role.management.editRole') : t('role.management.addRole')}
                open={isModalOpen}
                onOk={handleOk}
                onCancel={() => setIsModalOpen(false)}
                width={800}
                okText={t('common.save')}
                cancelText={t('common.cancel')}
            >
                <Form form={form} layout="vertical">
                    <Form.Item
                        name="name"
                        label={t('role.management.name')}
                        rules={[{required: !editingRole, message: t('role.management.nameRequired')}]}
                    >
                        <Input disabled={!!editingRole} placeholder={t('role.management.namePlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="displayName"
                        label={t('role.management.displayName')}
                        rules={[{required: true, message: t('role.management.displayNameRequired')}]}
                    >
                        <Input placeholder={t('role.management.displayNamePlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="description"
                        label={t('role.management.description')}
                    >
                        <TextArea rows={3} placeholder={t('role.management.descriptionPlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="color"
                        label={t('role.management.color')}
                        rules={[{required: true, message: t('role.management.colorRequired')}]}
                    >
                        <ColorPicker
                            showText
                            presets={[
                                {
                                    label: t('role.management.recommendedColors'),
                                    colors: [
                                        '#1890ff', // blue
                                        '#52c41a', // green
                                        '#faad14', // gold
                                        '#f5222d', // red
                                        '#722ed1', // purple
                                        '#fa8c16', // orange
                                        '#13c2c2', // cyan
                                        '#eb2f96', // magenta
                                        '#2f54eb', // geekblue
                                        '#fa541c', // volcano
                                    ],
                                },
                            ]}
                            format="hex"
                            onChangeComplete={(color) => {
                                form.setFieldsValue({color: color.toHexString()});
                            }}
                        />
                    </Form.Item>
                    <Form.Item
                        name="type"
                        label={t('role.management.type')}
                        rules={[{required: true}]}
                    >
                        <Select
                            disabled={!!editingRole}
                            onChange={handleRoleTypeChange}
                        >
                            <Select.Option value="system">{t('role.management.system')}</Select.Option>
                            <Select.Option value="resource">{t('role.management.resource')}</Select.Option>
                        </Select>
                    </Form.Item>
                    <Form.Item
                        noStyle
                        shouldUpdate={(prevValues, currentValues) => prevValues.type !== currentValues.type}
                    >
                        {({getFieldValue}) => {
                            const roleType = getFieldValue('type') as RoleType | undefined;
                            const categories = getPermissionCategories(t, roleType, getAllowedPermissionSet(roleType));

                            return (
                                <Form.Item
                                    name="permissions"
                                    label={t('role.management.permissions')}
                                >
                                    <Checkbox.Group className="w-full">
                                        <Card size="small" className="max-h-[400px] overflow-y-auto">
                                            {catalogLoading ? (
                                                <div className="flex min-h-[120px] items-center justify-center">
                                                    <Spin size="small"/>
                                                </div>
                                            ) : !roleType ? (
                                                <div className="p-5 text-center text-gray-500">
                                                    {t('role.management.selectRoleTypeFirst')}
                                                </div>
                                            ) : categories.length === 0 ? (
                                                <div className="p-5 text-center text-gray-500">
                                                    {roleType === 'system'
                                                        ? t('role.management.noSystemPermissions')
                                                        : t('role.management.noResourcePermissions')}
                                                </div>
                                            ) : (
                                                categories.map((category, index) => (
                                                    <div key={index} className="mb-4">
                                                        <Title level={5} className="!mb-2 !text-sm">
                                                            {category.title}
                                                        </Title>
                                                        <div className="flex w-full flex-col gap-2">
                                                            {category.permissions.map(perm => (
                                                                <Checkbox key={perm.value} value={perm.value}>
                                                                    <Text>{perm.label}</Text>
                                                                    <Text type="secondary" className="ml-2 text-xs">
                                                                        ({perm.value})
                                                                    </Text>
                                                                </Checkbox>
                                                            ))}
                                                        </div>
                                                        {index < categories.length - 1 && <Divider className="my-3"/>}
                                                    </div>
                                                ))
                                            )}
                                        </Card>
                                    </Checkbox.Group>
                                </Form.Item>
                            );
                        }}
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default RoleManagement;
