import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Button, Form, Input, Modal, Popconfirm, Select, Spin, Switch, Table, Tag, message} from 'antd'
import type {ColumnsType} from 'antd/es/table'
import {useParams} from 'react-router-dom'
import {SearchOutlined} from '@ant-design/icons'
import {FileTable} from '../../layouts/github/FileTable'
import {api} from '../../services/api'
import {CommitHistoryItem, ProjectBranch} from '../../types'
import {useResourcePermission} from '../../hooks/permission/usePermission'

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

type CreateBranchFormValues = {
    name: string
    description?: string
    baseBranch: string
    commitId?: string
}

const ProjectBranches: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
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

    const loadBranches = useCallback(async () => {
        if (!projectId) return
        setLoading(true)
        try {
            const data = await api.getProjectBranches(projectId)
            setBranches(data || [])
        } catch (error: any) {
            message.error(error.message || 'Failed to load branches')
        } finally {
            setLoading(false)
        }
    }, [projectId])

    const loadCommits = useCallback(async () => {
        if (!projectId) return
        setCommitsLoading(true)
        try {
            const data = await api.getProjectCommits(projectId)
            setCommits(data || [])
        } catch (error: any) {
            message.error(error.message || 'Failed to load commits')
        } finally {
            setCommitsLoading(false)
        }
    }, [projectId])

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
                message.error('Base commit not found')
                return
            }

            setCreating(true)
            await api.createProjectBranch(projectId, {
                name: values.name.trim(),
                description: values.description?.trim() || undefined,
                fromCommitId: baseCommitId,
            })
            message.success('Branch created')
            setCreateOpen(false)
            await loadBranches()
            setSelectedBranchName(values.baseBranch)
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || 'Failed to create branch')
        } finally {
            setCreating(false)
        }
    }

    const handleToggleProtected = async (branch: ProjectBranch, isProtected: boolean) => {
        if (!canManage) return
        setUpdatingIds((prev) => new Set(prev).add(branch.id))
        try {
            await api.updateBranch(branch.id, {isProtected})
            message.success(isProtected ? 'Branch protected' : 'Branch unprotected')
            await loadBranches()
        } catch (error: any) {
            message.error(error.message || 'Failed to update branch')
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
            await api.deleteBranch(branch.id)
            message.success('Branch deleted')
            await loadBranches()
        } catch (error: any) {
            message.error(error.message || 'Failed to delete branch')
        } finally {
            setDeletingId(null)
        }
    }

    const columns: ColumnsType<ProjectBranch> = [
        {
            title: 'Branch',
            dataIndex: 'name',
            key: 'name',
            render: (_, record) => (
                <div className="flex flex-col min-w-0">
                    <span className="font-semibold text-github-text truncate">{record.name}</span>
                    {record.description ? (
                        <span className="text-xs text-github-muted truncate">{record.description}</span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Head',
            dataIndex: 'headCommitId',
            key: 'headCommitId',
            render: (_, record) => (
                <div className="flex flex-col min-w-0">
                    <span className="text-github-text truncate">
                        {record.headCommitMessage || 'No commits'}
                    </span>
                    <span className="text-xs text-github-muted font-mono">
                        {record.headCommitId?.slice(0, 7) || '-'}
                    </span>
                </div>
            ),
        },
        {
            title: 'Updated',
            dataIndex: 'updatedAt',
            key: 'updatedAt',
            render: (_, record) => (
                <span className="text-github-muted">{formatRelativeTime(record.updatedAt)}</span>
            ),
        },
        {
            title: 'Protected',
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
                        <Tag className="!m-0">Protected</Tag>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Actions',
            key: 'actions',
            width: 120,
            render: (_, record) => (
                <Popconfirm
                    title="Delete this branch?"
                    description={record.name === 'master' ? 'Master branch cannot be deleted.' : record.isProtected ? 'Protected branches cannot be deleted.' : 'This action cannot be undone.'}
                    onConfirm={() => handleDelete(record)}
                    okText="Delete"
                    cancelText="Cancel"
                    disabled={!canManage || record.isProtected || record.name === 'master'}
                >
                    <Button
                        danger
                        size="small"
                        disabled={!canManage || record.isProtected || record.name === 'master'}
                        loading={deletingId === record.id}
                    >
                        Delete
                    </Button>
                </Popconfirm>
            ),
        },
    ]

    if (!projectId) {
        return <div className="text-github-muted">Project not found.</div>
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-lg font-semibold text-github-text">Branches</h2>
                    <div className="text-sm text-github-muted">
                        {filteredBranches.length} / {branches.length} branches
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Input
                        allowClear
                        prefix={<SearchOutlined className="text-github-muted"/>}
                        placeholder="Search branches"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        className="w-[220px]"
                    />
                    <Button type="primary" onClick={handleOpenCreate} disabled={!canManage}>
                        New Branch
                    </Button>
                </div>
            </div>

            <FileTable
                header={
                    <div className="flex items-center justify-between w-full">
                        <div className="text-github-text">Branch list</div>
                        <div className="text-sm text-github-muted">
                            Default base: {activeBranch?.name || 'master'}
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
                            dataSource={filteredBranches}
                            pagination={false}
                            size="small"
                        />
                    )}
                </div>
            </FileTable>

            <Modal
                open={createOpen}
                title="Create new branch"
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreate}
                okText="Create"
                confirmLoading={creating}
                destroyOnClose
            >
                <Form form={form} layout="vertical" preserve={false}>
                    <Form.Item
                        label="Branch name"
                        name="name"
                        rules={[
                            {required: true, message: 'Please enter a branch name'},
                            {max: 64, message: 'Branch name is too long'},
                        ]}
                    >
                        <Input placeholder="feature/my-branch" autoComplete="off"/>
                    </Form.Item>
                    <Form.Item label="Description" name="description">
                        <Input.TextArea rows={3} placeholder="Optional description"/>
                    </Form.Item>
                    <Form.Item label="Base branch" name="baseBranch" rules={[{required: true}]}
                               initialValue={activeBranch?.name || 'master'}>
                        <Select
                            placeholder="Select base branch"
                            options={branches.map((branch) => ({
                                label: branch.name,
                                value: branch.name,
                            }))}
                            onChange={(value) => setSelectedBranchName(value)}
                        />
                    </Form.Item>
                    <Form.Item label="Advanced commit selection">
                        <Switch checked={advancedMode} onChange={setAdvancedMode}/>
                    </Form.Item>
                    {advancedMode ? (
                        <Form.Item label="Base commit" name="commitId" rules={[{required: true, message: 'Select a commit'}]}>
                            <Select
                                placeholder="Select a commit"
                                loading={commitsLoading}
                                showSearch
                                optionFilterProp="label"
                                options={commits.map((commit) => ({
                                    value: commit.id,
                                    label: `${commit.message || 'No message'} · ${commit.id.slice(0, 7)}`,
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
