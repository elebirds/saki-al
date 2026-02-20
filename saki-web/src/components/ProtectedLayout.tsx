import React, {useEffect, useMemo} from 'react'
import {Navigate, Outlet, useLocation, useNavigate, useParams} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import type {MenuProps} from 'antd'
import {
    AppstoreOutlined,
    BarChartOutlined,
    BranchesOutlined,
    ClusterOutlined,
    CodeOutlined,
    DatabaseOutlined,
    ExperimentOutlined,
    HistoryOutlined,
    InfoCircleOutlined,
    LogoutOutlined,
    SettingOutlined,
    TeamOutlined,
    UserOutlined
} from '@ant-design/icons'
import {useAuthStore} from '../store/authStore'
import {api} from '../services/api'
import {usePermission, useResourcePermission} from '../hooks'
import {AppShell, type NavItem} from '../layouts'
import {RepoTabs} from '../layouts/github/RepoTabs'

const ProtectedLayout: React.FC = () => {
    const {t, i18n} = useTranslation()
    const location = useLocation()
    const navigate = useNavigate()
    const {projectId} = useParams<{ projectId: string }>()
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
    const logout = useAuthStore((state) => state.logout)
    const user = useAuthStore((state) => state.user)

    const {can, isSuperAdmin} = usePermission()
    const {can: canProject} = useResourcePermission('project', projectId)
    const canManageUsers = can('user:read') || isSuperAdmin
    const canManageRoles = can('role:read') || isSuperAdmin
    const canManageSystemSettings = can('system_setting:read') || isSuperAdmin
    const canViewRuntime = can('round:read') || can('project:read:all') || isSuperAdmin
    const canViewProjectOverview = canProject('project:read:assigned')
    const canViewProjectSamples = canProject('project:read:assigned')
    const canViewProjectBranches = canProject('branch:read:assigned')
    const canViewProjectCommits = canProject('commit:read:assigned')
    const canViewProjectLoops = canProject('loop:manage:assigned') || can('loop:manage') || isSuperAdmin
    const canViewProjectInsights =
        canProject('loop:read:assigned') &&
        canProject('round:read:assigned') &&
        canProject('model:read:assigned')
    const canViewProjectSettings =
        canProject('project:update:assigned') ||
        canProject('project:assign:assigned') ||
        canProject('project:archive:assigned')

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
        ...(canViewRuntime
            ? [{
                key: 'runtime',
                label: 'Runtime',
                path: '/runtime/executors',
                icon: <ClusterOutlined/>,
            }]
            : []),
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
        ...(canManageSystemSettings
            ? [
                {
                    key: 'system-settings',
                    label: t('systemSettings.nav'),
                    path: '/system/settings',
                    icon: <SettingOutlined/>,
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
        if (pathname.startsWith('/system/settings')) return 'system-settings'
        if (pathname.startsWith('/about')) return 'about'
        if (pathname.startsWith('/runtime')) return 'runtime'
        if (pathname.startsWith('/projects')) return 'projects'
        if (pathname === '/' || pathname.startsWith('/datasets')) return 'datasets'
        return 'datasets'
    })()

    const isProjectDetail = /^\/projects\/[^/]+/.test(location.pathname)
    const isWorkspace = /^\/projects\/[^/]+\/workspace/.test(location.pathname)
    const isProjectImport = /^\/projects\/[^/]+\/import/.test(location.pathname)
    const isRuntimeExecutors = /^\/runtime\/executors/.test(location.pathname)
    const showProjectTabs = Boolean(projectId && isProjectDetail)

    const projectTabItems: NavItem[] = useMemo(() => {
        const items: NavItem[] = []
        if (canViewProjectOverview) {
            items.push({key: 'overview', label: t('project.tabs.overview'), path: '', icon: <AppstoreOutlined/>})
        }
        if (canViewProjectSamples) {
            items.push({key: 'samples', label: t('project.tabs.samples'), path: 'samples', icon: <DatabaseOutlined/>})
        }
        if (canViewProjectBranches) {
            items.push({key: 'branches', label: t('project.tabs.branches'), path: 'branches', icon: <BranchesOutlined/>})
        }
        if (canViewProjectCommits) {
            items.push({key: 'commits', label: t('project.tabs.commits'), path: 'commits', icon: <HistoryOutlined/>})
        }
        if (canViewProjectLoops) {
            items.push({key: 'loops', label: t('project.tabs.loops'), path: 'loops', icon: <ExperimentOutlined/>})
        }
        if (canViewProjectInsights) {
            items.push({key: 'insights', label: t('project.tabs.insights'), path: 'insights', icon: <BarChartOutlined/>})
        }
        if (canViewProjectSettings) {
            items.push({key: 'settings', label: t('project.tabs.settings'), path: 'settings', icon: <SettingOutlined/>})
        }
        return items
    }, [
        t,
        canViewProjectOverview,
        canViewProjectSamples,
        canViewProjectBranches,
        canViewProjectCommits,
        canViewProjectLoops,
        canViewProjectInsights,
        canViewProjectSettings,
    ])

    useEffect(() => {
        if (!projectId || !isProjectDetail || projectTabItems.length === 0) return
        const basePath = `/projects/${projectId}`
        const rest = location.pathname.replace(basePath, '')
        if (!rest || rest === '/') return
        const segment = rest.split('/').filter(Boolean)[0]
        const passthroughSegments = new Set(['workspace', 'members', 'import', 'export'])
        if (segment && passthroughSegments.has(segment)) {
            return
        }
        const allowed = new Set(projectTabItems.map((item) => item.path))
        if (segment && !allowed.has(segment)) {
            const first = projectTabItems[0]
            navigate(first.path ? `${basePath}/${first.path}` : basePath, {replace: true})
        }
    }, [projectId, isProjectDetail, projectTabItems, location.pathname, navigate])

    const projectTabActiveKey = useMemo(() => {
        if (!projectId) return 'overview'
        const basePath = `/projects/${projectId}`
        const rest = location.pathname.replace(basePath, '')
        if (!rest || rest === '/') return 'overview'
        const segment = rest.split('/').filter(Boolean)[0]
        return projectTabItems.find((item) => item.path === segment)?.key || 'overview'
    }, [location.pathname, projectId, projectTabItems])

    const handleProjectTabClick = (path: string) => {
        if (!projectId) return
        navigate(path ? `/projects/${projectId}/${path}` : `/projects/${projectId}`)
    }

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

    if (!isAuthenticated) {
        return <Navigate to="/login" replace/>
    }

    if (user?.mustChangePassword && location.pathname !== '/change-password') {
        return <Navigate to="/change-password" replace/>
    }

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
            userAvatarUrl={user?.avatarUrl}
            userMenuItems={userMenuItems}
            onUserMenuClick={handleUserMenuClick}
            footerText={t('app.footer')}
            showHeaderBorder={!isProjectDetail}
            headerSubnav={
                showProjectTabs && projectTabItems.length > 0 ? (
                    <RepoTabs
                        items={projectTabItems}
                        activeKey={projectTabActiveKey}
                        onItemClick={handleProjectTabClick}
                    />
                ) : undefined
            }
            layoutMode={isWorkspace ? 'fill' : 'flow'}
            contentClassName={
                isWorkspace
                    ? 'px-6 w-full h-full flex flex-col'
                    : isProjectImport
                        ? 'px-6 py-6 w-full h-full flex flex-col'
                    : isRuntimeExecutors
                        ? 'px-6 py-6 w-full h-full flex flex-col'
                    : isProjectDetail
                            ? 'max-w-[1280px] mx-auto px-6 pt-6 min-h-full flex flex-col'
                        : 'max-w-[1280px] mx-auto px-6 py-6 min-h-full flex flex-col'
            }
            contentCardClassName={
                isProjectDetail || isRuntimeExecutors
                    ? 'bg-transparent border-0 p-0 h-full flex flex-col'
                    : 'bg-github-panel rounded-md p-6 min-h-full flex flex-col shadow-[0_2px_8px_rgba(27,31,36,0.12)]'
            }
        >
            <Outlet/>
        </AppShell>
    )
}

export default ProtectedLayout
