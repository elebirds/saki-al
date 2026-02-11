import React, {useEffect} from 'react'
import {Navigate, Outlet, useLocation, useNavigate} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import type {MenuProps} from 'antd'
import {
    AppstoreOutlined,
    ClusterOutlined,
    CodeOutlined,
    InfoCircleOutlined,
    LogoutOutlined,
    TeamOutlined,
    UserOutlined
} from '@ant-design/icons'
import {useAuthStore} from '../store/authStore'
import {api} from '../services/api'
import {usePermission} from '../hooks'
import {AppShell, type NavItem} from '../layouts'

const ProtectedLayout: React.FC = () => {
    const {t, i18n} = useTranslation()
    const location = useLocation()
    const navigate = useNavigate()
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
    const logout = useAuthStore((state) => state.logout)
    const user = useAuthStore((state) => state.user)

    const {can, isSuperAdmin} = usePermission()
    const canManageUsers = can('user:read') || isSuperAdmin
    const canManageRoles = can('role:read') || isSuperAdmin

    useEffect(() => {
        let interval: number
        if (isAuthenticated) {
            interval = window.setInterval(async () => {
                try {
                    const response = await api.refreshToken()
                    const setTokens = useAuthStore.getState().setTokens
                    setTokens(response.accessToken, response.refreshToken)
                } catch (error) {
                    console.error('Token refresh failed', error)
                }
            }, 5 * 60 * 1000)
        }
        return () => {
            if (interval) window.clearInterval(interval)
        }
    }, [isAuthenticated])

    if (!isAuthenticated) {
        return <Navigate to="/login" replace/>
    }

    if (user?.mustChangePassword && location.pathname !== '/change-password') {
        return <Navigate to="/change-password" replace/>
    }

    const changeLanguage = (lng: string) => {
        i18n.changeLanguage(lng)
    }

    const navItems: NavItem[] = [
        {
            key: 'datasets',
            label: t('app.datasets'),
            path: '/',
            icon: <CodeOutlined/>,
        },
        {
            key: 'projects',
            label: t('app.projects'),
            path: '/projects',
            icon: <AppstoreOutlined/>,
        },
        {
            key: 'runtime',
            label: 'Runtime',
            path: '/runtime/executors',
            icon: <ClusterOutlined/>,
        },
        ...(canManageUsers
            ? [
                {
                    key: 'users',
                    label: t('user.management.title'),
                    path: '/users',
                    icon: <TeamOutlined/>,
                },
            ]
            : []),
        ...(canManageRoles
            ? [
                {
                    key: 'roles',
                    label: t('role.management.title'),
                    path: '/roles',
                    icon: <UserOutlined/>,
                },
            ]
            : []),
        {
            key: 'about',
            label: t('app.about'),
            path: '/about',
            icon: <InfoCircleOutlined/>,
        },
    ]

    const activeNavKey = (() => {
        const pathname = location.pathname
        if (pathname.startsWith('/users')) return 'users'
        if (pathname.startsWith('/roles')) return 'roles'
        if (pathname.startsWith('/about')) return 'about'
        if (pathname.startsWith('/runtime')) return 'runtime'
        if (pathname.startsWith('/projects')) return 'projects'
        if (pathname === '/' || pathname.startsWith('/datasets')) return 'datasets'
        return 'datasets'
    })()

    const isProjectDetail = /^\/projects\/[^/]+/.test(location.pathname)
    const isWorkspace = /^\/projects\/[^/]+\/workspace/.test(location.pathname)
    const isRuntimeExecutors = /^\/runtime\/executors/.test(location.pathname)

    const handleUserMenuClick: MenuProps['onClick'] = ({key}) => {
        if (key === 'profile') {
            navigate('/profile')
        } else if (key === 'logout') {
            logout()
        }
    }

    const userMenuItems: MenuProps['items'] = [
        {
            key: 'profile',
            icon: <UserOutlined/>,
            label: t('user.profile.title'),
        },
        {
            type: 'divider',
        },
        {
            key: 'logout',
            icon: <LogoutOutlined/>,
            label: t('auth.logout'),
        },
    ]

    return (
        <AppShell
            appTitle={t('app.title')}
            repoOwner="saki"
            repoName="saki-web"
            navItems={navItems}
            activeNavKey={activeNavKey}
            onNavItemClick={(path) => navigate(path)}
            language={i18n.language}
            languageOptions={[
                {value: 'en', label: t('common.language.english')},
                {value: 'zh', label: t('common.language.chinese')},
            ]}
            onLanguageChange={changeLanguage}
            userName={user?.fullName || user?.email}
            userMenuItems={userMenuItems}
            onUserMenuClick={handleUserMenuClick}
            footerText={t('app.footer')}
            showHeaderBorder={!isProjectDetail}
            contentClassName={
                isWorkspace
                    ? 'px-6 w-full h-full flex flex-col'
                    : isRuntimeExecutors
                        ? 'px-6 py-6 w-full h-full flex flex-col'
                    : isProjectDetail
                        ? 'max-w-[1280px] mx-auto px-6 h-full flex flex-col'
                        : 'max-w-[1280px] mx-auto px-6 py-6 h-full flex flex-col'
            }
            contentCardClassName={
                isProjectDetail || isRuntimeExecutors
                    ? 'bg-transparent border-0 p-0 h-full flex flex-col'
                    : 'bg-github-panel rounded-md p-6 h-full flex flex-col shadow-[0_2px_8px_rgba(27,31,36,0.12)]'
            }
        >
            <Outlet/>
        </AppShell>
    )
}

export default ProtectedLayout
