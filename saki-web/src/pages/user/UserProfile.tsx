import React, { useEffect, useState } from 'react';
import { Card, Descriptions, Tag, Spin, message, Space, Divider, Typography, List } from 'antd';
import { UserOutlined, SafetyOutlined, LockOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../store/authStore';
import { usePermissionStore } from '../../store/permissionStore';
import { api } from '../../services/api';
import { User } from '../../types';
const { Title, Text } = Typography;

const UserProfile: React.FC = () => {
  const { t } = useTranslation();
  const currentUser = useAuthStore((state) => state.user);
  const permissionStore = usePermissionStore();
  const [userInfo, setUserInfo] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Get permissions from store
  const userPermissions = permissionStore.userPermissions;
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
        message.error(error.message || t('userProfile.fetchError'));
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
        'all': t('userProfile.permissionScope.all'),
        'assigned': t('userProfile.permissionScope.assigned'),
        'self': t('userProfile.permissionScope.self'),
        'owned': t('userProfile.permissionScope.owned'),
      };
      return `${resource}:${action} (${scopeMap[scope] || scope})`;
    }
    return permission;
  };

  if (loading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <Spin size="large" tip={t('common.loading')} />
      </div>
    );
  }

  const displayUser = userInfo || currentUser;
  if (!displayUser) {
    return (
      <div style={{ padding: '24px' }}>
        <Card>
          <Text type="secondary">{t('userProfile.userNotFound')}</Text>
        </Card>
      </div>
    );
  }

  const groupedPermissions = userPermissions ? groupPermissions(userPermissions.permissions) : {};
  const permissionKeys = Object.keys(groupedPermissions);

  return (
    <div style={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column', 
      overflow: 'hidden',
      padding: '24px'
    }}>
      <Title level={2} style={{ marginBottom: 24, flexShrink: 0 }}>
        {t('userProfile.title')}
      </Title>

      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        overflowX: 'hidden',
        paddingRight: '8px'
      }}>
        {/* Basic Information */}
        <Card
          title={
            <Space>
              <UserOutlined />
              <span>{t('userProfile.basicInfo')}</span>
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          <Descriptions column={2} bordered>
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
              <Descriptions.Item label={t('userProfile.isSuperAdmin')}>
                <Tag color="red">{t('common.yes')}</Tag>
              </Descriptions.Item>
            )}
            <Descriptions.Item label={t('userProfile.createdAt')}>
              {formatDate(displayUser.createdAt)}
            </Descriptions.Item>
            {displayUser.updatedAt && (
              <Descriptions.Item label={t('userProfile.updatedAt')}>
                {formatDate(displayUser.updatedAt)}
              </Descriptions.Item>
            )}
            {displayUser.lastLoginAt && (
              <Descriptions.Item label={t('userProfile.lastLoginAt')}>
                {formatDate(displayUser.lastLoginAt)}
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>

        {/* System Roles */}
        <Card
          title={
            <Space>
              <SafetyOutlined />
              <span>{t('userProfile.systemRoles')}</span>
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          {systemRoles.length === 0 ? (
            <Text type="secondary">{t('userProfile.noRoles')}</Text>
          ) : (
            <Space wrap>
              {systemRoles.map((role) => (
                <Tag key={role.id} color={getRoleColor(role.name)} style={{ fontSize: 14, padding: '4px 12px' }}>
                  {role.displayName}
                </Tag>
              ))}
            </Space>
          )}
        </Card>

        {/* Permissions */}
        <Card
          title={
            <Space>
              <LockOutlined />
              <span>{t('userProfile.permissions')}</span>
              {userPermissions && (
                <Text type="secondary" style={{ fontSize: 14, fontWeight: 'normal' }}>
                  ({userPermissions.permissions.length} {t('userProfile.permissions')})
                </Text>
              )}
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          {!userPermissions || userPermissions.permissions.length === 0 ? (
            <Text type="secondary">{t('userProfile.noPermissions')}</Text>
          ) : (
            <div style={{ maxHeight: '500px', overflowY: 'auto', overflowX: 'hidden' }}>
              {permissionKeys.map((resource, index) => (
                <div key={resource}>
                  {index > 0 && <Divider />}
                  <Title level={5} style={{ marginBottom: 12 }}>
                    {t(`userProfile.permissionResources.${resource}`, resource)}
                  </Title>
                  <List
                    size="small"
                    dataSource={groupedPermissions[resource]}
                    renderItem={(permission) => (
                      <List.Item>
                        <Text code>{formatPermission(permission)}</Text>
                      </List.Item>
                    )}
                  />
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

export default UserProfile;
