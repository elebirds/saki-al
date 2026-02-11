import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {
    Avatar,
    Button,
    Card,
    ColorPicker,
    Form,
    Input,
    Menu,
    message,
    Modal,
    Popconfirm,
    Select,
    Spin,
    Table,
    Tag,
    Tooltip,
    Typography,
} from 'antd'
import type {ColumnsType} from 'antd/es/table'
import {
    DeleteOutlined,
    EditOutlined,
    LockOutlined,
    PlusOutlined,
    QuestionCircleOutlined,
    UserOutlined
} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'
import {useAuthStore} from '../../store/authStore'
import {useParams, useSearchParams} from 'react-router-dom'
import {api} from '../../services/api'
import {useResourcePermission} from '../../hooks'
import type {Dataset, Project, ProjectLabel, ProjectLabelCreate, ProjectLabelUpdate, ResourceMember, Role} from '../../types'

const {Title, Text} = Typography

const normalizeColor = (value: any) => {
    if (!value) return '#1890ff'
    if (typeof value === 'string') return value
    if (typeof value?.toHexString === 'function') return value.toHexString()
    return '#1890ff'
}

const ProjectSettings: React.FC = () => {
    const {t} = useTranslation()
    const {projectId} = useParams<{ projectId: string }>()
    const [searchParams, setSearchParams] = useSearchParams()
    const section = searchParams.get('section') || 'basic'

    const sectionItems = [
        {key: 'basic', label: t('project.settings.sections.basic')},
        {key: 'datasets', label: t('project.settings.sections.datasets')},
        {key: 'labels', label: t('project.settings.sections.labels')},
        {key: 'members', label: t('project.settings.sections.members')},
    ]

    const taskTypeOptions = [
        {value: 'classification', label: t('project.settings.taskType.classification')},
        {value: 'detection', label: t('project.settings.taskType.detection')},
        {value: 'segmentation', label: t('project.settings.taskType.segmentation')},
    ]

    const statusOptions = [
        {value: 'active', label: t('project.settings.status.active')},
        {value: 'archived', label: t('project.settings.status.archived')},
    ]

    const {can} = useResourcePermission('project', projectId)
    const canUpdateProject = can('project:update')
    const canManageLabels = can('label:manage')
    const canReadLabels = can('label:read') || canManageLabels
    const canManageMembers = can('project:assign')

    const [project, setProject] = useState<Project | null>(null)
    const [projectLoading, setProjectLoading] = useState(true)
    const [projectSaving, setProjectSaving] = useState(false)
    const [projectForm] = Form.useForm()

    const [labels, setLabels] = useState<ProjectLabel[]>([])
    const [labelsLoading, setLabelsLoading] = useState(false)
    const [labelModalOpen, setLabelModalOpen] = useState(false)
    const [labelSaving, setLabelSaving] = useState(false)
    const [editingLabel, setEditingLabel] = useState<ProjectLabel | null>(null)
    const [labelForm] = Form.useForm()

    const [members, setMembers] = useState<ResourceMember[]>([])
    const [membersLoading, setMembersLoading] = useState(false)
    const [roles, setRoles] = useState<Role[]>([])
    const [users, setUsers] = useState<Array<{ id: string; email: string; fullName?: string }>>([])
    const [memberModalOpen, setMemberModalOpen] = useState(false)
    const [memberSaving, setMemberSaving] = useState(false)
    const [memberForm] = Form.useForm()
    const [memberActionId, setMemberActionId] = useState<string | null>(null)
    const [memberEditModalOpen, setMemberEditModalOpen] = useState(false)
    const [editingMember, setEditingMember] = useState<ResourceMember | null>(null)
    const [memberEditForm] = Form.useForm()
    const currentUser = useAuthStore((state) => state.user)

    const [linkedDatasetIds, setLinkedDatasetIds] = useState<string[]>([])
    const [allDatasets, setAllDatasets] = useState<Dataset[]>([])
    const [datasetsLoading, setDatasetsLoading] = useState(false)
    const [datasetModalOpen, setDatasetModalOpen] = useState(false)
    const [datasetSaving, setDatasetSaving] = useState(false)
    const [datasetForm] = Form.useForm()

    useEffect(() => {
        const validKeys = new Set(sectionItems.map((item) => item.key))
        if (!validKeys.has(section)) {
            setSearchParams({section: 'basic'}, {replace: true})
        }
    }, [section, setSearchParams])

    const loadProject = useCallback(async () => {
        if (!projectId) return
        setProjectLoading(true)
        try {
            const data = await api.getProject(projectId)
            setProject(data)
            projectForm.setFieldsValue({
                name: data.name,
                description: data.description,
                status: data.status,
            })
        } catch (error: any) {
            message.error(error.message || t('project.settings.loadProjectError'))
        } finally {
            setProjectLoading(false)
        }
    }, [projectId, projectForm, t])

    const loadLabels = useCallback(async () => {
        if (!projectId) return
        setLabelsLoading(true)
        try {
            const data = await api.getProjectLabels(projectId)
            setLabels(data)
        } catch (error: any) {
            message.error(error.message || t('project.settings.loadLabelsError'))
        } finally {
            setLabelsLoading(false)
        }
    }, [projectId, t])

    const loadMembers = useCallback(async () => {
        if (!projectId) return
        setMembersLoading(true)
        try {
            const data = await api.getProjectMembers(projectId)
            setMembers(data)
        } catch (error: any) {
            message.error(error.message || t('project.settings.loadMembersError'))
        } finally {
            setMembersLoading(false)
        }
    }, [projectId, t])

    const loadRoles = useCallback(async () => {
        try {
            const response = await api.getRoles('resource', 1, 100)
            setRoles(response.items)
        } catch (error: any) {
            message.error(error.message || t('project.settings.loadRolesError'))
        }
    }, [t])

    const loadUsers = useCallback(async () => {
        try {
            const response = await api.getUserList(1, 200)
            setUsers(response.items)
        } catch (error: any) {
            message.error(error.message || t('project.settings.loadUsersError'))
        }
    }, [t])

    const loadProjectDatasetIds = useCallback(async () => {
        if (!projectId) return
        setDatasetsLoading(true)
        try {
            const ids = await api.getProjectDatasets(projectId)
            setLinkedDatasetIds(ids)
        } catch (error: any) {
            message.error(error.message || t('project.settings.datasets.loadLinkedError'))
        } finally {
            setDatasetsLoading(false)
        }
    }, [projectId, t])

    const loadAllDatasets = useCallback(async () => {
        try {
            const pageSize = 200
            let page = 1
            const all: Dataset[] = []
            while (true) {
                const response = await api.getDatasets(page, pageSize)
                const items = response.items || []
                all.push(...items)
                if (!response.hasMore || items.length === 0 || all.length >= response.total) {
                    break
                }
                page += 1
            }
            setAllDatasets(all)
        } catch (error: any) {
            message.error(error.message || t('project.settings.datasets.loadAllError'))
        }
    }, [t])

    useEffect(() => {
        loadProject()
    }, [loadProject])

    useEffect(() => {
        if (section === 'labels' && canReadLabels) {
            loadLabels()
        }
    }, [section, canReadLabels, loadLabels])

    useEffect(() => {
        if (section === 'members') {
            if (canManageMembers) {
                loadMembers()
                loadRoles()
                loadUsers()
            } else {
                setMembers([])
            }
        }
    }, [section, canManageMembers, loadMembers, loadRoles, loadUsers])

    useEffect(() => {
        if (section === 'datasets') {
            loadProjectDatasetIds()
            loadAllDatasets()
        }
    }, [section, loadProjectDatasetIds, loadAllDatasets])

    const handleSaveProject = async (values: any) => {
        if (!projectId) return
        setProjectSaving(true)
        try {
            const payload: Partial<Project> = {
                name: values.name,
                description: values.description,
                status: values.status,
            }
            const updated = await api.updateProject(projectId, payload)
            setProject(updated)
            message.success(t('project.settings.updateSuccess'))
        } catch (error: any) {
            message.error(error.message || t('project.settings.updateError'))
        } finally {
            setProjectSaving(false)
        }
    }

    const openCreateLabel = () => {
        setEditingLabel(null)
        labelForm.resetFields()
        labelForm.setFieldsValue({color: '#1890ff'})
        setLabelModalOpen(true)
    }

    const openEditLabel = (label: ProjectLabel) => {
        setEditingLabel(label)
        labelForm.setFieldsValue({
            name: label.name,
            description: label.description,
            color: label.color,
            shortcut: label.shortcut,
        })
        setLabelModalOpen(true)
    }

    const handleSaveLabel = async () => {
        if (!projectId) return
        try {
            const values = await labelForm.validateFields()
            setLabelSaving(true)
            const payload: ProjectLabelCreate | ProjectLabelUpdate = {
                name: values.name,
                description: values.description,
                color: normalizeColor(values.color),
                shortcut: values.shortcut,
            }
            if (editingLabel) {
                await api.updateProjectLabel(editingLabel.id, payload)
                message.success(t('project.settings.labelUpdated'))
            } else {
                await api.createProjectLabel(projectId, payload as ProjectLabelCreate)
                message.success(t('project.settings.labelCreated'))
            }
            setLabelModalOpen(false)
            setEditingLabel(null)
            loadLabels()
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || t('project.settings.labelSaveError'))
        } finally {
            setLabelSaving(false)
        }
    }

    const handleDeleteLabel = async (labelId: string) => {
        try {
            await api.deleteProjectLabel(labelId)
            message.success(t('project.settings.labelDeleted'))
            loadLabels()
        } catch (error: any) {
            message.error(error.message || t('project.settings.labelDeleteError'))
        }
    }

    const handleAddMember = async () => {
        if (!projectId) return
        try {
            const values = await memberForm.validateFields()
            setMemberSaving(true)
            await api.addProjectMember(projectId, values)
            message.success(t('project.settings.memberAdded'))
            setMemberModalOpen(false)
            memberForm.resetFields()
            loadMembers()
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || t('project.settings.memberAddError'))
        } finally {
            setMemberSaving(false)
        }
    }

    const openEditMemberRole = (member: ResourceMember) => {
        setEditingMember(member)
        memberEditForm.setFieldsValue({roleId: member.roleId})
        setMemberEditModalOpen(true)
    }

    const handleEditMemberRole = async () => {
        if (!projectId || !editingMember) return
        try {
            const values = await memberEditForm.validateFields()
            setMemberActionId(editingMember.id)
            await api.updateProjectMemberRole(projectId, editingMember.userId, {roleId: values.roleId})
            message.success(t('project.settings.memberRoleUpdated'))
            setMemberEditModalOpen(false)
            setEditingMember(null)
            loadMembers()
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || t('project.settings.memberRoleUpdateError'))
        } finally {
            setMemberActionId(null)
        }
    }

    const isOwnerMember = (member: ResourceMember) =>
        member.roleName === 'dataset_owner' || member.roleDisplayName === '数据集所有者'

    const isSelfMember = (member: ResourceMember) => member.userId === currentUser?.id

    const handleRemoveMember = async (member: ResourceMember) => {
        if (!projectId) return
        setMemberActionId(member.id)
        try {
            await api.removeProjectMember(projectId, member.userId)
            message.success(t('project.settings.memberRemoved'))
            loadMembers()
        } catch (error: any) {
            message.error(error.message || t('project.settings.memberRemoveError'))
        } finally {
            setMemberActionId(null)
        }
    }

    const handleLinkDatasets = async () => {
        if (!projectId) return
        try {
            const values = await datasetForm.validateFields()
            const datasetIds: string[] = values.datasetIds || []
            setDatasetSaving(true)
            await api.linkProjectDatasets(projectId, datasetIds)
            message.success(t('project.settings.datasets.linkSuccess'))
            setDatasetModalOpen(false)
            datasetForm.resetFields()
            loadProjectDatasetIds()
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(error.message || t('project.settings.datasets.linkError'))
        } finally {
            setDatasetSaving(false)
        }
    }

    const handleUnlinkDataset = async (datasetId: string) => {
        if (!projectId) return
        setDatasetSaving(true)
        try {
            await api.unlinkProjectDatasets(projectId, [datasetId])
            message.success(t('project.settings.datasets.unlinkSuccess'))
            loadProjectDatasetIds()
        } catch (error: any) {
            message.error(error.message || t('project.settings.datasets.unlinkError'))
        } finally {
            setDatasetSaving(false)
        }
    }

    const labelColumns: ColumnsType<ProjectLabel> = [
        {
            title: t('project.settings.labels.columns.label'),
            dataIndex: 'name',
            key: 'name',
            render: (_, record) => (
                <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{backgroundColor: record.color}}/>
                    <span className="text-github-text">{record.name}</span>
                </div>
            ),
        },
        {
            title: t('project.settings.labels.columns.description'),
            dataIndex: 'description',
            key: 'description',
            render: (value: string) => value || <span className="text-github-muted">{t('common.placeholder')}</span>,
        },
        {
            title: t('project.settings.labels.columns.shortcut'),
            dataIndex: 'shortcut',
            key: 'shortcut',
            render: (value: string) => value ? <Tag>{value}</Tag> : <span className="text-github-muted">{t('common.placeholder')}</span>,
        },
        {
            title: t('project.settings.labels.columns.actions'),
            key: 'actions',
            render: (_, record) => (
                <div className="flex items-center gap-2">
                    <Button size="small" onClick={() => openEditLabel(record)} disabled={!canManageLabels}>
                        {t('common.edit')}
                    </Button>
                    <Popconfirm
                        title={t('project.settings.labels.deleteTitle')}
                        okText={t('common.delete')}
                        cancelText={t('common.cancel')}
                        onConfirm={() => handleDeleteLabel(record.id)}
                        disabled={!canManageLabels}
                    >
                        <Button size="small" danger disabled={!canManageLabels}>
                            {t('common.delete')}
                        </Button>
                    </Popconfirm>
                </div>
            ),
        },
    ]

    const memberColumns: ColumnsType<ResourceMember> = [
        {
            title: t('project.settings.members.columns.member'),
            dataIndex: 'userFullName',
            key: 'member',
            render: (_, record) => {
                const displayName = record.userFullName || record.userEmail || t('common.user')
                return (
                    <div className="flex items-center gap-3">
                        <Avatar src={record.userAvatarUrl} icon={<UserOutlined/>}>
                            {displayName.charAt(0).toUpperCase()}
                        </Avatar>
                        <div>
                            <div className="flex items-center gap-2 text-github-text">
                                <span>{displayName}</span>
                                {isSelfMember(record) ? (
                                    <Tag color="blue" className="!m-0">
                                        {t('project.settings.members.currentUser')}
                                    </Tag>
                                ) : null}
                            </div>
                            <div className="text-xs text-github-muted">{record.userEmail}</div>
                        </div>
                    </div>
                )
            },
        },
        {
            title: t('project.settings.members.columns.role'),
            dataIndex: 'roleId',
            key: 'role',
            render: (_, record) => {
                const roleLabel = record.roleDisplayName || record.roleName || t('project.settings.members.defaultRole')
                return (
                    <div className="flex items-center gap-2">
                        <Tag color={record.roleColor || 'default'} className="!m-0">
                            {roleLabel}
                        </Tag>
                        {isOwnerMember(record) ? (
                            <Tooltip title={t('project.settings.members.ownerCannotRemove')}>
                                <LockOutlined className="text-github-muted"/>
                            </Tooltip>
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: t('project.settings.members.columns.actions'),
            key: 'actions',
            render: (_, record) => {
                const displayName = record.userFullName || record.userEmail || t('common.user')
                const disableRemove = !canManageMembers || isSelfMember(record) || isOwnerMember(record)
                const disableEdit = !canManageMembers || isOwnerMember(record)
                return (
                    <div className="flex items-center gap-2">
                        <Button
                            type="text"
                            icon={<EditOutlined/>}
                            onClick={() => openEditMemberRole(record)}
                            disabled={disableEdit}
                            loading={memberActionId === record.id}
                        />
                        <Popconfirm
                            title={
                                isSelfMember(record)
                                    ? t('project.settings.members.removeSelf', {name: displayName})
                                    : isOwnerMember(record)
                                        ? t('project.settings.members.removeOwner', {name: displayName})
                                        : t('project.settings.members.removeConfirm', {name: displayName})
                            }
                            okText={t('project.settings.members.remove')}
                            cancelText={t('common.cancel')}
                            onConfirm={() => handleRemoveMember(record)}
                            disabled={disableRemove}
                        >
                            <Button
                                type="text"
                                danger
                                icon={<DeleteOutlined/>}
                                disabled={disableRemove}
                                loading={memberActionId === record.id}
                            />
                        </Popconfirm>
                    </div>
                )
            },
        },
    ]

    const availableUsers = useMemo(() => {
        const existingIds = new Set(members.map((member) => member.userId))
        return users.filter((user) => !existingIds.has(user.id))
    }, [members, users])

    const linkedDatasets = useMemo(
        () => allDatasets.filter((dataset) => linkedDatasetIds.includes(dataset.id)),
        [allDatasets, linkedDatasetIds]
    )

    const addableDatasets = useMemo(
        () => allDatasets.filter((dataset) => !linkedDatasetIds.includes(dataset.id)),
        [allDatasets, linkedDatasetIds]
    )

    const renderBasicInfo = () => (
        <Card className="!border-github-border !bg-github-panel">
            <div className="mb-4 flex items-center justify-between">
                <div>
                    <Title level={4} className="!mb-0">
                        {project?.name
                            ? t('project.settings.basic.titleWithName', {name: project.name})
                            : t('project.settings.basic.title')}
                    </Title>
                    <Text type="secondary">{t('project.settings.basic.subtitle')}</Text>
                </div>
            </div>
            <Spin spinning={projectLoading}>
                <Form
                    form={projectForm}
                    layout="vertical"
                    onFinish={handleSaveProject}
                    disabled={!canUpdateProject}
                >
                    <div className="grid gap-4 md:grid-cols-2">
                        <Form.Item
                            name="name"
                            label={t('project.settings.basic.projectName')}
                            rules={[{required: true, message: t('project.settings.basic.projectNameRequired')}]}
                        >
                            <Input placeholder={t('project.settings.basic.projectNamePlaceholder')}/>
                        </Form.Item>
                        <Form.Item
                            label={
                                <div className="flex items-center gap-2">
                                    <span>{t('project.settings.basic.taskType')}</span>
                                    <Tooltip title={t('project.settings.basic.taskTypeHint')}>
                                        <Button type="text" size="small" icon={<QuestionCircleOutlined/>}/>
                                    </Tooltip>
                                </div>
                            }
                        >
                            <Input
                                value={taskTypeOptions.find((item) => item.value === project?.taskType)?.label || project?.taskType || '-'}
                                disabled
                            />
                        </Form.Item>
                    </div>
                    <Form.Item name="description" label={t('project.settings.basic.description')}>
                        <Input.TextArea rows={4} placeholder={t('project.settings.basic.descriptionPlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="status" label={t('project.settings.basic.status')}>
                        <Select options={statusOptions}/>
                    </Form.Item>
                    <div className="flex justify-end">
                        <Button type="primary" htmlType="submit" loading={projectSaving} disabled={!canUpdateProject}>
                            {t('common.saveChanges')}
                        </Button>
                    </div>
                </Form>
            </Spin>
        </Card>
    )

    const renderLabels = () => (
        <Card className="!border-github-border !bg-github-panel">
            <div className="mb-4 flex items-center justify-between">
                <div>
                    <Title level={4} className="!mb-0">{t('project.settings.labels.title')}</Title>
                    <Text type="secondary">{t('project.settings.labels.subtitle')}</Text>
                </div>
                <Button type="primary" icon={<PlusOutlined/>} onClick={openCreateLabel} disabled={!canManageLabels}>
                    {t('project.settings.labels.add')}
                </Button>
            </div>
            <Spin spinning={labelsLoading}>
                <Table
                    rowKey="id"
                    columns={labelColumns}
                    dataSource={labels}
                    pagination={false}
                    locale={{
                        emptyText: canReadLabels
                            ? t('project.settings.labels.empty')
                            : t('project.settings.labels.noPermission'),
                    }}
                />
            </Spin>

            <Modal
                title={editingLabel ? t('project.settings.labels.editTitle') : t('project.settings.labels.createTitle')}
                open={labelModalOpen}
                onCancel={() => setLabelModalOpen(false)}
                onOk={handleSaveLabel}
                confirmLoading={labelSaving}
                okButtonProps={{disabled: !canManageLabels}}
            >
                <Form form={labelForm} layout="vertical">
                    <Form.Item
                        name="name"
                        label={t('project.settings.labels.form.name')}
                        rules={[{required: true, message: t('project.settings.labels.form.nameRequired')}]}
                    >
                        <Input placeholder={t('project.settings.labels.form.namePlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="description" label={t('project.settings.labels.form.description')}>
                        <Input.TextArea rows={3} placeholder={t('project.settings.labels.form.descriptionPlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="shortcut" label={t('project.settings.labels.form.shortcut')}>
                        <Input placeholder={t('project.settings.labels.form.shortcutPlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="color" label={t('project.settings.labels.form.color')}>
                        <ColorPicker showText format="hex"/>
                    </Form.Item>
                </Form>
            </Modal>
        </Card>
    )

    const renderMembers = () => (
        <Card className="!border-github-border !bg-github-panel">
            <div className="mb-4 flex items-center justify-between">
                <div>
                    <Title level={4} className="!mb-0">{t('project.settings.members.title')}</Title>
                    <Text type="secondary">{t('project.settings.members.subtitle')}</Text>
                </div>
                <Button
                    type="primary"
                    icon={<PlusOutlined/>}
                    onClick={() => setMemberModalOpen(true)}
                    disabled={!canManageMembers}
                >
                    {t('project.settings.members.add')}
                </Button>
            </div>
            {!canManageMembers ? (
                <div className="rounded-md border border-dashed border-github-border p-4 text-sm text-github-muted">
                    {t('project.settings.members.noPermission')}
                </div>
            ) : (
                <Spin spinning={membersLoading}>
                    <Table
                        rowKey="id"
                        columns={memberColumns}
                        dataSource={members}
                        pagination={false}
                        locale={{emptyText: t('project.settings.members.empty')}}
                    />
                </Spin>
            )}

            <Modal
                title={t('project.settings.members.addTitle')}
                open={memberModalOpen}
                onCancel={() => setMemberModalOpen(false)}
                onOk={handleAddMember}
                confirmLoading={memberSaving}
                okButtonProps={{disabled: !canManageMembers}}
            >
                <Form form={memberForm} layout="vertical">
                    <Form.Item
                        name="userId"
                        label={t('project.settings.members.form.user')}
                        rules={[{required: true, message: t('project.settings.members.form.userRequired')}]}
                    >
                        <Select
                            showSearch
                            placeholder={t('project.settings.members.form.userPlaceholder')}
                            optionFilterProp="label"
                            options={availableUsers.map((user) => ({
                                value: user.id,
                                label: `${user.fullName || user.email} (${user.email})`,
                            }))}
                        />
                    </Form.Item>
                    <Form.Item
                        name="roleId"
                        label={t('project.settings.members.form.role')}
                        rules={[{required: true, message: t('project.settings.members.form.roleRequired')}]}
                    >
                        <Select
                            placeholder={t('project.settings.members.form.rolePlaceholder')}
                            options={roles.map((role) => ({
                                value: role.id,
                                label: role.displayName || role.name,
                            }))}
                        />
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={t('project.settings.members.editTitle')}
                open={memberEditModalOpen}
                onCancel={() => {
                    setMemberEditModalOpen(false)
                    setEditingMember(null)
                }}
                onOk={handleEditMemberRole}
                confirmLoading={memberActionId === editingMember?.id}
                okButtonProps={{disabled: !canManageMembers}}
            >
                <Form form={memberEditForm} layout="vertical">
                    <Form.Item
                        name="roleId"
                        label={t('project.settings.members.form.role')}
                        rules={[{required: true, message: t('project.settings.members.form.roleRequired')}]}
                    >
                        <Select
                            placeholder={t('project.settings.members.form.rolePlaceholder')}
                            options={roles.map((role) => ({
                                value: role.id,
                                label: role.displayName || role.name,
                            }))}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </Card>
    )

    const renderDatasets = () => (
        <Card className="!border-github-border !bg-github-panel">
            <div className="mb-4 flex items-center justify-between">
                <div>
                    <Title level={4} className="!mb-0">{t('project.settings.datasets.title')}</Title>
                    <Text type="secondary">{t('project.settings.datasets.subtitle')}</Text>
                </div>
                <Button
                    type="primary"
                    icon={<PlusOutlined/>}
                    onClick={() => setDatasetModalOpen(true)}
                    disabled={!canUpdateProject}
                >
                    {t('project.settings.datasets.add')}
                </Button>
            </div>

            {!canUpdateProject ? (
                <div className="rounded-md border border-dashed border-github-border p-4 text-sm text-github-muted">
                    {t('project.settings.datasets.noPermission')}
                </div>
            ) : (
                <Spin spinning={datasetsLoading}>
                    <Table
                        rowKey="id"
                        dataSource={linkedDatasets}
                        pagination={false}
                        locale={{emptyText: t('project.settings.datasets.empty')}}
                        columns={[
                            {
                                title: t('project.settings.datasets.columns.dataset'),
                                dataIndex: 'name',
                                key: 'name',
                                render: (value: string, record: Dataset) => (
                                    <div className="min-w-0">
                                        <div className="truncate text-github-text">{value}</div>
                                        {record.description ? (
                                            <div className="truncate text-xs text-github-muted">{record.description}</div>
                                        ) : null}
                                    </div>
                                ),
                            },
                            {
                                title: t('project.settings.datasets.columns.type'),
                                dataIndex: 'type',
                                key: 'type',
                                width: 140,
                                render: (value: string) => (
                                    <Tag className="!m-0">{value}</Tag>
                                ),
                            },
                            {
                                title: t('project.settings.datasets.columns.actions'),
                                key: 'actions',
                                width: 140,
                                render: (_, record: Dataset) => (
                                    <Popconfirm
                                        title={t('project.settings.datasets.unlinkTitle', {name: record.name})}
                                        description={t('project.settings.datasets.unlinkCascadeWarning')}
                                        okText={t('project.settings.datasets.unlink')}
                                        cancelText={t('common.cancel')}
                                        onConfirm={() => handleUnlinkDataset(record.id)}
                                    >
                                        <Button
                                            type="text"
                                            danger
                                            icon={<DeleteOutlined/>}
                                            loading={datasetSaving}
                                        />
                                    </Popconfirm>
                                ),
                            },
                        ]}
                    />
                </Spin>
            )}

            <Modal
                title={t('project.settings.datasets.addTitle')}
                open={datasetModalOpen}
                onCancel={() => setDatasetModalOpen(false)}
                onOk={handleLinkDatasets}
                confirmLoading={datasetSaving}
                okButtonProps={{disabled: !canUpdateProject}}
            >
                <Form form={datasetForm} layout="vertical">
                    <Form.Item
                        name="datasetIds"
                        label={t('project.settings.datasets.form.datasets')}
                        rules={[{required: true, message: t('project.settings.datasets.form.datasetsRequired')}]}
                    >
                        <Select
                            mode="multiple"
                            showSearch
                            optionFilterProp="label"
                            placeholder={t('project.settings.datasets.form.datasetsPlaceholder')}
                            options={addableDatasets.map((dataset) => ({
                                value: dataset.id,
                                label: `${dataset.name} (${dataset.type})`,
                            }))}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </Card>
    )

    return (
        <div className="flex h-full flex-col gap-6">
            <div className="flex flex-1 gap-6 overflow-hidden">
                <div className="w-[220px] shrink-0">
                    <Card className="!border-github-border !bg-github-panel">
                        <Menu
                            mode="inline"
                            selectedKeys={[section]}
                            items={sectionItems}
                            onClick={(info) => setSearchParams({section: String(info.key)})}
                        />
                    </Card>
                </div>
                <div className="flex-1 min-w-0 overflow-y-auto pr-2">
                    {section === 'basic' && renderBasicInfo()}
                    {section === 'datasets' && renderDatasets()}
                    {section === 'labels' && renderLabels()}
                    {section === 'members' && renderMembers()}
                </div>
            </div>
        </div>
    )
}

export default ProjectSettings
