import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Avatar, Button, Form, Input, message, Modal, Space, Spin, Tag, Tooltip} from 'antd'
import {DownloadOutlined, FolderOutlined, HistoryOutlined, ImportOutlined} from '@ant-design/icons'
import {useNavigate, useParams} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import {RepoActionBar} from '../../layouts/github/RepoActionBar'
import {RepoHeader} from '../../layouts/github/RepoHeader'
import {FileTable} from '../../layouts/github/FileTable'
import {api} from '../../services/api'
import {CommitHistoryItem, Dataset, Loop, Project, ProjectBranch, ProjectModel, ResourceMember} from '../../types'
import {usePermission, useResourcePermission} from '../../hooks'
import ProjectSidebar from './ProjectSidebar'


const ProjectOverview: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
    const {t} = useTranslation()
    const navigate = useNavigate()
    const [project, setProject] = useState<Project | null>(null)
    const [datasets, setDatasets] = useState<Dataset[]>([])
    const [branches, setBranches] = useState<ProjectBranch[]>([])
    const [commits, setCommits] = useState<CommitHistoryItem[]>([])
    const [loops, setLoops] = useState<Loop[]>([])
    const [models, setModels] = useState<ProjectModel[]>([])
    const [members, setMembers] = useState<ResourceMember[]>([])
    const [loading, setLoading] = useState(true)
    const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
    const [sampleStats, setSampleStats] = useState({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
    const [selectedBranchName, setSelectedBranchName] = useState('master')
    const [forkOpen, setForkOpen] = useState(false)
    const [forking, setForking] = useState(false)
    const [forkForm] = Form.useForm()
    const {can, isSuperAdmin} = usePermission()
    const {can: canProject} = useResourcePermission('project', projectId)
    const canFork = can('project:create')
    const canImport = canProject('annotation:create:assigned') && canProject('commit:create:assigned')
    const canExport = canProject('project:export:assigned')
    const canViewModels = canProject('model:read:assigned')
    const canViewLoops = canProject('loop:manage:assigned') || can('loop:manage') || isSuperAdmin
    const canViewSamples = canProject('project:read:assigned')

    const formatRelativeTime = useCallback((value?: string) => {
        if (!value) return t('common.placeholder')
        const date = new Date(value)
        const diffMs = Date.now() - date.getTime()
        const minutes = Math.floor(diffMs / 60000)
        if (minutes < 1) return t('common.time.justNow')
        if (minutes < 60) return t('common.time.minutesAgo', {count: minutes})
        const hours = Math.floor(minutes / 60)
        if (hours < 24) return t('common.time.hoursAgo', {count: hours})
        const days = Math.floor(hours / 24)
        if (days < 7) return t('common.time.daysAgo', {count: days})
        const weeks = Math.floor(days / 7)
        if (weeks < 5) return t('common.time.weeksAgo', {count: weeks})
        const months = Math.floor(days / 30)
        return t('common.time.monthsAgo', {count: months})
    }, [t])

    const loadProject = useCallback(async () => {
        if (!projectId) return
        setLoading(true)
        try {
            const [projectData, projectDatasets, branchData, commitData, modelRows, loopRows] = await Promise.all([
                api.getProject(projectId),
                api.getProjectDatasetDetails(projectId),
                api.getProjectBranches(projectId),
                api.getProjectCommits(projectId),
                canViewModels
                    ? api.getProjectModels(projectId, {limit: 5}).catch(() => [] as ProjectModel[])
                    : Promise.resolve([] as ProjectModel[]),
                canViewLoops
                    ? api.getProjectLoops(projectId).catch(() => [] as Loop[])
                    : Promise.resolve([] as Loop[]),
            ])

            setProject(projectData)
            setBranches(branchData)
            setCommits(commitData)
            setModels(modelRows)
            setLoops(loopRows)

            setDatasets(projectDatasets || [])

            try {
                const memberList = await api.getProjectMembers(projectId)
                setMembers(memberList)
            } catch (error) {
                setMembers([])
            }

            if ((projectDatasets || []).length === 1) {
                setSelectedDatasetId(projectDatasets[0].id)
            }
        } catch (error) {
            console.error('Failed to load project overview', error)
            setModels([])
            setLoops([])
        } finally {
            setLoading(false)
        }
    }, [canViewLoops, canViewModels, projectId])

    useEffect(() => {
        loadProject()
    }, [loadProject])

    useEffect(() => {
        if (selectedDatasetId && !datasets.find((dataset) => dataset.id === selectedDatasetId)) {
            setSelectedDatasetId(null)
        }
        if (!selectedDatasetId && datasets.length > 0) {
            setSelectedDatasetId(datasets[0].id)
        }
    }, [datasets, selectedDatasetId])

    useEffect(() => {
        let cancelled = false
        const loadSampleStats = async () => {
            if (!projectId || !canViewSamples) {
                setSampleStats({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
                return
            }
            const targetDatasetId = selectedDatasetId || datasets[0]?.id
            if (!targetDatasetId) {
                setSampleStats({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
                return
            }
            const branchName = selectedBranchName || branches[0]?.name || 'master'
            try {
                const [allPage, labeledPage, unlabeledPage] = await Promise.all([
                    api.getProjectSamples(projectId, targetDatasetId, {
                        status: 'all',
                        branchName,
                        page: 1,
                        limit: 1,
                    }),
                    api.getProjectSamples(projectId, targetDatasetId, {
                        status: 'labeled',
                        branchName,
                        page: 1,
                        limit: 1,
                    }),
                    api.getProjectSamples(projectId, targetDatasetId, {
                        status: 'unlabeled',
                        branchName,
                        page: 1,
                        limit: 1,
                    }),
                ])
                if (cancelled) return
                const total = Number(allPage.total || 0)
                const labeled = Number(labeledPage.total || 0)
                const unlabeled = Number(unlabeledPage.total || 0)
                setSampleStats({
                    labeled,
                    unlabeled,
                    skipped: Math.max(total - labeled - unlabeled, 0),
                    total,
                })
            } catch {
                if (cancelled) return
                setSampleStats({labeled: 0, unlabeled: 0, skipped: 0, total: 0})
            }
        }
        void loadSampleStats()
        return () => {
            cancelled = true
        }
    }, [projectId, canViewSamples, selectedDatasetId, datasets, selectedBranchName, branches])

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
            ? t('project.commits.author.system')
            : latestCommit.authorType === 'model'
                ? t('project.commits.author.model')
                : latestCommitAuthor?.userFullName || latestCommitAuthor?.userEmail || t('project.commits.author.unknown')
        : t('project.overview.noCommits')

    const latestCommitAvatar = latestCommitAuthor?.userAvatarUrl
    const latestCommitShortHash = latestCommit?.commitHash?.slice(0, 8)

    const handleOpenFork = useCallback(() => {
        if (!project) return
        forkForm.setFieldsValue({
            name: `${project.name}-fork`,
            description: project.description || undefined,
        })
        setForkOpen(true)
    }, [project, forkForm])

    const handleForkProject = useCallback(async () => {
        if (!projectId) return
        try {
            const values = await forkForm.validateFields()
            setForking(true)
            const created = await api.forkProject(projectId, {
                name: values.name,
                description: values.description,
            })
            message.success(t('project.list.forkSuccess'))
            setForkOpen(false)
            forkForm.resetFields()
            navigate(`/projects/${created.id}`)
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error?.message || t('project.list.forkError'))
        } finally {
            setForking(false)
        }
    }, [projectId, forkForm, t, navigate])

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        )
    }

    if (!project) {
        return (
            <div className="text-github-muted">{t('project.common.notFound')}</div>
        )
    }

    const taskTypeLabel = t(`project.overview.taskType.${project.taskType}`, project.taskType)
    const statusLabel = t(`project.overview.status.${project.status}`, project.status)
    const blockImportByDatasetType = project.datasetType === 'fedo'
    const canOpenImport = canImport && !blockImportByDatasetType
    const importDisabledReason = !canImport
        ? t('common.noPermission')
        : (blockImportByDatasetType ? t('import.project.classicOnly') : undefined)
    const importButton = (
        <Button
            className="!bg-github-input !border-github-border !text-github-text"
            icon={<ImportOutlined/>}
            onClick={() => {
                if (!canOpenImport) return
                if (projectId) {
                    navigate(`/projects/${projectId}/import`)
                }
            }}
            disabled={!canOpenImport}
        >
            {t('import.project.entry')}
        </Button>
    )

    return (
        <div>
            <RepoHeader
                title={project.name}
                visibilityLabel={taskTypeLabel}
                actions={
                    <Space>
                        {canExport ? (
                            <Button
                                className="!bg-github-input !border-github-border !text-github-text"
                                icon={<DownloadOutlined/>}
                                onClick={() => {
                                    if (projectId) {
                                        navigate(`/projects/${projectId}/export`)
                                    }
                                }}
                            >
                                {t('export.project.entry')}
                            </Button>
                        ) : null}
                        {importDisabledReason ? (
                            <Tooltip title={importDisabledReason}>
                                <span>{importButton}</span>
                            </Tooltip>
                        ) : importButton}
                    </Space>
                }
                stats={[{
                    label: t('layout.repoHeader.stats.fork'),
                    count: project.forkCount || 0,
                    iconKey: 'fork',
                    hideDropdown: true,
                    onClick: canFork ? handleOpenFork : undefined,
                    disabled: !canFork,
                }]}
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
                        onTagsClick={() => {
                            if (projectId) {
                                navigate(`/projects/${projectId}/settings?section=labels`)
                            }
                        }}
                        onQuickSearch={(keyword) => {
                            if (!projectId) return
                            const params = new URLSearchParams()
                            if (selectedDatasetId) {
                                params.set('datasetId', selectedDatasetId)
                            }
                            params.set('branch', activeBranchName)
                            params.set('q', keyword)
                            navigate(`/projects/${projectId}/samples?${params.toString()}`)
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
                      {latestCommit?.message || activeBranch?.headCommitMessage || t('project.overview.noCommitsYet')}
                    </span>
                                    </div>
                                    <div className="flex items-center gap-3 text-sm text-github-muted shrink-0">
                                        {latestCommit?.commitHash ? (
                                            <span className="font-mono text-xs">
                                                {latestCommitShortHash}
                                            </span>
                                        ) : null}
                                        <span>· {formatRelativeTime(latestCommit?.createdAt || activeBranch?.updatedAt)}</span>
                                        <Button
                                            type="link"
                                            className="text-github-link! p-0!"
                                            onClick={() => {
                                                if (projectId) {
                                                    navigate(`/projects/${projectId}/commits?branch=${activeBranchName}`)
                                                }
                                            }}
                                        >
                                            <HistoryOutlined className="mr-1"/>
                                            <span
                                                className="font-semibold text-github-text">{project.commitCount}</span> {t('project.overview.commits')}
                                        </Button>
                                    </div>
                                </>
                            }
                        >
                            {datasets.length === 0 ? (
                                <div className="px-4 py-8 text-center text-github-muted">
                                    {t('project.overview.noDatasets')}
                                </div>
                            ) : (
                                datasets.map((dataset) => (
                                    <div
                                        key={dataset.id}
                                        className="flex items-center px-4 py-2 hover:bg-github-base border-b border-github-border-muted last:border-b-0 text-sm"
                                    >
                                        <div className="flex items-center gap-3 w-55 shrink-0">
                                            <FolderOutlined className="text-github-muted"/>
                                            <Button
                                                type="link"
                                                className="text-github-link! p-0!"
                                                onClick={() => {
                                                    setSelectedDatasetId(dataset.id)
                                                    if (projectId) {
                                                        const params = new URLSearchParams()
                                                        params.set('datasetId', dataset.id)
                                                        params.set('branch', activeBranchName)
                                                        navigate(`/projects/${projectId}/samples?${params.toString()}`)
                                                    }
                                                }}
                                            >
                                                {dataset.name}
                                            </Button>
                                        </div>
                                        <div className="flex-1 text-github-muted truncate px-4">
                                            {dataset.description || t('project.overview.noDescription')}
                                        </div>
                                        <div
                                            className="flex items-center gap-2 text-github-muted text-right whitespace-nowrap shrink-0">
                                            <Tag className="m-0!">{dataset.type}</Tag>
                                            <span>{formatRelativeTime(dataset.updatedAt)}</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </FileTable>
                </div>

                <ProjectSidebar
                    projectId={projectId}
                    description={project.description}
                    taskTypeLabel={taskTypeLabel}
                    statusLabel={statusLabel}
                    statusValue={project.status}
                    stats={{
                        datasets: project.datasetCount,
                        labels: project.labelCount,
                        branches: project.branchCount,
                        commits: project.commitCount,
                        members: members.length || undefined,
                    }}
                    members={members}
                    sampleStatus={sampleStats}
                    models={models}
                    canViewModels={canViewModels}
                    loops={loops}
                    canViewLoops={canViewLoops}
                />
            </div>

            <Modal
                title={t('project.list.forkTitle')}
                open={forkOpen}
                onCancel={() => {
                    setForkOpen(false)
                    forkForm.resetFields()
                }}
                onOk={handleForkProject}
                okText={t('project.list.forkProject')}
                okButtonProps={{loading: forking}}
                cancelButtonProps={{disabled: forking}}
            >
                <Form form={forkForm} layout="vertical">
                    <Form.Item label={t('project.list.forkSource')}>
                        <Input value={project?.name || ''} disabled/>
                    </Form.Item>
                    <Form.Item
                        name="name"
                        label={t('project.list.forkName')}
                        rules={[{required: true, message: t('project.list.forkNameRequired')}]}
                    >
                        <Input placeholder={t('project.list.forkNamePlaceholder')} autoComplete="off"/>
                    </Form.Item>
                    <Form.Item
                        name="description"
                        label={t('project.list.forkDescription')}
                    >
                        <Input.TextArea rows={3} placeholder={t('project.list.forkDescriptionPlaceholder')}/>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    )
}

export default ProjectOverview
