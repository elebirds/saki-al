import React, { useMemo } from 'react'
import { Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  AppstoreOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { RepoTabs } from '../../layouts/github/RepoTabs'
import type { NavItem } from '../../layouts/github/types'

const tabItems: NavItem[] = [
  { key: 'overview', label: 'Overview', path: '', icon: <AppstoreOutlined /> },
  { key: 'samples', label: 'Samples & Annotations', path: 'samples', icon: <DatabaseOutlined /> },
  { key: 'loops', label: 'AL Loops', path: 'loops', icon: <ExperimentOutlined /> },
  { key: 'insights', label: 'Insights', path: 'insights', icon: <BarChartOutlined /> },
  { key: 'members', label: 'Members', path: 'members', icon: <TeamOutlined /> },
  { key: 'settings', label: 'Settings', path: 'settings', icon: <SettingOutlined /> },
]

const ProjectLayout: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const activeKey = useMemo(() => {
    if (!projectId) return 'overview'
    const basePath = `/projects/${projectId}`
    const rest = location.pathname.replace(basePath, '')
    if (!rest || rest === '/') return 'overview'
    const segment = rest.split('/').filter(Boolean)[0]
    return tabItems.find((item) => item.path === segment)?.key || 'overview'
  }, [location.pathname, projectId])

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
      <RepoTabs items={tabItems} activeKey={activeKey} onItemClick={handleTabClick} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}

export default ProjectLayout
