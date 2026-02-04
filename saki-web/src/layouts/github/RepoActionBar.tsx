import React from 'react'
import { Button, Dropdown, Input } from 'antd'
import type { MenuProps } from 'antd'
import { BranchesOutlined, CodeOutlined, DownOutlined, SearchOutlined, TagOutlined } from '@ant-design/icons'

export type RepoActionBarProps = {
  branchName?: string
  branchesCount?: number
  tagsCount?: number
}

const branchMenuItems: MenuProps['items'] = [
  { key: 'main', label: 'main' },
  { key: 'dev', label: 'dev' },
]

const fileMenuItems: MenuProps['items'] = [
  { key: 'upload', label: 'Upload files' },
  { key: 'new', label: 'New file' },
]

const codeMenuItems: MenuProps['items'] = [
  { key: 'https', label: 'HTTPS' },
  { key: 'ssh', label: 'SSH' },
]

export const RepoActionBar: React.FC<RepoActionBarProps> = ({
  branchName = 'main',
  branchesCount = 0,
  tagsCount = 0,
}) => {
  return (
    <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
      <div className="flex items-center gap-4">
        <Dropdown menu={{ items: branchMenuItems }}>
          <Button className="!bg-github-input !border-github-border !text-github-text">
            <div className="flex items-center gap-2">
              <BranchesOutlined />
              <span>{branchName}</span>
              <DownOutlined />
            </div>
          </Button>
        </Dropdown>
        <Button type="text" className="!text-github-muted hover:!text-github-text">
          <BranchesOutlined className="mr-2" />
          <span className="font-semibold text-github-text">{branchesCount}</span>
          <span className="ml-1">Branches</span>
        </Button>
        <Button type="text" className="!text-github-muted hover:!text-github-text">
          <TagOutlined className="mr-2" />
          <span className="font-semibold text-github-text">{tagsCount}</span>
          <span className="ml-1">Tags</span>
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center bg-github-input border border-github-border rounded-md px-2 py-1.5">
          <Input
            variant="borderless"
            prefix={<SearchOutlined className="text-github-muted" />}
            placeholder="Go to file"
            className="w-[180px] !bg-transparent !text-github-text placeholder:!text-github-muted"
          />
          <kbd className="ml-2 px-1.5 py-0.5 text-xs bg-github-badge border border-github-border rounded text-github-muted">
            t
          </kbd>
        </div>
        <Dropdown menu={{ items: fileMenuItems }}>
          <Button className="!bg-github-input !border-github-border !text-github-text">
            Add file <DownOutlined />
          </Button>
        </Dropdown>
        <Button className="!bg-github-input !border-github-border !text-github-text">
          <CodeOutlined />
        </Button>
        <Dropdown menu={{ items: codeMenuItems }}>
          <Button className="!bg-github-success !border-github-success !text-white hover:!bg-github-success-hover">
            <div className="flex items-center gap-2">
              Code <DownOutlined />
            </div>
          </Button>
        </Dropdown>
      </div>
    </div>
  )
}
