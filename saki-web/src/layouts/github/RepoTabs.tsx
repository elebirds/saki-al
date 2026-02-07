import React from 'react'
import {Button} from 'antd'
import type {NavItem} from './types'

export type RepoTabsProps = {
    items: NavItem[]
    activeKey: string
    onItemClick: (path: string) => void
}

export const RepoTabs: React.FC<RepoTabsProps> = ({items, activeKey, onItemClick}) => {
    return (
        <nav
            className="bg-[var(--github-header)] border-b border-github-border w-screen relative left-1/2 right-1/2 -mx-[50vw]">
            <div className="max-w-[1280px] mx-auto px-6 flex w-full items-center justify-center">
                <div className="flex items-center gap-2 text-sm overflow-x-auto">
                    {items.map((item) => {
                        const isActive = item.key === activeKey
                        return (
                            <Button
                                key={item.key}
                                type="text"
                                icon={item.icon}
                                onClick={() => onItemClick(item.path)}
                                className={`!flex !items-center !gap-2 !px-2 !py-3 !rounded-none !border-b-2 !whitespace-nowrap !transition-colors ${
                                    isActive
                                        ? '!border-github-accent !text-github-text'
                                        : '!border-transparent !text-github-muted hover:!text-github-text'
                                }`}
                            >
                                {item.label}
                            </Button>
                        )
                    })}
                </div>
            </div>
        </nav>
    )
}
