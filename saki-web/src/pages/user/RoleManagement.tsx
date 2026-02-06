import React, {useCallback, useEffect, useRef, useState} from 'react';
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
    Space,
    Spin,
    Table,
    Tag,
    Tooltip,
    Typography
} from 'antd';
import {DeleteOutlined, EditOutlined, LockOutlined, PlusOutlined} from '@ant-design/icons';
import {Role, RoleCreate, RolePermissionCreate, RoleType, RoleUpdate} from '../../types';
import {api} from '../../services/api';
import {useTranslation} from 'react-i18next';
import {usePermission} from '../../hooks';
import {PaginatedList} from '../../components/common/PaginatedList';

const {TextArea} = Input;
const {Text, Title} = Typography;

// 获取权限分类列表（根据国际化和角色类型过滤）
const getPermissionCategories = (t: (key: string) => string, roleType?: RoleType) => {
    // 系统级权限（只有系统角色可以使用）
    const systemCategories = [
        {
            title: t('roleManagement.permissionLabels.userManagement'),
            permissions: [
                {value: 'user:create:all', label: t('roleManagement.permissionLabels.userCreate')},
                {value: 'user:read:all', label: t('roleManagement.permissionLabels.userRead')},
                {value: 'user:update:all', label: t('roleManagement.permissionLabels.userUpdate')},
                {value: 'user:delete:all', label: t('roleManagement.permissionLabels.userDelete')},
                {value: 'user:list:all', label: t('roleManagement.permissionLabels.userList')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.roleManagement'),
            permissions: [
                {value: 'role:create:all', label: t('roleManagement.permissionLabels.roleCreate')},
                {value: 'role:read:all', label: t('roleManagement.permissionLabels.roleRead')},
                {value: 'role:update:all', label: t('roleManagement.permissionLabels.roleUpdate')},
                {value: 'role:delete:all', label: t('roleManagement.permissionLabels.roleDelete')},
                {value: 'role:assign:all', label: t('roleManagement.permissionLabels.roleAssign')},
                {value: 'role:revoke:all', label: t('roleManagement.permissionLabels.roleRevoke')},
                {value: 'role:assign_admin:all', label: t('roleManagement.permissionLabels.roleAssignAdmin')},
            ],
        },
    ];

    // 资源级权限（系统角色和资源角色都可以使用，但权限范围不同）
    const resourceCategories = [
        {
            title: t('roleManagement.permissionLabels.datasetManagementAll'),
            permissions: [
                {value: 'dataset:create:all', label: t('roleManagement.permissionLabels.datasetCreateAll')},
                {value: 'dataset:read:all', label: t('roleManagement.permissionLabels.datasetReadAll')},
                {value: 'dataset:update:all', label: t('roleManagement.permissionLabels.datasetUpdateAll')},
                {value: 'dataset:delete:all', label: t('roleManagement.permissionLabels.datasetDeleteAll')},
                {value: 'dataset:assign:all', label: t('roleManagement.permissionLabels.datasetAssignAll')},
                {value: 'dataset:export:all', label: t('roleManagement.permissionLabels.datasetExportAll')},
                {value: 'dataset:import:all', label: t('roleManagement.permissionLabels.datasetImportAll')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.datasetManagementAssigned'),
            permissions: [
                {value: 'dataset:read:assigned', label: t('roleManagement.permissionLabels.datasetReadAssigned')},
                {value: 'dataset:update:assigned', label: t('roleManagement.permissionLabels.datasetUpdateAssigned')},
                {value: 'dataset:assign:assigned', label: t('roleManagement.permissionLabels.datasetAssignAssigned')},
                {value: 'dataset:export:assigned', label: t('roleManagement.permissionLabels.datasetExportAssigned')},
                {value: 'dataset:import:assigned', label: t('roleManagement.permissionLabels.datasetImportAssigned')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.sampleManagementAll'),
            permissions: [
                {value: 'sample:read:all', label: t('roleManagement.permissionLabels.sampleReadAll')},
                {value: 'sample:create:all', label: t('roleManagement.permissionLabels.sampleCreateAll')},
                {value: 'sample:update:all', label: t('roleManagement.permissionLabels.sampleUpdateAll')},
                {value: 'sample:delete:all', label: t('roleManagement.permissionLabels.sampleDeleteAll')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.sampleManagementAssigned'),
            permissions: [
                {value: 'sample:read:assigned', label: t('roleManagement.permissionLabels.sampleReadAssigned')},
                {value: 'sample:create:assigned', label: t('roleManagement.permissionLabels.sampleCreateAssigned')},
                {value: 'sample:update:assigned', label: t('roleManagement.permissionLabels.sampleUpdateAssigned')},
                {value: 'sample:delete:assigned', label: t('roleManagement.permissionLabels.sampleDeleteAssigned')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.labelManagementAll'),
            permissions: [
                {value: 'label:read:all', label: t('roleManagement.permissionLabels.labelReadAll')},
                {value: 'label:create:all', label: t('roleManagement.permissionLabels.labelCreateAll')},
                {value: 'label:update:all', label: t('roleManagement.permissionLabels.labelUpdateAll')},
                {value: 'label:delete:all', label: t('roleManagement.permissionLabels.labelDeleteAll')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.labelManagementAssigned'),
            permissions: [
                {value: 'label:read:assigned', label: t('roleManagement.permissionLabels.labelReadAssigned')},
                {value: 'label:create:assigned', label: t('roleManagement.permissionLabels.labelCreateAssigned')},
                {value: 'label:update:assigned', label: t('roleManagement.permissionLabels.labelUpdateAssigned')},
                {value: 'label:delete:assigned', label: t('roleManagement.permissionLabels.labelDeleteAssigned')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.annotationManagementAll'),
            permissions: [
                {value: 'annotation:read:all', label: t('roleManagement.permissionLabels.annotationReadAll')},
                {value: 'annotation:modify:all', label: t('roleManagement.permissionLabels.annotationModifyAll')},
            ],
        },
        {
            title: t('roleManagement.permissionLabels.annotationManagementAssigned'),
            permissions: [
                {value: 'annotation:read:assigned', label: t('roleManagement.permissionLabels.annotationReadAssigned')},
                {
                    value: 'annotation:modify:assigned',
                    label: t('roleManagement.permissionLabels.annotationModifyAssigned')
                },
            ],
        },
        {
            title: t('roleManagement.permissionLabels.annotationManagementSelf'),
            permissions: [
                {value: 'annotation:read:self', label: t('roleManagement.permissionLabels.annotationReadSelf')},
                {value: 'annotation:modify:self', label: t('roleManagement.permissionLabels.annotationModifySelf')},
            ],
        },
    ];

    // 根据角色类型过滤权限
    if (roleType === 'system') {
        // 系统角色：返回系统级权限（:all）和资源级权限（:all）
        const allCategories = [...systemCategories, ...resourceCategories];
        return allCategories.map(category => ({
            ...category,
            permissions: category.permissions.filter(p => p.value.endsWith(':all')),
        })).filter(category => category.permissions.length > 0);
    } else if (roleType === 'resource') {
        // 资源角色：只返回资源级权限（:assigned 和 :self），不包含系统级权限
        return resourceCategories.map(category => ({
            ...category,
            permissions: category.permissions.filter(p => p.value.endsWith(':assigned') || p.value.endsWith(':self')),
        })).filter(category => category.permissions.length > 0);
    }

    // 没有指定类型，返回所有权限
    return [...systemCategories, ...resourceCategories];
};

const RoleManagement: React.FC = () => {
    const {t} = useTranslation();
    const [roles, setRoles] = useState<Role[]>([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingRole, setEditingRole] = useState<Role | null>(null);
    const [roleTypeFilter, setRoleTypeFilter] = useState<RoleType | 'all'>('all');
    const [tableHeight, setTableHeight] = useState<number>(500);
    const tableContainerRef = useRef<HTMLDivElement>(null);
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
            return {items: [], total: 0, limit: pageSize, offset: 0, size: 0} as any;
        }
        try {
            const type = roleTypeFilter === 'all' ? undefined : roleTypeFilter;
            return await api.getRoles(type, page, pageSize);
        } catch (error: any) {
            message.error(error.message || t('roleManagement.fetchError'));
            throw error;
        }
    }, [canReadRoles, roleTypeFilter, t]);

    useEffect(() => {
        if (!permissionLoading && canReadRoles) {
            setRefreshKey((v) => v + 1);
        }
    }, [permissionLoading, canReadRoles, roleTypeFilter]);

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
    }, [roles, roleTypeFilter]); // 当数据或加载状态变化时重新计算

    const handleAdd = () => {
        setEditingRole(null);
        form.resetFields();
        form.setFieldsValue({type: 'system', permissions: [], color: 'blue'});
        setIsModalOpen(true);
    };

    // 处理角色类型变更
    const handleRoleTypeChange = (type: RoleType) => {
        const currentPermissions = form.getFieldValue('permissions') || [];

        // 根据新类型过滤权限
        let validPermissions: string[] = [];
        if (type === 'system') {
            // 系统角色：只保留 :all 权限
            validPermissions = currentPermissions.filter((p: string) => p.endsWith(':all'));
        } else if (type === 'resource') {
            // 资源角色：只保留 :assigned 和 :self 权限
            validPermissions = currentPermissions.filter((p: string) => p.endsWith(':assigned') || p.endsWith(':self'));
        }

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
            message.success(t('roleManagement.deleteSuccess'));
            setRefreshKey((v) => v + 1);
        } catch (error: any) {
            message.error(error.message || t('roleManagement.deleteError'));
        }
    };

    const handleOk = async () => {
        try {
            const values = await form.validateFields();
            const roleType = values.type as RoleType;
            let permissions = values.permissions || [];

            // 验证权限与角色类型匹配
            if (roleType === 'system') {
                // 系统角色只能有 :all 权限
                const invalidPerms = permissions.filter((p: string) => !p.endsWith(':all'));
                if (invalidPerms.length > 0) {
                    message.error(t('roleManagement.invalidPermissionsForSystemRole'));
                    return;
                }
            } else if (roleType === 'resource') {
                // 资源角色只能有 :assigned 和 :self 权限
                const invalidPerms = permissions.filter((p: string) => !p.endsWith(':assigned') && !p.endsWith(':self'));
                if (invalidPerms.length > 0) {
                    message.error(t('roleManagement.invalidPermissionsForResourceRole'));
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
                message.success(t('roleManagement.updateSuccess'));
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
                message.success(t('roleManagement.createSuccess'));
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
            title: t('roleManagement.name'),
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: t('roleManagement.displayName'),
            dataIndex: 'displayName',
            key: 'displayName',
            render: (text: string, record: Role) => (
                <Space>
                    <Tag color={record.color || 'blue'}>{text}</Tag>
                    {record.isSystem && (
                        <Tooltip title={t('roleManagement.systemRole')}>
                            <LockOutlined className="text-gray-500"/>
                        </Tooltip>
                    )}
                </Space>
            ),
        },
        {
            title: t('roleManagement.description'),
            dataIndex: 'description',
            key: 'description',
            ellipsis: true,
        },
        {
            title: t('roleManagement.type'),
            dataIndex: 'type',
            key: 'type',
            render: (type: RoleType) => (
                <Tag color={type === 'system' ? 'blue' : 'green'}>
                    {type === 'system' ? t('roleManagement.system') : t('roleManagement.resource')}
                </Tag>
            ),
        },
        {
            title: t('roleManagement.permissionCount'),
            key: 'permissions',
            render: (_: any, record: Role) => (
                <Tag>{record.permissions?.length || 0} {t('roleManagement.permissions')}</Tag>
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
                    <Space size="middle">
                        {canEditThisRole ? (
                            <Button type="link" icon={<EditOutlined/>} onClick={() => handleEdit(record)}>
                                {t('common.edit')}
                            </Button>
                        ) : (
                            <Tooltip
                                title={isSystemRole ? t('roleManagement.cannotEditSystemRole') : t('common.noPermission')}>
                                <Button type="link" icon={<EditOutlined/>} disabled>
                                    {t('common.edit')}
                                </Button>
                            </Tooltip>
                        )}

                        {canDeleteThisRole ? (
                            <Popconfirm
                                title={t('roleManagement.deleteConfirm')}
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
                                title={isSystemRole ? t('roleManagement.cannotDeleteSystemRole') : t('common.noPermission')}>
                                <Button type="link" danger icon={<DeleteOutlined/>} disabled>
                                    {t('common.delete')}
                                </Button>
                            </Tooltip>
                        )}
                    </Space>
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
        <div className="flex h-full flex-col overflow-hidden p-6">
            <div className="mb-4 flex flex-shrink-0 items-center justify-between">
                <span className="m-0 font-semibold">{t('roleManagement.title')}</span>
                <Space>
                    <Select
                        value={roleTypeFilter}
                        onChange={(value) => {
                            setRoleTypeFilter(value);
                            setRefreshKey((v) => v + 1);
                        }}
                        className="w-[150px]"
                    >
                        <Select.Option value="all">{t('roleManagement.allTypes')}</Select.Option>
                        <Select.Option value="system">{t('roleManagement.system')}</Select.Option>
                        <Select.Option value="resource">{t('roleManagement.resource')}</Select.Option>
                    </Select>
                    {canCreateRole ? (
                        <Button type="primary" icon={<PlusOutlined/>} onClick={handleAdd}>
                            {t('roleManagement.addRole')}
                        </Button>
                    ) : (
                        <Tooltip title={t('common.noPermission')}>
                            <Button type="primary" icon={<PlusOutlined/>} disabled>
                                {t('roleManagement.addRole')}
                            </Button>
                        </Tooltip>
                    )}
                </Space>
            </div>
            <div ref={tableContainerRef} className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <PaginatedList<Role>
                    fetchData={fetchRoles}
                    onItemsChange={setRoles}
                    refreshKey={refreshKey}
                    resetPageOnRefresh
                    initialPageSize={20}
                    pageSizeOptions={['10', '20', '50', '100']}
                    renderItems={(items, loading) => (
                        <Table
                            columns={columns}
                            dataSource={items}
                            rowKey="id"
                            loading={loading}
                            scroll={{y: tableHeight, x: 'max-content'}}
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
                title={editingRole ? t('roleManagement.editRole') : t('roleManagement.addRole')}
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
                        label={t('roleManagement.name')}
                        rules={[{required: !editingRole, message: t('roleManagement.nameRequired')}]}
                    >
                        <Input disabled={!!editingRole} placeholder={t('roleManagement.namePlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="displayName"
                        label={t('roleManagement.displayName')}
                        rules={[{required: true, message: t('roleManagement.displayNameRequired')}]}
                    >
                        <Input placeholder={t('roleManagement.displayNamePlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="description"
                        label={t('roleManagement.description')}
                    >
                        <TextArea rows={3} placeholder={t('roleManagement.descriptionPlaceholder')}/>
                    </Form.Item>
                    <Form.Item
                        name="color"
                        label={t('roleManagement.color')}
                        rules={[{required: true, message: t('roleManagement.colorRequired')}]}
                    >
                        <ColorPicker
                            showText
                            presets={[
                                {
                                    label: t('roleManagement.recommendedColors'),
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
                        label={t('roleManagement.type')}
                        rules={[{required: true}]}
                    >
                        <Select
                            disabled={!!editingRole}
                            onChange={handleRoleTypeChange}
                        >
                            <Select.Option value="system">{t('roleManagement.system')}</Select.Option>
                            <Select.Option value="resource">{t('roleManagement.resource')}</Select.Option>
                        </Select>
                    </Form.Item>
                    <Form.Item
                        noStyle
                        shouldUpdate={(prevValues, currentValues) => prevValues.type !== currentValues.type}
                    >
                        {({getFieldValue}) => {
                            const roleType = getFieldValue('type') as RoleType | undefined;
                            const categories = getPermissionCategories(t, roleType);

                            return (
                                <Form.Item
                                    name="permissions"
                                    label={t('roleManagement.permissions')}
                                >
                                    <Checkbox.Group className="w-full">
                                        <Card size="small" className="max-h-[400px] overflow-y-auto">
                                            {!roleType ? (
                                                <div className="p-5 text-center text-gray-500">
                                                    {t('roleManagement.selectRoleTypeFirst')}
                                                </div>
                                            ) : categories.length === 0 ? (
                                                <div className="p-5 text-center text-gray-500">
                                                    {roleType === 'system'
                                                        ? t('roleManagement.noSystemPermissions')
                                                        : t('roleManagement.noResourcePermissions')}
                                                </div>
                                            ) : (
                                                categories.map((category, index) => (
                                                    <div key={index} className="mb-4">
                                                        <Title level={5} className="!mb-2 !text-sm">
                                                            {category.title}
                                                        </Title>
                                                        <Space direction="vertical" className="w-full">
                                                            {category.permissions.map(perm => (
                                                                <Checkbox key={perm.value} value={perm.value}>
                                                                    <Text>{perm.label}</Text>
                                                                    <Text type="secondary" className="ml-2 text-xs">
                                                                        ({perm.value})
                                                                    </Text>
                                                                </Checkbox>
                                                            ))}
                                                        </Space>
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
