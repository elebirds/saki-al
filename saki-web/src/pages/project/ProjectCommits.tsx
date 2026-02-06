import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Button, Dropdown, Spin, message} from 'antd'
import type {MenuProps} from 'antd'
import {
    BranchesOutlined,
    CalendarOutlined,
    CodeOutlined,
    DownOutlined,
    UserOutlined,
} from '@ant-design/icons'
import {useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {api} from '../../services/api'
import {CommitHistoryItem, ProjectBranch, ResourceMember} from '../../types'

const formatRelativeTime = (value?: string) => {
    if (!value) return '-'
    const date = new Date(value)
    const diffMs = Date.now() - date.getTime()
    const minutes = Math.floor(diffMs / 60000)
    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes} min ago`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours} hours ago`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days} days ago`
    const weeks = Math.floor(days / 7)
    if (weeks < 5) return `${weeks} weeks ago`
    const months = Math.floor(days / 30)
    return `${months} months ago`
}

const formatCommitGroupDate = (value?: string) => {
    if (!value) return 'Commits'
    const date = new Date(value)
    return `Commits on ${date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    })}`
}

const ProjectCommits: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const [branches, setBranches] = useState<ProjectBranch[]>([])
    const [members, setMembers] = useState<ResourceMember[]>([])
    const [loadingBranches, setLoadingBranches] = useState(true)
    const [loadingCommits, setLoadingCommits] = useState(true)
    const [commits, setCommits] = useState<CommitHistoryItem[]>([])
    const [activeBranchName, setActiveBranchName] = useState('master')

    const loadBranches = useCallback(async () => {
        if (!projectId) return
        setLoadingBranches(true)
        try {
            const data = await api.getProjectBranches(projectId)
            setBranches(data || [])
        } catch (error: any) {
            message.error(error.message || 'Failed to load branches')
        } finally {
            setLoadingBranches(false)
        }
    }, [projectId])

    const loadMembers = useCallback(async () => {
        if (!projectId) return
        try {
            const data = await api.getProjectMembers(projectId)
            setMembers(data || [])
        } catch (error) {
            setMembers([])
        }
    }, [projectId])

    useEffect(() => {
        loadBranches()
        loadMembers()
    }, [loadBranches, loadMembers])

    useEffect(() => {
        const paramBranch = searchParams.get('branch')
        if (!paramBranch) return
        setActiveBranchName(paramBranch)
    }, [searchParams])

    useEffect(() => {
        if (branches.length === 0) return
        const paramBranch = searchParams.get('branch')
        const hasParam = paramBranch && branches.some((branch) => branch.name === paramBranch)
        if (hasParam) {
            setActiveBranchName(paramBranch as string)
            return
        }
        const master = branches.find((branch) => branch.name === 'master')?.name
        const next = master || branches[0].name
        setActiveBranchName(next)
        const nextParams = new URLSearchParams(searchParams)
        nextParams.set('branch', next)
        setSearchParams(nextParams)
    }, [branches, searchParams, setSearchParams])

    const activeBranch = useMemo(() => {
        return branches.find((branch) => branch.name === activeBranchName)
    }, [branches, activeBranchName])

    const memberMap = useMemo(() => {
        return new Map(members.map((member) => [member.userId, member]))
    }, [members])

    const loadCommits = useCallback(async () => {
        if (!projectId || !activeBranch?.headCommitId) {
            setCommits([])
            return
        }
        setLoadingCommits(true)
        try {
            const data = await api.getCommitHistory(activeBranch.headCommitId)
            const ordered = (data || []).slice().reverse()
            setCommits(ordered)
        } catch (error: any) {
            message.error(error.message || 'Failed to load commits')
        } finally {
            setLoadingCommits(false)
        }
    }, [projectId, activeBranch?.headCommitId])

    useEffect(() => {
        if (!activeBranch?.headCommitId) {
            setCommits([])
            setLoadingCommits(false)
            return
        }
        loadCommits()
    }, [activeBranch?.headCommitId, loadCommits])

    const branchMenuItems: MenuProps['items'] = branches.map((branch) => ({
        key: branch.name,
        label: branch.name,
    }))

    const groupedCommits = useMemo(() => {
        const groups: Array<{ key: string; label: string; items: CommitHistoryItem[] }> = []
        const groupMap = new Map<string, { label: string; items: CommitHistoryItem[] }>()

        commits.forEach((commit) => {
            const dateKey = commit.createdAt ? new Date(commit.createdAt).toISOString().split('T')[0] : 'unknown'
            const label = formatCommitGroupDate(commit.createdAt)
            if (!groupMap.has(dateKey)) {
                groupMap.set(dateKey, {label, items: []})
                groups.push({key: dateKey, label, items: groupMap.get(dateKey)!.items})
            }
            groupMap.get(dateKey)!.items.push(commit)
        })

        return groups
    }, [commits])

    const getAuthorName = useCallback((commit: CommitHistoryItem) => {
        if (commit.authorType === 'system') return 'System'
        if (commit.authorType === 'model') return 'Model'
        const member = commit.authorId ? memberMap.get(commit.authorId) : null
        return member?.userFullName || member?.userEmail || 'Unknown User'
    }, [memberMap])

    if (!projectId) {
        return <div className="text-github-muted">Project not found.</div>
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="pt-1">
                <div className="flex items-center justify-between">
                    <h1 className="text-2xl font-normal text-github-text">Commits</h1>
                </div>
                <div className="mt-3 border-b border-github-border"/>
            </header>

            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Dropdown
                        menu={{
                            items: branchMenuItems,
                            onClick: (info) => {
                                const nextParams = new URLSearchParams(searchParams)
                                nextParams.set('branch', String(info.key))
                                setSearchParams(nextParams)
                                setActiveBranchName(String(info.key))
                            },
                        }}
                    >
                        <Button
                            className="!bg-github-input !border-github-border !text-github-text"
                            loading={loadingBranches}
                        >
                            <div className="flex items-center gap-2">
                                <BranchesOutlined/>
                                <span className="max-w-[160px] truncate">{activeBranch?.name || 'master'}</span>
                                <DownOutlined/>
                            </div>
                        </Button>
                    </Dropdown>
                    <Button className="!bg-github-input !border-github-border !text-github-muted" disabled>
                        <div className="flex items-center gap-2">
                            <UserOutlined/>
                            <span>All users</span>
                            <DownOutlined/>
                        </div>
                    </Button>
                    <Button className="!bg-github-input !border-github-border !text-github-muted" disabled>
                        <div className="flex items-center gap-2">
                            <CalendarOutlined/>
                            <span>All time</span>
                            <DownOutlined/>
                        </div>
                    </Button>
                </div>
                <div className="text-sm text-github-muted">
                    {commits.length} commits
                </div>
            </div>

            {loadingCommits ? (
                <div className="flex items-center justify-center py-12">
                    <Spin/>
                </div>
            ) : groupedCommits.length === 0 ? (
                <div className="rounded-md border border-github-border bg-github-panel px-4 py-10 text-center text-github-muted">
                    No commits found on this branch.
                </div>
            ) : (
                <div className="flex flex-col gap-6">
                    {groupedCommits.map((group, index) => (
                        <div key={group.key} className="relative flex gap-4">
                            <div className="relative flex flex-col items-center">
                                <div
                                    className="h-8 w-8 rounded-full border border-github-border bg-github-panel flex items-center justify-center text-github-muted">
                                    <CodeOutlined/>
                                </div>
                                <div
                                    className={`w-px flex-1 ${index === groupedCommits.length - 1 ? 'bg-transparent' : 'bg-github-border-muted'}`}
                                />
                            </div>
                            <div className="flex-1">
                                <h3 className="text-sm font-medium text-github-text">{group.label}</h3>
                                <div className="mt-2 rounded-md border border-github-border bg-github-panel">
                                    {group.items.map((commit, commitIndex) => (
                                        <div
                                            key={commit.id}
                                            className={`flex flex-wrap items-center justify-between gap-3 px-4 py-3 cursor-pointer hover:bg-github-base ${commitIndex === 0 ? '' : 'border-t border-github-border-muted'}`}
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => {
                                                navigate(`/projects/${projectId}/commits/${commit.id}?branch=${activeBranchName}`)
                                            }}
                                            onKeyDown={(event) => {
                                                if (event.key === 'Enter') {
                                                    navigate(`/projects/${projectId}/commits/${commit.id}?branch=${activeBranchName}`)
                                                }
                                            }}
                                        >
                                            <div className="min-w-0">
                                                <div className="font-semibold text-github-text truncate">
                                                    {commit.message || 'No commit message'}
                                                </div>
                                                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-github-muted">
                                                    <span>{getAuthorName(commit)}</span>
                                                    <span>·</span>
                                                    <span>{formatRelativeTime(commit.createdAt)}</span>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <Button
                                                    size="small"
                                                    className="!bg-github-input !border-github-border !text-github-text font-mono"
                                                    onClick={(event) => {
                                                        event.stopPropagation()
                                                        navigate(`/projects/${projectId}/commits/${commit.id}?branch=${activeBranchName}`)
                                                    }}
                                                >
                                                    {commit.id.slice(0, 7)}
                                                </Button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

export default ProjectCommits
