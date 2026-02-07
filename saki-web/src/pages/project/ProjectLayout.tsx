import React, {useMemo} from 'react'
import {Outlet, useLocation, useNavigate, useParams} from 'react-router-dom'
import {
    AppstoreOutlined,
    BarChartOutlined,
    BranchesOutlined,
    DatabaseOutlined,
    ExperimentOutlined,
    HistoryOutlined,
    SettingOutlined,
} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'
import {RepoTabs} from '../../layouts/github/RepoTabs'
import type {NavItem} from '../../layouts/github/types'

const ProjectLayout: React.FC = () => {
    const {t} = useTranslation()
    const {projectId} = useParams<{ projectId: string }>()
    const location = useLocation()
    const navigate = useNavigate()

    const tabItems: NavItem[] = useMemo(() => [
        {key: 'overview', label: t('project.tabs.overview'), path: '', icon: <AppstoreOutlined/>},
        {key: 'samples', label: t('project.tabs.samples'), path: 'samples', icon: <DatabaseOutlined/>},
        {key: 'branches', label: t('project.tabs.branches'), path: 'branches', icon: <BranchesOutlined/>},
        {key: 'commits', label: t('project.tabs.commits'), path: 'commits', icon: <HistoryOutlined/>},
        {key: 'loops', label: t('project.tabs.loops'), path: 'loops', icon: <ExperimentOutlined/>},
        {key: 'insights', label: t('project.tabs.insights'), path: 'insights', icon: <BarChartOutlined/>},
        {key: 'settings', label: t('project.tabs.settings'), path: 'settings', icon: <SettingOutlined/>},
    ], [t])

    const activeKey = useMemo(() => {
        if (!projectId) return 'overview'
        const basePath = `/projects/${projectId}`
        const rest = location.pathname.replace(basePath, '')
        if (!rest || rest === '/') return 'overview'
        const segment = rest.split('/').filter(Boolean)[0]
        return tabItems.find((item) => item.path === segment)?.key || 'overview'
    }, [location.pathname, projectId, tabItems])

    const handleTabClick = (path: string) => {
        if (!projectId) return
        if (!path) {
            navigate(`/projects/${projectId}`)
        } else {
            navigate(`/projects/${projectId}/${path}`)
        }
    }

    return (
        <div className="flex h-full flex-col gap-6">
            <RepoTabs items={tabItems} activeKey={activeKey} onItemClick={handleTabClick}/>
            <div className="flex-1 overflow-hidden">
                <Outlet/>
            </div>
        </div>
    )
}

export default ProjectLayout
