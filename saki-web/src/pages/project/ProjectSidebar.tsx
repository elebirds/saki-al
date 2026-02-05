import React from 'react'
import { Avatar, Button, Tag } from 'antd'
import { DatabaseOutlined, ForkOutlined, NodeIndexOutlined } from '@ant-design/icons'
import { ResourceMember } from '../../types'

export interface ProjectSidebarProps {
  description?: string | null
  taskTypeLabel?: string
  statusLabel?: string
  stats: {
    datasets: number
    labels: number
    branches: number
    commits: number
    members?: number
  }
  members?: ResourceMember[]
  sampleStatus?: {
    labeled: number
    unlabeled: number
    skipped: number
    total: number
  }
}

const statusColors: Record<string, string> = {
  Active: 'green',
  Archived: 'default',
}

const ProjectSidebar: React.FC<ProjectSidebarProps> = ({
  description,
  taskTypeLabel,
  statusLabel,
  stats,
  members,
  sampleStatus,
}) => {
  const totalSamples = sampleStatus?.total || 0
  const segments = totalSamples
    ? [
        { label: 'Labeled', value: sampleStatus?.labeled || 0, color: '#2da44e' },
        { label: 'Unlabeled', value: sampleStatus?.unlabeled || 0, color: '#d29922' },
        { label: 'Skipped', value: sampleStatus?.skipped || 0, color: '#8b949e' },
      ]
    : []

  return (
    <aside className="w-[296px] shrink-0 hidden lg:block">
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-github-text">About</h3>
          <DatabaseOutlined className="text-github-muted" />
        </div>
        <p className="text-sm mb-4 text-github-text">
          {description || 'No description provided.'}
        </p>
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2 text-github-muted">
            <NodeIndexOutlined />
            <span className="text-github-text">{taskTypeLabel}</span>
          </div>
          <div className="flex items-center gap-2 text-github-muted">
            <ForkOutlined />
            <Tag color={statusColors[statusLabel || ''] || 'default'}>{statusLabel}</Tag>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-github-muted">
            <div>
              <span className="text-github-text font-semibold">{stats.datasets}</span> datasets
            </div>
            <div>
              <span className="text-github-text font-semibold">{stats.labels}</span> labels
            </div>
            <div>
              <span className="text-github-text font-semibold">{stats.branches}</span> branches
            </div>
            <div>
              <span className="text-github-text font-semibold">{stats.commits}</span> commits
            </div>
            {typeof stats.members === 'number' ? (
              <div>
                <span className="text-github-text font-semibold">{stats.members}</span> members
              </div>
            ) : null}
          </div>
        </div>

        {members && members.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {members.slice(0, 5).map((member) => (
              <Avatar
                key={member.id}
                size={28}
                src={member.userAvatarUrl}
              >
                {(member.userFullName || member.userEmail || 'U').charAt(0).toUpperCase()}
              </Avatar>
            ))}
            {members.length > 5 ? (
              <span className="text-xs text-github-muted">+{members.length - 5}</span>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="border-t border-github-border pt-4 mb-4">
        <h3 className="font-semibold text-github-text mb-2">AL Loops</h3>
        <p className="text-sm text-github-muted mb-1">No loops yet</p>
        <Button type="link" className="!text-github-link !p-0" disabled>
          Coming soon
        </Button>
      </div>

      <div className="border-t border-github-border pt-4 mb-4">
        <h3 className="font-semibold text-github-text mb-2">Models</h3>
        <p className="text-sm text-github-muted mb-1">No artifacts published</p>
        <Button type="link" className="!text-github-link !p-0" disabled>
          Coming soon
        </Button>
      </div>

      <div className="border-t border-github-border pt-4">
        <h3 className="font-semibold text-github-text mb-3">Sample Status</h3>
        {totalSamples > 0 ? (
          <>
            <div className="flex h-2 rounded-full overflow-hidden mb-3">
              {segments.map((segment) => (
                <div
                  key={segment.label}
                  className="h-full"
                  style={{
                    width: `${(segment.value / totalSamples) * 100}%`,
                    backgroundColor: segment.color,
                  }}
                />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {segments.map((segment) => (
                <div key={segment.label} className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: segment.color }} />
                  <span className="font-semibold text-github-text">{segment.label}</span>
                  <span className="text-github-muted">{segment.value}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="text-sm text-github-muted">Not available yet</div>
        )}
      </div>
    </aside>
  )
}

export default ProjectSidebar
