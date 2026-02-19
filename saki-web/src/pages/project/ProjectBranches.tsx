import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Button, Form, Input, Modal, Popconfirm, Select, Spin, Switch, Table, Tag, message} from 'antd'
import type {ColumnsType} from 'antd/es/table'
import {useParams} from 'react-router-dom'
import {SearchOutlined} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'
import {FileTable} from '../../layouts/github/FileTable'
import {api} from '../../services/api'
import {CommitHistoryItem, ProjectBranch} from '../../types'
import {useResourcePermission} from '../../hooks/permission/usePermission'

type CreateBranchFormValues = {
    name: string
    description?: string
    baseBranch: string
    commitId?: string
}

type BranchPathMeta = {
    parts: string[]
    parentPath: string
    leafName: string
    depth: number
}

const parseBranchPath = (name: string): BranchPathMeta => {
    const parts = name.split('/').filter(Boolean)
    if (parts.length === 0) {
        return {
            parts: [name],
            parentPath: '',
            leafName: name,
            depth: 0,
        }
    }
    return {
        parts,
        parentPath: parts.slice(0, -1).join('/'),
        leafName: parts[parts.length - 1],
        depth: Math.max(0, parts.length - 1),
    }
}

const compareBranchByPath = (left: ProjectBranch, right: ProjectBranch): number => {
    const leftParts = parseBranchPath(left.name).parts
    const rightParts = parseBranchPath(right.name).parts
    const maxDepth = Math.max(leftParts.length, rightParts.length)
    for (let idx = 0; idx < maxDepth; idx += 1) {
        const leftPart = leftParts[idx]
        const rightPart = rightParts[idx]
        if (leftPart === undefined) return -1
        if (rightPart === undefined) return 1
        const diff = leftPart.localeCompare(rightPart, undefined, {numeric: true, sensitivity: 'base'})
        if (diff !== 0) return diff
    }
    return left.name.localeCompare(right.name, undefined, {numeric: true, sensitivity: 'base'})
}

const ProjectBranches: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
    const {t} = useTranslation()
    const {can} = useResourcePermission('project', projectId)
    const canManage = can('branch:manage:assigned')

    const [branches, setBranches] = useState<ProjectBranch[]>([])
    const [loading, setLoading] = useState(true)
    const [search, setSearch] = useState('')
    const [selectedBranchName, setSelectedBranchName] = useState('master')

    const [createOpen, setCreateOpen] = useState(false)
    const [creating, setCreating] = useState(false)
    const [advancedMode, setAdvancedMode] = useState(false)
    const [commits, setCommits] = useState<CommitHistoryItem[]>([])
    const [commitsLoading, setCommitsLoading] = useState(false)
    const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set())
    const [deletingId, setDeletingId] = useState<string | null>(null)

    const [form] = Form.useForm<CreateBranchFormValues>()

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

    const loadBranches = useCallback(async () => {
        if (!projectId) return
        setLoading(true)
        try {
            const data = await api.getProjectBranches(projectId)
            setBranches(data || [])
        } catch (error: any) {
            message.error(error.message || t('project.branches.loadError'))
        } finally {
            setLoading(false)
        }
    }, [projectId, t])

    const loadCommits = useCallback(async () => {
        if (!projectId) return
        setCommitsLoading(true)
        try {
            const data = await api.getProjectCommits(projectId)
            setCommits(data || [])
        } catch (error: any) {
            message.error(error.message || t('project.commits.loadError'))
        } finally {
            setCommitsLoading(false)
        }
    }, [projectId, t])

    useEffect(() => {
        loadBranches()
    }, [loadBranches])

    useEffect(() => {
        if (branches.length === 0) return
        const master = branches.find((branch) => branch.name === 'master')?.name
        setSelectedBranchName((prev) => {
            if (branches.find((branch) => branch.name === prev)) {
                return prev
            }
            return master || branches[0].name
        })
    }, [branches])

    useEffect(() => {
        if (advancedMode && commits.length === 0) {
            loadCommits()
        }
    }, [advancedMode, commits.length, loadCommits])

    const filteredBranches = useMemo(() => {
        if (!search.trim()) return branches
        const keyword = search.trim().toLowerCase()
        return branches.filter((branch) => branch.name.toLowerCase().includes(keyword))
    }, [branches, search])

    const orderedBranches = useMemo(() => {
        return [...filteredBranches].sort(compareBranchByPath)
    }, [filteredBranches])

    const orderedAllBranches = useMemo(() => {
        return [...branches].sort(compareBranchByPath)
    }, [branches])

    const activeBranch = useMemo(() => {
        return branches.find((branch) => branch.name === selectedBranchName) || branches[0]
    }, [branches, selectedBranchName])

    const handleOpenCreate = () => {
        const baseBranch = activeBranch?.name || 'master'
        form.resetFields()
        form.setFieldsValue({
            baseBranch,
        })
        setAdvancedMode(false)
        setCreateOpen(true)
    }

    const handleCreate = async () => {
        if (!projectId) return
        try {
            const values = await form.validateFields()
            const baseBranch = branches.find((branch) => branch.name === values.baseBranch) || activeBranch
            const baseCommitId = advancedMode
                ? values.commitId
                : baseBranch?.headCommitId

            if (!baseCommitId) {
                message.error(t('project.branches.baseCommitNotFound'))
                return
            }

            setCreating(true)
            await api.createProjectBranch(projectId, {
                name: values.name.trim(),
                description: values.description?.trim() || undefined,
                fromCommitId: baseCommitId,
            })
            message.success(t('project.branches.createSuccess'))
            setCreateOpen(false)
            await loadBranches()
            setSelectedBranchName(values.baseBranch)
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || t('project.branches.createError'))
        } finally {
            setCreating(false)
        }
    }

    const handleToggleProtected = async (branch: ProjectBranch, isProtected: boolean) => {
        if (!canManage) return
        setUpdatingIds((prev) => new Set(prev).add(branch.id))
        try {
            await api.updateBranch(projectId!, branch.id, {isProtected})
            message.success(isProtected ? t('project.branches.protected') : t('project.branches.unprotected'))
            await loadBranches()
        } catch (error: any) {
            message.error(error.message || t('project.branches.updateError'))
        } finally {
            setUpdatingIds((prev) => {
                const next = new Set(prev)
                next.delete(branch.id)
                return next
            })
        }
    }

    const handleDelete = async (branch: ProjectBranch) => {
        if (!canManage) return
        setDeletingId(branch.id)
        try {
            await api.deleteBranch(projectId!, branch.id)
            message.success(t('project.branches.deleteSuccess'))
            await loadBranches()
        } catch (error: any) {
            message.error(error.message || t('project.branches.deleteError'))
        } finally {
            setDeletingId(null)
        }
    }

    const columns: ColumnsType<ProjectBranch> = [
        {
            title: t('project.branches.columns.branch'),
            dataIndex: 'name',
            key: 'name',
            render: (_, record) => {
                const pathMeta = parseBranchPath(record.name)
                return (
                    <div className="flex flex-col min-w-0" style={{paddingLeft: `${Math.min(pathMeta.depth, 6) * 12}px`}}>
                        {pathMeta.parentPath ? (
                            <span className="text-[11px] text-github-muted font-mono truncate">
                                {pathMeta.parentPath}/
                            </span>
                        ) : null}
                        <span className="font-semibold text-github-text truncate">{pathMeta.leafName}</span>
                        {record.description ? (
                            <span className="text-xs text-github-muted truncate">{record.description}</span>
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: t('project.branches.columns.head'),
            dataIndex: 'headCommitId',
            key: 'headCommitId',
            render: (_, record) => (
                <div className="flex flex-col min-w-0">
                    <span className="text-github-text truncate">
                        {record.headCommitMessage || t('project.branches.noCommits')}
                    </span>
                    <span className="text-xs text-github-muted font-mono">
                        {record.headCommitId?.slice(0, 7) || '-'}
                    </span>
                </div>
            ),
        },
        {
            title: t('project.branches.columns.updated'),
            dataIndex: 'updatedAt',
            key: 'updatedAt',
            render: (_, record) => (
                <span className="text-github-muted">{formatRelativeTime(record.updatedAt)}</span>
            ),
        },
        {
            title: t('project.branches.columns.protected'),
            dataIndex: 'isProtected',
            key: 'isProtected',
            render: (_, record) => (
                <div className="flex items-center gap-2">
                    <Switch
                        size="small"
                        checked={record.isProtected}
                        disabled={!canManage || record.name === 'master'}
                        loading={updatingIds.has(record.id)}
                        onChange={(checked) => handleToggleProtected(record, checked)}
                    />
                    {record.isProtected ? (
                        <Tag className="!m-0">{t('project.branches.protectedLabel')}</Tag>
                    ) : null}
                </div>
            ),
        },
        {
            title: t('project.branches.columns.actions'),
            key: 'actions',
            width: 120,
            render: (_, record) => (
                <Popconfirm
                    title={t('project.branches.deleteTitle')}
                    description={
                        record.name === 'master'
                            ? t('project.branches.deleteMasterBlocked')
                            : record.isProtected
                                ? t('project.branches.deleteProtectedBlocked')
                                : t('project.branches.deleteWarning')
                    }
                    onConfirm={() => handleDelete(record)}
                    okText={t('common.delete')}
                    cancelText={t('common.cancel')}
                    disabled={!canManage || record.isProtected || record.name === 'master'}
                >
                    <Button
                        danger
                        size="small"
                        disabled={!canManage || record.isProtected || record.name === 'master'}
                        loading={deletingId === record.id}
                    >
                        {t('common.delete')}
                    </Button>
                </Popconfirm>
            ),
        },
    ]

    if (!projectId) {
        return <div className="text-github-muted">{t('project.common.notFound')}</div>
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-lg font-semibold text-github-text">{t('project.branches.title')}</h2>
                    <div className="text-sm text-github-muted">
                        {t('project.branches.count', {filtered: filteredBranches.length, total: branches.length})}
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Input
                        allowClear
                        prefix={<SearchOutlined className="text-github-muted"/>}
                        placeholder={t('project.branches.searchPlaceholder')}
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        className="w-[220px]"
                    />
                    <Button type="primary" onClick={handleOpenCreate} disabled={!canManage}>
                        {t('project.branches.newBranch')}
                    </Button>
                </div>
            </div>

            <FileTable
                header={
                    <div className="flex items-center justify-between w-full">
                        <div className="text-github-text">{t('project.branches.listTitle')}</div>
                        <div className="text-sm text-github-muted">
                            {t('project.branches.defaultBase', {branch: activeBranch?.name || 'master'})}
                        </div>
                    </div>
                }
            >
                <div className="px-4 py-4">
                    {loading ? (
                        <div className="flex items-center justify-center py-8">
                            <Spin/>
                        </div>
                    ) : (
                        <Table
                            rowKey="id"
                            columns={columns}
                            dataSource={orderedBranches}
                            pagination={false}
                            size="small"
                        />
                    )}
                </div>
            </FileTable>

            <Modal
                open={createOpen}
                title={t('project.branches.createTitle')}
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreate}
                okText={t('common.create')}
                confirmLoading={creating}
                destroyOnClose
            >
                <Form form={form} layout="vertical" preserve={false}>
                    <Form.Item
                        label={t('project.branches.form.name')}
                        name="name"
                        rules={[
                            {required: true, message: t('project.branches.form.nameRequired')},
                            {max: 64, message: t('project.branches.form.nameTooLong')},
                        ]}
                    >
                        <Input placeholder={t('project.branches.form.namePlaceholder')} autoComplete="off"/>
                    </Form.Item>
                    <Form.Item label={t('project.branches.form.description')} name="description">
                        <Input.TextArea rows={3} placeholder={t('project.branches.form.descriptionPlaceholder')}/>
                    </Form.Item>
                    <Form.Item label={t('project.branches.form.baseBranch')} name="baseBranch" rules={[{required: true}]}
                               initialValue={activeBranch?.name || 'master'}>
                        <Select
                            placeholder={t('project.branches.form.baseBranchPlaceholder')}
                            options={orderedAllBranches.map((branch) => ({
                                label: branch.name,
                                value: branch.name,
                            }))}
                            onChange={(value) => setSelectedBranchName(value)}
                        />
                    </Form.Item>
                    <Form.Item label={t('project.branches.form.advancedSelection')}>
                        <Switch checked={advancedMode} onChange={setAdvancedMode}/>
                    </Form.Item>
                    {advancedMode ? (
                        <Form.Item
                            label={t('project.branches.form.baseCommit')}
                            name="commitId"
                            rules={[{required: true, message: t('project.branches.form.baseCommitRequired')}]}
                        >
                            <Select
                                placeholder={t('project.branches.form.baseCommitPlaceholder')}
                                loading={commitsLoading}
                                showSearch
                                optionFilterProp="label"
                                options={commits.map((commit) => ({
                                    value: commit.id,
                                    label: `${commit.message || t('project.branches.form.noMessage')} · ${commit.commitHash.slice(0, 8)}`,
                                }))}
                            />
                        </Form.Item>
                    ) : null}
                </Form>
            </Modal>
        </div>
    )
}

export default ProjectBranches
