import React from 'react'
import type {MenuProps} from 'antd'
import {Button, Dropdown, Input} from 'antd'
import {BranchesOutlined, DownOutlined, SearchOutlined, TagOutlined} from '@ant-design/icons'

export type RepoActionBarProps = {
    branchName?: string
    branchesCount?: number
    tagsCount?: number
    branches?: { id?: string; name: string }[]
    onBranchChange?: (name: string) => void
}

export const RepoActionBar: React.FC<RepoActionBarProps> = ({
                                                                branchName = 'main',
                                                                branchesCount = 0,
                                                                tagsCount = 0,
                                                                branches,
                                                                onBranchChange,
                                                            }) => {
    const branchMenuItems: MenuProps['items'] = (branches && branches.length > 0)
        ? branches.map((branch) => ({
            key: branch.id || branch.name,
            label: branch.name,
        }))
        : [
            {key: 'main', label: 'main'},
            {key: 'dev', label: 'dev'},
        ]

    return (
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <div className="flex items-center gap-4">
                <Dropdown
                    menu={{
                        items: branchMenuItems,
                        onClick: (info) => {
                            const selected = branches?.find((branch) => (branch.id || branch.name) === info.key)
                            onBranchChange?.(selected?.name || String(info.key))
                        },
                    }}
                >
                    <Button className="!bg-github-input !border-github-border !text-github-text">
                        <div className="flex items-center gap-2">
                            <BranchesOutlined/>
                            <span>{branchName}</span>
                            <DownOutlined/>
                        </div>
                    </Button>
                </Dropdown>
                <Button type="text" className="!text-github-muted hover:!text-github-text">
                    <BranchesOutlined className="mr-2"/>
                    <span className="font-semibold text-github-text">{branchesCount}</span>
                    <span className="ml-1">Branches</span>
                </Button>
                <Button type="text" className="!text-github-muted hover:!text-github-text">
                    <TagOutlined className="mr-2"/>
                    <span className="font-semibold text-github-text">{tagsCount}</span>
                    <span className="ml-1">Tags</span>
                </Button>
            </div>

            <div className="flex items-center gap-2">
                <div className="flex items-center bg-github-input border border-github-border rounded-md px-2 py-1.5">
                    <Input
                        variant="borderless"
                        prefix={<SearchOutlined className="text-github-muted"/>}
                        placeholder="Go to file"
                        className="w-[180px] !bg-transparent !text-github-text placeholder:!text-github-muted"
                    />
                    <kbd
                        className="ml-2 px-1.5 py-0.5 text-xs bg-github-badge border border-github-border rounded text-github-muted">
                        t
                    </kbd>
                </div>
            </div>
        </div>
    )
}
