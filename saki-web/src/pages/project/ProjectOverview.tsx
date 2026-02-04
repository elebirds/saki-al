import React from 'react'
import { Avatar, Button } from 'antd'
import {
  FileOutlined,
  FolderOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { FileTable } from '../../layouts/github/FileTable'
import { RepoActionBar } from '../../layouts/github/RepoActionBar'
import { RepoHeader } from '../../layouts/github/RepoHeader'
import { Sidebar } from '../../layouts/github/Sidebar'

const files = [
  { type: 'folder', name: 'ref', message: "chore: simplify fedo's metadata & add example vis code a...", date: '2 months ago' },
  { type: 'folder', name: 'saki-api', message: 'feat: 引入 postgresql 和异步 IO', date: '2 weeks ago' },
  { type: 'folder', name: 'saki-runtime', message: '[feat] add the demo plugin and its training entry, update p...', date: '2 months ago' },
  { type: 'folder', name: 'saki-web', message: 'fix: fix compile error in TS', date: '3 weeks ago' },
  { type: 'file', name: '.gitignore', message: '[feat] add network error handling page and update routing', date: '2 months ago' },
  { type: 'file', name: 'API.md', message: 'refactor(annotation-system): union handler, add sync sys...', date: '2 months ago' },
  { type: 'file', name: 'DEPLOYMENT.md', message: 'feat(docker): add Docker mirror configuration script and ...', date: 'last month' },
  { type: 'file', name: 'MODEL_RUNTIME_DESIGN.md', message: '[init] add initial project prompt and constraints for Model ...', date: '2 months ago' },
  { type: 'file', name: 'PROMPT.txt', message: '[init] add initial project prompt and constraints for Model ...', date: '2 months ago' },
  { type: 'file', name: 'RBAC_DESIGN.md', message: 'feat(rbac): implement enhanced role-based access contr...', date: 'last month' },
  { type: 'file', name: 'README.md', message: '[init] project init', date: '2 months ago' },
  { type: 'file', name: 'deploy.sh', message: 'fix: docker bugs', date: 'last month' },
  { type: 'file', name: 'docker-compose.yml', message: 'feat: 引入 postgresql 和异步 IO', date: '2 weeks ago' },
  { type: 'file', name: 'env.example', message: 'feat: object storage', date: '2 weeks ago' },
  { type: 'file', name: '重构总结文档.md', message: 'refactor(model): layer 3', date: '2 weeks ago' },
  { type: 'file', name: '问题与建议清单.md', message: 'refactor(model): layer 3', date: '2 weeks ago' },
]

export default function ProjectOverview() {
  return (
    <div>
      <RepoHeader title="saki-al" visibilityLabel="Private" />

      <div className="flex gap-6">
        <div className="flex-1 min-w-0">
          <RepoActionBar branchName="main" branchesCount={3} tagsCount={0} />

          <FileTable
            header={
              <>
                <div className="flex items-center gap-3 min-w-0">
                  <Avatar size={24} className="bg-gradient-to-br from-green-400 to-blue-500" />
                  <span className="font-semibold text-sm text-github-text">elebirds</span>
                  <span className="text-github-muted text-sm truncate">
                    feat: 引入 postgresql 和异步 IO
                  </span>
                </div>
                <div className="flex items-center gap-3 text-sm text-github-muted shrink-0">
                  <span className="font-mono text-xs">9edd608</span>
                  <span>· 2 weeks ago</span>
                  <Button type="link" className="!text-github-link !p-0">
                    <HistoryOutlined className="mr-1" />
                    <span className="font-semibold text-github-text">100</span> Commits
                  </Button>
                </div>
              </>
            }
          >
            {files.map((file) => (
              <div
                key={`${file.type}-${file.name}`}
                className="flex items-center px-4 py-2 hover:bg-github-base border-b border-github-border-muted last:border-b-0 text-sm"
              >
                <div className="flex items-center gap-3 w-[200px] shrink-0">
                  {file.type === 'folder' ? (
                    <FolderOutlined className="text-github-muted" />
                  ) : (
                    <FileOutlined className="text-github-muted" />
                  )}
                  <Button type="link" className="!text-github-link !p-0">
                    {file.name}
                  </Button>
                </div>
                <div className="flex-1 text-github-muted truncate px-4">{file.message}</div>
                <div className="text-github-muted text-right whitespace-nowrap shrink-0">
                  {file.date}
                </div>
              </div>
            ))}
          </FileTable>
        </div>

        <Sidebar
          aboutText="Saki - Active Learning Framework"
          languages={[
            { name: 'Python', percent: 54.8, color: '#3572A5' },
            { name: 'TypeScript', percent: 44.5, color: '#3178c6' },
            { name: 'Shell', percent: 0.4, color: '#89e051' },
            { name: 'Dockerfile', percent: 0.2, color: '#384d54' },
            { name: 'CSS', percent: 0.1, color: '#563d7c' },
          ]}
        />
      </div>
    </div>
  )
}
