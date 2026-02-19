import React, {useEffect, useRef, useState} from 'react';
import {Avatar, Button, Card, Collapse, Descriptions, message, Spin, Tag, Typography} from 'antd';
import {CameraOutlined, LockOutlined, SafetyOutlined, UserOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {useAuthStore} from '../../store/authStore';
import {usePermissionStore} from '../../store/permissionStore';
import {api} from '../../services/api';
import {User} from '../../types';
import {AvatarCropModal} from '../../components/user/AvatarCropModal';

const {Title, Text} = Typography;
const MAX_AVATAR_SIZE_BYTES = 10 * 1024 * 1024;

const UserProfile: React.FC = () => {
    const {t} = useTranslation();
    const currentUser = useAuthStore((state) => state.user);
    const setAuthUser = useAuthStore((state) => state.setUser);
    const permissionStore = usePermissionStore();
    const [userInfo, setUserInfo] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [avatarModalOpen, setAvatarModalOpen] = useState(false);
    const [avatarSourceFile, setAvatarSourceFile] = useState<File | null>(null);
    const [avatarUploading, setAvatarUploading] = useState(false);
    const avatarInputRef = useRef<HTMLInputElement | null>(null);

    // Get permissions from store
    const systemPermissions = permissionStore.systemPermissions;
    const systemRoles = permissionStore.getSystemRoles();
    const isSuperAdmin = permissionStore.isSuperAdmin();

    useEffect(() => {
        const fetchUserInfo = async () => {
            if (!currentUser) {
                setLoading(false);
                return;
            }

            try {
                setLoading(true);
                const data = await api.getCurrentUser();
                setUserInfo(data);
            } catch (error: any) {
                message.error(error.message || t('user.profile.fetchError'));
            } finally {
                setLoading(false);
            }
        };

        fetchUserInfo();
    }, [currentUser, t]);

    // Format date
    const formatDate = (dateString?: string) => {
        if (!dateString) return '-';
        try {
            const date = new Date(dateString);
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const seconds = String(date.getSeconds()).padStart(2, '0');
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        } catch {
            return dateString;
        }
    };

    // Get role color
    const getRoleColor = (roleName: string): string => {
        const colors: Record<string, string> = {
            'super_admin': 'red',
            'admin': 'gold',
            'user': 'blue',
            'annotator': 'green',
            'viewer': 'default',
        };
        return colors[roleName] || 'default';
    };

    // Group permissions by resource
    const groupPermissions = (permissions: string[]) => {
        const grouped: Record<string, string[]> = {};
        permissions.forEach(perm => {
            const [resource] = perm.split(':');
            if (!grouped[resource]) {
                grouped[resource] = [];
            }
            grouped[resource].push(perm);
        });
        return grouped;
    };

    // Format permission for display
    const formatPermission = (permission: string): string => {
        const parts = permission.split(':');
        if (parts.length >= 3) {
            const [resource, action, scope] = parts;
            const scopeMap: Record<string, string> = {
                'all': t('user.profile.permissionScope.all'),
                'assigned': t('user.profile.permissionScope.assigned'),
            };
            return `${resource}:${action} (${scopeMap[scope] || scope})`;
        }
        return permission;
    };

    const handleAvatarSelectClick = () => {
        avatarInputRef.current?.click();
    };

    const handleAvatarSourceChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) {
            return;
        }
        if (!file.type.startsWith('image/')) {
            message.error(t('user.profile.avatarFileTypeError'));
            return;
        }
        if (file.size > MAX_AVATAR_SIZE_BYTES) {
            message.error(t('user.profile.avatarFileSizeError'));
            return;
        }
        setAvatarSourceFile(file);
        setAvatarModalOpen(true);
    };

    const handleAvatarModalCancel = () => {
        if (avatarUploading) {
            return;
        }
        setAvatarModalOpen(false);
        setAvatarSourceFile(null);
    };

    const handleAvatarConfirm = async (croppedFile: File) => {
        try {
            setAvatarUploading(true);
            const updatedUser = await api.uploadUserAvatar(croppedFile);
            setUserInfo(updatedUser);
            if (currentUser) {
                setAuthUser({...currentUser, ...updatedUser});
            } else {
                setAuthUser(updatedUser);
            }
            setAvatarModalOpen(false);
            setAvatarSourceFile(null);
            message.success(t('user.profile.avatarUploadSuccess'));
        } catch (error: any) {
            message.error(error.message || t('user.profile.avatarUploadError'));
        } finally {
            setAvatarUploading(false);
        }
    };

    if (loading) {
        return (
            <div className="p-6 text-center">
                <Spin size="large" tip={t('common.loading')}/>
            </div>
        );
    }

    const displayUser = userInfo || currentUser;
    if (!displayUser) {
        return (
            <div className="p-6">
                <Card>
                    <Text type="secondary">{t('user.profile.userNotFound')}</Text>
                </Card>
            </div>
        );
    }

    const groupedPermissions = systemPermissions ? groupPermissions(systemPermissions.permissions) : {};
    const permissionKeys = Object.keys(groupedPermissions);
    const displayName = displayUser.fullName || displayUser.email || '-';
    const displayInitial = displayName ? displayName.charAt(0).toUpperCase() : 'U';

    return (
        <div className="flex h-full flex-col gap-6 overflow-hidden p-6">
            <input
                ref={avatarInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={handleAvatarSourceChange}
            />
            <div className="flex-shrink-0">
                <Title level={2} className="!mb-0">
                    {t('user.profile.title')}
                </Title>
            </div>

            <div className="flex-1 overflow-y-auto pr-2">
                <div
                    className="rounded-2xl border border-github-border bg-gradient-to-r from-[var(--github-panel)] via-[var(--github-base)] to-[var(--github-panel)] p-6">
                    <div className="flex flex-wrap items-center gap-4">
                        <Avatar
                            size={64}
                            src={displayUser.avatarUrl}
                            icon={<UserOutlined/>}
                            className="bg-gradient-to-br from-orange-400 to-pink-500"
                        >
                            {displayInitial}
                        </Avatar>
                        <div>
                            <div className="text-lg font-semibold text-github-text">{displayName}</div>
                            <div className="text-sm text-github-muted">{displayUser.email}</div>
                        </div>
                        <div className="ml-auto flex flex-wrap items-center gap-2">
                            <Button
                                icon={<CameraOutlined/>}
                                onClick={handleAvatarSelectClick}
                                loading={avatarUploading}
                            >
                                {t('user.profile.uploadAvatar')}
                            </Button>
                            <Tag color={displayUser.isActive ? 'green' : 'red'}>
                                {displayUser.isActive ? t('common.active') : t('common.inactive')}
                            </Tag>
                            {isSuperAdmin && <Tag color="red">{t('common.yes')}</Tag>}
                        </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-6 text-xs text-github-muted">
                        <span>{t('user.profile.createdAt')}: {formatDate(displayUser.createdAt)}</span>
                        {displayUser.updatedAt &&
                            <span>{t('user.profile.updatedAt')}: {formatDate(displayUser.updatedAt)}</span>}
                        {displayUser.lastLoginAt &&
                            <span>{t('user.profile.lastLoginAt')}: {formatDate(displayUser.lastLoginAt)}</span>}
                    </div>
                </div>

                <div className="mt-6 grid gap-6 lg:grid-cols-[360px,1fr]">
                    <div className="space-y-6">
                        <Card
                            className="!border-github-border !bg-github-panel"
                            title={
                                <div className="flex items-center gap-2">
                                    <UserOutlined/>
                                    <span>{t('user.profile.basicInfo')}</span>
                                </div>
                            }
                        >
                            <Descriptions column={1} bordered={false} size="small">
                                <Descriptions.Item label={t('common.email')}>
                                    {displayUser.email}
                                </Descriptions.Item>
                                <Descriptions.Item label={t('common.fullName')}>
                                    {displayUser.fullName || '-'}
                                </Descriptions.Item>
                                <Descriptions.Item label={t('common.status')}>
                                    <Tag color={displayUser.isActive ? 'green' : 'red'}>
                                        {displayUser.isActive ? t('common.active') : t('common.inactive')}
                                    </Tag>
                                </Descriptions.Item>
                                {isSuperAdmin && (
                                    <Descriptions.Item label={t('user.profile.isSuperAdmin')}>
                                        <Tag color="red">{t('common.yes')}</Tag>
                                    </Descriptions.Item>
                                )}
                            </Descriptions>
                        </Card>

                        <Card
                            className="!border-github-border !bg-github-panel"
                            title={
                                <div className="flex items-center gap-2">
                                    <SafetyOutlined/>
                                    <span>{t('user.profile.systemRoles')}</span>
                                </div>
                            }
                        >
                            {systemRoles.length === 0 ? (
                                <Text type="secondary">{t('user.profile.noRoles')}</Text>
                            ) : (
                                <div className="flex flex-wrap gap-2">
                                    {systemRoles.map((role) => (
                                        <Tag key={role.id} color={getRoleColor(role.name)}
                                             className="px-3 py-1 text-sm">
                                            {role.displayName}
                                        </Tag>
                                    ))}
                                </div>
                            )}
                        </Card>
                    </div>

                    <Card
                        className="!border-github-border !bg-github-panel"
                        title={
                            <div className="flex items-center gap-2">
                                <LockOutlined/>
                                <span>{t('user.profile.permissions')}</span>
                                {systemPermissions && (
                                    <Text type="secondary" className="text-sm font-normal">
                                        ({systemPermissions.permissions.length} {t('user.profile.permissions')})
                                    </Text>
                                )}
                            </div>
                        }
                    >
                        {!systemPermissions || systemPermissions.permissions.length === 0 ? (
                            <Text type="secondary">{t('user.profile.noPermissions')}</Text>
                        ) : (
                            <div className="max-h-[560px] overflow-y-auto pr-1">
                                <Collapse
                                    ghost
                                    items={permissionKeys.map((resource) => ({
                                        key: resource,
                                        label: (
                                            <span className="text-sm font-medium text-github-text">
                        {t(`user.profile.permissionResources.${resource}`, resource)}
                      </span>
                                        ),
                                        children: (
                                            <div className="flex flex-wrap gap-2 pt-2">
                                                {groupedPermissions[resource].map((permission) => (
                                                    <Tag key={permission} className="text-xs">
                                                        {formatPermission(permission)}
                                                    </Tag>
                                                ))}
                                            </div>
                                        ),
                                    }))}
                                />
                            </div>
                        )}
                    </Card>
                </div>
            </div>
            <AvatarCropModal
                open={avatarModalOpen}
                sourceFile={avatarSourceFile}
                uploading={avatarUploading}
                onCancel={handleAvatarModalCancel}
                onConfirm={handleAvatarConfirm}
            />
        </div>
    );
};

export default UserProfile;
