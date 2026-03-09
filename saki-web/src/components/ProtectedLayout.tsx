import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Navigate, Outlet, useLocation, useNavigate, useParams} from 'react-router-dom'
import {Trans, useTranslation} from 'react-i18next'
import type {MenuProps} from 'antd'
import {message} from 'antd'
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
    LockOutlined,
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

const EXECUTOR_IDLE_BELL_STORAGE_PREFIX = 'saki.executorIdleBell.v1::'
const EXECUTOR_IDLE_POLLING_INTERVAL_MS = 10_000
const EXECUTOR_IDLE_NOTIFY_DELAY_MS = 30_000

type ExecutorIdleWatchState = {
    hasBusySinceLastNotify: boolean
    idleSinceMs: number | null
    notifiedInCurrentIdle: boolean
}

const buildExecutorIdleBellStorageKey = (apiBaseUrl: string): string =>
    `${EXECUTOR_IDLE_BELL_STORAGE_PREFIX}${apiBaseUrl}`

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
    const canViewProjectModels = canProject('model:read:assigned')
    const canViewProjectInsights =
        canProject('loop:read:assigned') &&
        canProject('round:read:assigned') &&
        canProject('model:read:assigned')
    const canViewProjectSettings =
        canProject('project:update:assigned') ||
        canProject('project:assign:assigned') ||
        canProject('project:archive:assigned')
    const currentYear = new Date().getFullYear()
    const apiBaseUrl = useMemo(() => api.getApiBaseUrl(), [])
    const bellStorageKey = useMemo(() => buildExecutorIdleBellStorageKey(apiBaseUrl), [apiBaseUrl])
    const [executorIdleBellEnabled, setExecutorIdleBellEnabled] = useState(false)
    const idleWatchStateRef = useRef<Map<string, ExecutorIdleWatchState>>(new Map())
    const unsupportedHintShownRef = useRef(false)
    const permissionHintShownRef = useRef(false)

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

    useEffect(() => {
        try {
            const stored = window.localStorage.getItem(bellStorageKey)
            setExecutorIdleBellEnabled(stored === '1')
        } catch {
            setExecutorIdleBellEnabled(false)
        }
    }, [bellStorageKey])

    useEffect(() => {
        try {
            window.localStorage.setItem(bellStorageKey, executorIdleBellEnabled ? '1' : '0')
        } catch {
            // ignore storage failure
        }
    }, [bellStorageKey, executorIdleBellEnabled])

    const notifyExecutorIdleRecovered = useCallback((executorId: string) => {
        const title = t('runtime.executors.messages.idleRecoveredTitle')
        const body = t('runtime.executors.messages.idleRecoveredBody', {executorId})

        if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
            try {
                new Notification(title, {
                    body,
                    tag: `saki-executor-idle::${apiBaseUrl}::${executorId}`,
                })
                return
            } catch {
                // ignore and fallback to in-app message
            }
        }

        message.info(`${title}：${body}`)
    }, [apiBaseUrl, t])

    const handleExecutorIdleBellChange = useCallback(async (enabled: boolean) => {
        setExecutorIdleBellEnabled(enabled)
        message.success(
            enabled
                ? t('layout.header.executorIdleBellEnabledMessage')
                : t('layout.header.executorIdleBellDisabledMessage'),
        )

        if (!enabled) {
            idleWatchStateRef.current.clear()
            return
        }

        if (typeof window === 'undefined' || !('Notification' in window)) {
            if (!unsupportedHintShownRef.current) {
                message.info(t('layout.header.executorIdleBellUnsupported'))
                unsupportedHintShownRef.current = true
            }
            return
        }

        if (Notification.permission === 'default') {
            try {
                const permission = await Notification.requestPermission()
                if (permission !== 'granted' && !permissionHintShownRef.current) {
                    message.info(t('layout.header.executorIdleBellPermissionDenied'))
                    permissionHintShownRef.current = true
                }
            } catch {
                if (!permissionHintShownRef.current) {
                    message.info(t('layout.header.executorIdleBellPermissionDenied'))
                    permissionHintShownRef.current = true
                }
            }
            return
        }

        if (Notification.permission !== 'granted' && !permissionHintShownRef.current) {
            message.info(t('layout.header.executorIdleBellPermissionDenied'))
            permissionHintShownRef.current = true
        }
    }, [t])

    useEffect(() => {
        if (!isAuthenticated || !canViewRuntime || !executorIdleBellEnabled) {
            idleWatchStateRef.current.clear()
            return
        }

        let cancelled = false
        let timer: number | null = null

        const pollExecutors = async () => {
            try {
                const response = await api.getRuntimeExecutors()
                if (cancelled) return

                const now = Date.now()
                const previousStateMap = idleWatchStateRef.current
                const nextStateMap = new Map<string, ExecutorIdleWatchState>()

                for (const executor of response.items || []) {
                    const executorId = String(executor.executorId || '').trim()
                    if (!executorId) continue

                    const prev = previousStateMap.get(executorId) || {
                        hasBusySinceLastNotify: false,
                        idleSinceMs: null,
                        notifiedInCurrentIdle: false,
                    }

                    const status = String(executor.status || '').trim().toLowerCase()
                    const currentTaskId = String(executor.currentTaskId || '').trim()
                    const pendingAssignCount = Number(executor.pendingAssignCount || 0)

                    const isBusyLike = (
                        status === 'busy'
                        || status === 'reserved'
                        || Boolean(currentTaskId)
                        || pendingAssignCount > 0
                    )

                    const isIdle = (
                        Boolean(executor.isOnline)
                        && status === 'idle'
                        && !currentTaskId
                        && pendingAssignCount <= 0
                    )

                    const nextState: ExecutorIdleWatchState = {...prev}

                    if (isBusyLike) {
                        nextState.hasBusySinceLastNotify = true
                        nextState.idleSinceMs = null
                        nextState.notifiedInCurrentIdle = false
                        nextStateMap.set(executorId, nextState)
                        continue
                    }

                    if (isIdle) {
                        const idleSinceMs = prev.idleSinceMs ?? now
                        nextState.idleSinceMs = idleSinceMs
                        if (
                            nextState.hasBusySinceLastNotify
                            && !nextState.notifiedInCurrentIdle
                            && now - idleSinceMs >= EXECUTOR_IDLE_NOTIFY_DELAY_MS
                        ) {
                            notifyExecutorIdleRecovered(executorId)
                            nextState.notifiedInCurrentIdle = true
                            nextState.hasBusySinceLastNotify = false
                        }
                        nextStateMap.set(executorId, nextState)
                        continue
                    }

                    // offline/unknown 时结束当前空闲窗口，等待下一次 busy-like 后再重新计算
                    nextState.idleSinceMs = null
                    nextStateMap.set(executorId, nextState)
                }

                idleWatchStateRef.current = nextStateMap
            } catch {
                // keep silent to avoid noisy global errors
            } finally {
                if (!cancelled) {
                    timer = window.setTimeout(() => {
                        void pollExecutors()
                    }, EXECUTOR_IDLE_POLLING_INTERVAL_MS)
                }
            }
        }

        void pollExecutors()

        return () => {
            cancelled = true
            if (timer != null) {
                window.clearTimeout(timer)
            }
        }
    }, [canViewRuntime, executorIdleBellEnabled, isAuthenticated, notifyExecutorIdleRecovered])

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
            items.push({
                key: 'prediction-tasks',
                label: t('project.tabs.predictionTasks'),
                path: 'prediction-tasks',
                icon: <ClusterOutlined/>,
            })
        }
        if (canViewProjectModels) {
            items.push({key: 'models', label: t('project.tabs.models'), path: 'models', icon: <DatabaseOutlined/>})
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
        canViewProjectModels,
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
        } else if (key === 'change-password') {
            navigate('/profile/change-password')
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
            key: 'change-password',
            icon: <LockOutlined/>,
            label: t('auth.changePassword.title'),
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
            onQuickActionClick={(action) => {
                if (action === 'new-project') {
                    navigate('/projects?create=1')
                    return
                }
                navigate('/datasets?create=1')
            }}
            onRepoOwnerClick={() => navigate('/')}
            onRepoNameClick={() => navigate('/projects')}
            userName={user?.fullName || user?.email}
            userAvatarUrl={user?.avatarUrl}
            userMenuItems={userMenuItems}
            onUserMenuClick={handleUserMenuClick}
            executorIdleBellEnabled={executorIdleBellEnabled}
            onExecutorIdleBellChange={canViewRuntime
                ? (enabled) => {
                    void handleExecutorIdleBellChange(enabled)
                }
                : undefined
            }
            footerText={
                <Trans
                    i18nKey="app.footer"
                    values={{year: currentYear}}
                    components={{
                        author: <a href="https://hhm.moe" target="_blank" rel="noreferrer" className="underline hover:no-underline"/>,
                    }}
                />
            }
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
