import React from 'react'
import { Button, Dropdown, Tag } from 'antd'
import type { MenuProps } from 'antd'
import { DownOutlined, EyeOutlined, ForkOutlined, StarOutlined } from '@ant-design/icons'
import type { RepoStat } from './types'

export type RepoHeaderProps = {
  title: string
  visibilityLabel?: string
  stats?: RepoStat[]
}

const defaultStats: RepoStat[] = [
  { label: 'Watch', count: 0 },
  { label: 'Fork', count: 0 },
  { label: 'Star', count: 0 },
]

const iconMap: Record<string, React.ReactNode> = {
  Watch: <EyeOutlined />,
  Fork: <ForkOutlined />,
  Star: <StarOutlined />,
}

export const RepoHeader: React.FC<RepoHeaderProps> = ({ title, visibilityLabel = 'Private', stats }) => {
  const resolvedStats = stats || defaultStats

  return (
    <div className="flex items-center justify-between mb-6">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-green-400 to-blue-500" />
        <h1 className="text-xl font-semibold text-github-text">{title}</h1>
        <Tag className="!bg-transparent !text-github-muted !border-github-border !rounded-full">
          {visibilityLabel}
        </Tag>
      </div>

      <div className="flex items-center gap-2">
        {resolvedStats.map((stat) => {
          const menuItems: MenuProps['items'] = stat.menuItems || [
            { key: `${stat.label.toLowerCase()}-all`, label: `View all ${stat.label.toLowerCase()}` },
          ]

          return (
            <div key={stat.label} className="flex items-center">
              <Button
                className="!bg-github-input !border-github-border !text-github-text !rounded-r-none"
                icon={iconMap[stat.label]}
              >
                <span className="mr-1">{stat.label}</span>
                <span className="ml-1 px-1.5 py-0.5 rounded bg-github-badge text-xs text-github-text">
                  {stat.count}
                </span>
              </Button>
              <Dropdown menu={{ items: menuItems }} placement="bottomRight">
                <Button className="!bg-github-input !border-github-border !text-github-text !rounded-l-none">
                  <DownOutlined />
                </Button>
              </Dropdown>
            </div>
          )
        })}
      </div>
    </div>
  )
}
