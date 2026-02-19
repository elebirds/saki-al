import React from 'react'
import type {MenuProps} from 'antd'
import {Avatar, Button, Dropdown, Tag} from 'antd'
import {DownOutlined, ForkOutlined} from '@ant-design/icons'
import type {RepoStat} from './types'
import {useTranslation} from 'react-i18next'

export type RepoHeaderProps = {
    title: string
    avatarUrl?: string | null
    visibilityLabel?: string
    stats?: RepoStat[]
    actions?: React.ReactNode
}

const iconMap: Record<string, React.ReactNode> = {
    fork: <ForkOutlined/>,
    Fork: <ForkOutlined/>,
    派生: <ForkOutlined/>,
}

export const RepoHeader: React.FC<RepoHeaderProps> = ({title, avatarUrl, visibilityLabel, stats, actions}) => {
    const {t} = useTranslation()
    const resolvedStats = stats || [{label: t('layout.repoHeader.stats.fork'), count: 0}]
    const resolvedVisibilityLabel = visibilityLabel || t('layout.repoHeader.private')
    const avatarFallback = (title || '?').trim().charAt(0).toUpperCase() || '?'

    return (
        <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
                <Avatar
                    size={32}
                    src={avatarUrl || undefined}
                    className={avatarUrl ? undefined : '!bg-gradient-to-br !from-green-400 !to-blue-500'}
                >
                    {avatarFallback}
                </Avatar>
                <h1 className="text-xl font-semibold text-github-text">{title}</h1>
                <Tag className="!bg-transparent !text-github-muted !border-github-border !rounded-full">
                    {resolvedVisibilityLabel}
                </Tag>
            </div>

            <div className="flex items-center gap-2">
                {actions}
                {resolvedStats.map((stat) => {
                    const menuItems: MenuProps['items'] = stat.menuItems || [
                        {
                            key: `${stat.label.toLowerCase()}-all`,
                            label: t('layout.repoHeader.viewAll', {label: stat.label.toLowerCase()}),
                        },
                    ]
                    const statIcon = stat.icon || iconMap[stat.iconKey || stat.label]

                    if (stat.hideDropdown) {
                        return (
                            <Button
                                key={`${stat.label}-single`}
                                className="!bg-github-input !border-github-border !text-github-text"
                                icon={statIcon}
                                onClick={stat.onClick}
                                disabled={stat.disabled}
                            >
                                <span className="mr-1">{stat.label}</span>
                                <span className="ml-1 px-1.5 py-0.5 rounded bg-github-badge text-xs text-github-text">
                  {stat.count}
                </span>
                            </Button>
                        )
                    }

                    return (
                        <div key={stat.label} className="flex items-center">
                            <Button
                                className="!bg-github-input !border-github-border !text-github-text !rounded-r-none"
                                icon={statIcon}
                            >
                                <span className="mr-1">{stat.label}</span>
                                <span className="ml-1 px-1.5 py-0.5 rounded bg-github-badge text-xs text-github-text">
                  {stat.count}
                </span>
                            </Button>
                            <Dropdown menu={{items: menuItems}} placement="bottomRight">
                                <Button
                                    className="!bg-github-input !border-github-border !text-github-text !rounded-l-none">
                                    <DownOutlined/>
                                </Button>
                            </Dropdown>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
