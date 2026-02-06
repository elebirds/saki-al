import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Avatar, Button, Spin, Tag} from 'antd'
import {FolderOutlined, HistoryOutlined} from '@ant-design/icons'
import {useNavigate, useParams} from 'react-router-dom'
import {RepoActionBar} from '../../layouts/github/RepoActionBar'
import {RepoHeader} from '../../layouts/github/RepoHeader'
import {FileTable} from '../../layouts/github/FileTable'
import {api} from '../../services/api'
import {CommitHistoryItem, Dataset, Project, ProjectBranch, ResourceMember} from '../../types'
import ProjectSidebar from './ProjectSidebar'


const taskTypeLabel: Record<string, string> = {
    classification: 'Classification',
    detection: 'Detection',
    segmentation: 'Segmentation',
}

const statusLabel: Record<string, string> = {
    active: 'Active',
    archived: 'Archived',
}

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

const ProjectOverview: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
    const navigate = useNavigate()
    const [project, setProject] = useState<Project | null>(null)
    const [datasets, setDatasets] = useState<Dataset[]>([])
    const [branches, setBranches] = useState<ProjectBranch[]>([])
    const [commits, setCommits] = useState<CommitHistoryItem[]>([])
    const [members, setMembers] = useState<ResourceMember[]>([])
    const [loading, setLoading] = useState(true)
    const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
    const [sampleStats, setSampleStats] = useState({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
    const [selectedBranchName, setSelectedBranchName] = useState('master')

    const loadProject = useCallback(async () => {
        if (!projectId) return
        setLoading(true)
        try {
            const [projectData, datasetIds, branchData, commitData] = await Promise.all([
                api.getProject(projectId),
                api.getProjectDatasets(projectId),
                api.getProjectBranches(projectId),
                api.getProjectCommits(projectId),
            ])

            setProject(projectData)
            setBranches(branchData)
            setCommits(commitData)

            const datasetResults = await Promise.all(datasetIds.map((id) => api.getDataset(id)))
            const resolvedDatasets = datasetResults.filter(Boolean) as Dataset[]
            setDatasets(resolvedDatasets)

            try {
                const memberList = await api.getProjectMembers(projectId)
                setMembers(memberList)
            } catch (error) {
                setMembers([])
            }

            if (resolvedDatasets.length === 1) {
                setSelectedDatasetId(resolvedDatasets[0].id)
            }
        } catch (error) {
            console.error('Failed to load project overview', error)
        } finally {
            setLoading(false)
        }
    }, [projectId])

    useEffect(() => {
        loadProject()
    }, [loadProject])

    useEffect(() => {
        if (selectedDatasetId && !datasets.find((dataset) => dataset.id === selectedDatasetId)) {
            setSelectedDatasetId(null)
        }
        if (!selectedDatasetId && datasets.length === 1) {
            setSelectedDatasetId(datasets[0].id)
        }
    }, [datasets, selectedDatasetId])

    useEffect(() => {
        if (datasets.length === 0) {
            setSampleStats({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
            return
        }

        const loadStats = async () => {
            const stats = await Promise.all(
                datasets.map((dataset) =>
                    api.getDatasetStats(dataset.id).catch(() => null)
                )
            )

            const totals = stats.reduce(
                (acc, stat) => {
                    if (!stat) return acc
                    acc.labeled += stat.labeledSamples || 0
                    acc.unlabeled += stat.unlabeledSamples || 0
                    acc.skipped += stat.skippedSamples || 0
                    acc.total += stat.totalSamples || 0
                    return acc
                },
                {labeled: 0, unlabeled: 0, skipped: 0, total: 0}
            )

            setSampleStats(totals)
        }

        loadStats()
    }, [datasets])

    useEffect(() => {
        if (branches.length === 0) return
        const master = branches.find((branch) => branch.name === 'master')?.name
        setSelectedBranchName((prev) => prev || master || branches[0].name)
    }, [branches])

    const memberMap = useMemo(() => {
        return new Map(members.map((member) => [member.userId, member]))
    }, [members])

    const activeBranchName = selectedBranchName || branches[0]?.name || 'master'
    const activeBranch = branches.find((branch) => branch.name === activeBranchName) || branches[0]
    const latestCommit = activeBranch?.headCommitId
        ? commits.find((commit) => commit.id === activeBranch.headCommitId)
        : commits[0]
    const latestCommitAuthor = latestCommit?.authorId ? memberMap.get(latestCommit.authorId) : null
    const latestCommitName = latestCommit
        ? latestCommit.authorType === 'system'
            ? 'System'
            : latestCommit.authorType === 'model'
                ? 'Model'
                : latestCommitAuthor?.userFullName || latestCommitAuthor?.userEmail || 'Unknown User'
        : 'No commits'

    const latestCommitAvatar = latestCommitAuthor?.userAvatarUrl

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        )
    }

    if (!project) {
        return (
            <div className="text-github-muted">Project not found.</div>
        )
    }

    return (
        <div>
            <RepoHeader
                title={project.name}
                visibilityLabel={taskTypeLabel[project.taskType] || project.taskType}
                stats={[{label: 'Fork', count: 0}]}
            />

            <div className="flex gap-6">
                <div className="flex-1 min-w-0">
                    <RepoActionBar
                        branchName={activeBranchName}
                        branchesCount={project.branchCount}
                        tagsCount={project.labelCount}
                        branches={branches.map((branch) => ({id: branch.id, name: branch.name}))}
                        onBranchChange={(name) => setSelectedBranchName(name)}
                        onBranchesClick={() => {
                            if (projectId) {
                                navigate(`/projects/${projectId}/branches`)
                            }
                        }}
                    />
                        <FileTable
                            header={
                                <>
                                    <div className="flex items-center gap-3 min-w-0">
                                        <Avatar
                                            size={24}
                                            src={latestCommitAvatar}
                                            className="bg-gradient-to-br from-green-400 to-blue-500"
                                        >
                                            {latestCommitName.charAt(0).toUpperCase()}
                                        </Avatar>
                                        <span
                                            className="font-semibold text-sm text-github-text">{latestCommitName}</span>
                                        <span className="text-github-muted text-sm truncate">
                      {latestCommit?.message || activeBranch?.headCommitMessage || 'No commits yet'}
                    </span>
                                    </div>
                                    <div className="flex items-center gap-3 text-sm text-github-muted shrink-0">
                                        {latestCommit?.id || activeBranch?.headCommitId ? (
                                            <span className="font-mono text-xs">
                                                {(latestCommit?.id || activeBranch?.headCommitId || '').slice(0, 7)}
                                            </span>
                                        ) : null}
                                        <span>· {formatRelativeTime(latestCommit?.createdAt || activeBranch?.updatedAt)}</span>
                                        <Button
                                            type="link"
                                            className="!text-github-link !p-0"
                                            onClick={() => {
                                                if (projectId) {
                                                    navigate(`/projects/${projectId}/commits?branch=${activeBranchName}`)
                                                }
                                            }}
                                        >
                                            <HistoryOutlined className="mr-1"/>
                                            <span
                                                className="font-semibold text-github-text">{project.commitCount}</span> Commits
                                        </Button>
                                    </div>
                                </>
                            }
                        >
                            {datasets.length === 0 ? (
                                <div className="px-4 py-8 text-center text-github-muted">
                                    No datasets linked to this project.
                                </div>
                            ) : (
                                datasets.map((dataset) => (
                                    <div
                                        key={dataset.id}
                                        className="flex items-center px-4 py-2 hover:bg-github-base border-b border-github-border-muted last:border-b-0 text-sm"
                                    >
                                        <div className="flex items-center gap-3 w-[220px] shrink-0">
                                            <FolderOutlined className="text-github-muted"/>
                                            <Button type="link" className="!text-github-link !p-0"
                                                    onClick={() => setSelectedDatasetId(dataset.id)}>
                                                {dataset.name}
                                            </Button>
                                        </div>
                                        <div className="flex-1 text-github-muted truncate px-4">
                                            {dataset.description || 'No description'}
                                        </div>
                                        <div
                                            className="flex items-center gap-2 text-github-muted text-right whitespace-nowrap shrink-0">
                                            <Tag className="!m-0">{dataset.type}</Tag>
                                            <span>{formatRelativeTime(dataset.updatedAt)}</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </FileTable>
                </div>

                <ProjectSidebar
                    description={project.description}
                    taskTypeLabel={taskTypeLabel[project.taskType] || project.taskType}
                    statusLabel={statusLabel[project.status] || project.status}
                    stats={{
                        datasets: project.datasetCount,
                        labels: project.labelCount,
                        branches: project.branchCount,
                        commits: project.commitCount,
                        members: members.length || undefined,
                    }}
                    members={members}
                    sampleStatus={sampleStats}
                />
            </div>
        </div>
    )
}

export default ProjectOverview
