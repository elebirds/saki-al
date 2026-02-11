import React from 'react'
import {Avatar, Button, Tag, Tooltip} from 'antd'
import {DatabaseOutlined, ForkOutlined, NodeIndexOutlined} from '@ant-design/icons'
import {ResourceMember} from '../../types'
import {useTranslation} from 'react-i18next'

export interface ProjectSidebarProps {
    description?: string | null
    taskTypeLabel?: string
    statusLabel?: string
    statusValue?: string
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
    active: 'green',
    archived: 'default',
}

const ProjectSidebar: React.FC<ProjectSidebarProps> = ({
                                                           description,
                                                           taskTypeLabel,
                                                           statusLabel,
                                                           statusValue,
                                                           stats,
                                                           members,
                                                           sampleStatus,
                                                       }) => {
    const {t} = useTranslation()
    const totalSamples = sampleStatus?.total || 0
    const segments = totalSamples
        ? [
            {label: t('project.sidebar.sampleStatus.labeled'), value: sampleStatus?.labeled || 0, color: '#2da44e'},
            {
                label: t('project.sidebar.sampleStatus.unlabeled'),
                value: sampleStatus?.unlabeled || 0,
                color: '#d29922',
            },
            {label: t('project.sidebar.sampleStatus.skipped'), value: sampleStatus?.skipped || 0, color: '#8b949e'},
        ]
        : []

    return (
        <aside className="w-[296px] shrink-0 hidden lg:block">
            <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold text-github-text">{t('project.sidebar.about')}</h3>
                    <DatabaseOutlined className="text-github-muted"/>
                </div>
                <p className="text-sm mb-4 text-github-text">
                    {description || t('project.sidebar.noDescription')}
                </p>
                <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2 text-github-muted">
                        <NodeIndexOutlined/>
                        <span className="text-github-text">{taskTypeLabel || t('common.placeholder')}</span>
                    </div>
                    <div className="flex items-center gap-2 text-github-muted">
                        <ForkOutlined/>
                        <Tag color={statusColors[statusValue || ''] || 'default'}>{statusLabel}</Tag>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs text-github-muted">
                        <div>
                            <span className="text-github-text font-semibold">{stats.datasets}</span> {t('project.sidebar.stats.datasets')}
                        </div>
                        <div>
                            <span className="text-github-text font-semibold">{stats.labels}</span> {t('project.sidebar.stats.labels')}
                        </div>
                        <div>
                            <span className="text-github-text font-semibold">{stats.branches}</span> {t('project.sidebar.stats.branches')}
                        </div>
                        <div>
                            <span className="text-github-text font-semibold">{stats.commits}</span> {t('project.sidebar.stats.commits')}
                        </div>
                        {typeof stats.members === 'number' ? (
                            <div>
                                <span className="text-github-text font-semibold">{stats.members}</span> {t('project.sidebar.stats.members')}
                            </div>
                        ) : null}
                    </div>
                </div>

                {members && members.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                        {members.slice(0, 5).map((member) => (
                            <Tooltip
                                key={member.id}
                                title={
                                    member.userFullName && member.userEmail
                                        ? `${member.userFullName}(${member.userEmail})`
                                        : member.userFullName || member.userEmail || t('common.user')
                                }
                            >
                                <Avatar
                                    size={28}
                                    src={member.userAvatarUrl || undefined}
                                    className={member.userAvatarUrl ? undefined : '!bg-gradient-to-br !from-green-400 !to-blue-500'}
                                >
                                    {(member.userFullName || member.userEmail || 'U').charAt(0).toUpperCase()}
                                </Avatar>
                            </Tooltip>
                        ))}
                        {members.length > 5 ? (
                            <span className="text-xs text-github-muted">+{members.length - 5}</span>
                        ) : null}
                    </div>
                ) : null}
            </div>

            <div className="border-t border-github-border pt-4 mb-4">
                <h3 className="font-semibold text-github-text mb-2">{t('project.sidebar.loops.title')}</h3>
                <p className="text-sm text-github-muted mb-1">{t('project.sidebar.loops.empty')}</p>
                <Button type="link" className="!text-github-link !p-0" disabled>
                    {t('project.sidebar.loops.comingSoon')}
                </Button>
            </div>

            <div className="border-t border-github-border pt-4 mb-4">
                <h3 className="font-semibold text-github-text mb-2">{t('project.sidebar.models.title')}</h3>
                <p className="text-sm text-github-muted mb-1">{t('project.sidebar.models.empty')}</p>
                <Button type="link" className="!text-github-link !p-0" disabled>
                    {t('project.sidebar.models.comingSoon')}
                </Button>
            </div>

            <div className="border-t border-github-border pt-4">
                <h3 className="font-semibold text-github-text mb-3">{t('project.sidebar.sampleStatus.title')}</h3>
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
                                    <span className="w-2 h-2 rounded-full" style={{backgroundColor: segment.color}}/>
                                    <span className="font-semibold text-github-text">{segment.label}</span>
                                    <span className="text-github-muted">{segment.value}</span>
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <div className="text-sm text-github-muted">{t('project.sidebar.sampleStatus.empty')}</div>
                )}
            </div>
        </aside>
    )
}

export default ProjectSidebar
