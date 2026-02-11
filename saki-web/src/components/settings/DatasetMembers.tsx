import React, {useEffect, useState} from 'react';
import {Button, Form, message, Modal, Popconfirm, Select, Spin, Table, Tag, Typography} from 'antd';
import {DeleteOutlined, EditOutlined, UserAddOutlined} from '@ant-design/icons';
import {ResourceMember, RoleInfo} from '../../types';
import {api} from '../../services/api';
import {useTranslation} from 'react-i18next';
import {usePermission, useResourcePermission} from '../../hooks';

const {Title} = Typography;

interface UserListItem {
    id: string;
    email: string;
    fullName?: string;
}

interface DatasetMembersProps {
    datasetId: string;
    ownerId?: string;
}

const DatasetMembers: React.FC<DatasetMembersProps> = ({datasetId, ownerId}) => {
    const {t} = useTranslation();
    const [members, setMembers] = useState<ResourceMember[]>([]);
    const [users, setUsers] = useState<UserListItem[]>([]);
    const [availableRoles, setAvailableRoles] = useState<RoleInfo[]>([]);
    const [loading, setLoading] = useState(false);
    const [rolesLoading, setRolesLoading] = useState(false);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingMember, setEditingMember] = useState<ResourceMember | null>(null);
    const [form] = Form.useForm();

    // Permission hooks
    const {can} = useResourcePermission('dataset', datasetId);
    const {can: canSystem, isSuperAdmin} = usePermission();
    const canManageMembers = can('dataset:assign');
    // Use user:list permission (not user:read) for member selection
    const canListUsers = canSystem('user:list') || can('user:list') || isSuperAdmin;

    const fetchMembers = async () => {
        setLoading(true);
        try {
            const data = await api.getDatasetMembers(datasetId);
            setMembers(data);
        } catch (error: any) {
            message.error(error.message || t('dataset.members.fetchError'));
        } finally {
            setLoading(false);
        }
    };

    const fetchUsers = async () => {
        try {
            // Use getUserList API (requires user:list permission)
            const data = await api.getUserList();
            setUsers(data.items);
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
        // Fetch users list if user has permission
        if (canManageMembers && canListUsers) {
            fetchUsers();
        }
        if (canManageMembers) {
            fetchAvailableRoles();
        }
    }, [datasetId, canManageMembers, canListUsers]);

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
            message.success(t('dataset.members.removeSuccess'));
            fetchMembers();
        } catch (error: any) {
            message.error(error.message || t('dataset.members.removeError'));
        }
    };

    const handleOk = async () => {
        try {
            const values = await form.validateFields();
            if (editingMember) {
                await api.updateDatasetMemberRole(datasetId, editingMember.userId, {roleId: values.roleId});
                message.success(t('dataset.members.updateRoleSuccess'));
            } else {
                await api.addDatasetMember(datasetId, {userId: values.userId, roleId: values.roleId});
                message.success(t('dataset.members.addMemberSuccess'));
            }
            setIsModalOpen(false);
            fetchMembers();
        } catch (error: any) {
            message.error(error.message || t('common.operationFailed'));
        }
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
                <Tag color={record.roleColor || 'blue'}>
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
                    <div className="flex items-center gap-3">
                        <Button
                            type="link"
                            icon={<EditOutlined/>}
                            onClick={() => handleEdit(record)}
                            disabled={isOwnerMember || !canManageMembers}
                        >
                            {t('common.edit')}
                        </Button>
                        <Popconfirm
                            title={t('dataset.members.removeConfirm')}
                            onConfirm={() => handleDelete(record.userId)}
                            okText={t('common.yes')}
                            cancelText={t('common.no')}
                            disabled={isOwnerMember || !canManageMembers}
                        >
                            <Button
                                type="link"
                                danger
                                icon={<DeleteOutlined/>}
                                disabled={isOwnerMember || !canManageMembers}
                            >
                                {t('common.delete')}
                            </Button>
                        </Popconfirm>
                    </div>
                );
            },
        },
    ];

    return (
        <div>
            <div className="mb-4 flex items-center justify-between">
                <Title level={5}>{t('dataset.members.title')}</Title>
                {canManageMembers && (
                    <Button type="primary" icon={<UserAddOutlined/>} onClick={handleAdd}>
                        {t('dataset.members.addMember')}
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
                title={editingMember ? t('dataset.members.editMemberRole') : t('dataset.members.addMember')}
                open={isModalOpen}
                onOk={handleOk}
                onCancel={() => setIsModalOpen(false)}
            >
                {rolesLoading ? (
                    <div className="p-5 text-center">
                        <Spin tip={t('common.loading')}/>
                    </div>
                ) : (
                    <Form form={form} layout="vertical">
                        {!editingMember && (
                            <Form.Item
                                name="userId"
                                label={t('dataset.members.user')}
                                rules={[{required: true, message: t('dataset.members.selectUserRequired')}]}
                            >
                                <Select
                                    showSearch
                                    placeholder={t('dataset.members.selectUser')}
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
                            rules={[{required: true, message: t('dataset.members.selectRoleRequired')}]}
                        >
                            <Select placeholder={t('dataset.members.selectRole')}>
                                {availableRoles
                                    .filter(role => {
                                        return !role.isSupremo;
                                    })
                                    .map(role => (
                                        <Select.Option key={role.id} value={role.id}>
                                            <div>
                                                <span>{role.displayName}</span>
                                                <span className="ml-2 text-xs text-gray-400">
                          {role.description}
                        </span>
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
