import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Avatar,
  Button,
  Card,
  ColorPicker,
  Form,
  Input,
  Menu,
  Modal,
  Popconfirm,
  Select,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined, EditOutlined, LockOutlined, PlusOutlined, QuestionCircleOutlined, UserOutlined } from '@ant-design/icons'
import { useAuthStore } from '../../store/authStore'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../services/api'
import { useResourcePermission } from '../../hooks'
import type { Project, ProjectLabel, ProjectLabelCreate, ProjectLabelUpdate, ResourceMember, Role } from '../../types'

const { Title, Text } = Typography

const sectionItems = [
  { key: 'basic', label: 'Basic Info' },
  { key: 'labels', label: 'Labels' },
  { key: 'members', label: 'Members' },
]

const taskTypeOptions = [
  { value: 'classification', label: 'Classification' },
  { value: 'detection', label: 'Detection' },
  { value: 'segmentation', label: 'Segmentation' },
]

const statusOptions = [
  { value: 'active', label: 'Active' },
  { value: 'archived', label: 'Archived' },
]

const normalizeColor = (value: any) => {
  if (!value) return '#1890ff'
  if (typeof value === 'string') return value
  if (typeof value?.toHexString === 'function') return value.toHexString()
  return '#1890ff'
}

const ProjectSettings: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const section = searchParams.get('section') || 'basic'

  const { can } = useResourcePermission('project', projectId)
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

  useEffect(() => {
    const validKeys = new Set(sectionItems.map((item) => item.key))
    if (!validKeys.has(section)) {
      setSearchParams({ section: 'basic' }, { replace: true })
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
      message.error(error.message || 'Failed to load project')
    } finally {
      setProjectLoading(false)
    }
  }, [projectId, projectForm])

  const loadLabels = useCallback(async () => {
    if (!projectId) return
    setLabelsLoading(true)
    try {
      const data = await api.getProjectLabels(projectId)
      setLabels(data)
    } catch (error: any) {
      message.error(error.message || 'Failed to load labels')
    } finally {
      setLabelsLoading(false)
    }
  }, [projectId])

  const loadMembers = useCallback(async () => {
    if (!projectId) return
    setMembersLoading(true)
    try {
      const data = await api.getProjectMembers(projectId)
      setMembers(data)
    } catch (error: any) {
      message.error(error.message || 'Failed to load members')
    } finally {
      setMembersLoading(false)
    }
  }, [projectId])

  const loadRoles = useCallback(async () => {
    try {
      const response = await api.getRoles('resource', 1, 100)
      setRoles(response.items)
    } catch (error: any) {
      message.error(error.message || 'Failed to load roles')
    }
  }, [])

  const loadUsers = useCallback(async () => {
    try {
      const response = await api.getUserList(1, 200)
      setUsers(response.items)
    } catch (error: any) {
      message.error(error.message || 'Failed to load users')
    }
  }, [])

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
      message.success('Project updated')
    } catch (error: any) {
      message.error(error.message || 'Failed to update project')
    } finally {
      setProjectSaving(false)
    }
  }

  const openCreateLabel = () => {
    setEditingLabel(null)
    labelForm.resetFields()
    labelForm.setFieldsValue({ color: '#1890ff' })
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
        message.success('Label updated')
      } else {
        await api.createProjectLabel(projectId, payload as ProjectLabelCreate)
        message.success('Label created')
      }
      setLabelModalOpen(false)
      setEditingLabel(null)
      loadLabels()
    } catch (error: any) {
      if (error?.errorFields) return
      message.error(error.message || 'Failed to save label')
    } finally {
      setLabelSaving(false)
    }
  }

  const handleDeleteLabel = async (labelId: string) => {
    try {
      await api.deleteProjectLabel(labelId)
      message.success('Label deleted')
      loadLabels()
    } catch (error: any) {
      message.error(error.message || 'Failed to delete label')
    }
  }

  const handleAddMember = async () => {
    if (!projectId) return
    try {
      const values = await memberForm.validateFields()
      setMemberSaving(true)
      await api.addProjectMember(projectId, values)
      message.success('Member added')
      setMemberModalOpen(false)
      memberForm.resetFields()
      loadMembers()
    } catch (error: any) {
      if (error?.errorFields) return
      message.error(error.message || 'Failed to add member')
    } finally {
      setMemberSaving(false)
    }
  }

  const openEditMemberRole = (member: ResourceMember) => {
    setEditingMember(member)
    memberEditForm.setFieldsValue({ roleId: member.roleId })
    setMemberEditModalOpen(true)
  }

  const handleEditMemberRole = async () => {
    if (!projectId || !editingMember) return
    try {
      const values = await memberEditForm.validateFields()
      setMemberActionId(editingMember.id)
      await api.updateProjectMemberRole(projectId, editingMember.userId, { roleId: values.roleId })
      message.success('Role updated')
      setMemberEditModalOpen(false)
      setEditingMember(null)
      loadMembers()
    } catch (error: any) {
      if (error?.errorFields) return
      message.error(error.message || 'Failed to update role')
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
      message.success('Member removed')
      loadMembers()
    } catch (error: any) {
      message.error(error.message || 'Failed to remove member')
    } finally {
      setMemberActionId(null)
    }
  }

  const labelColumns: ColumnsType<ProjectLabel> = [
    {
      title: 'Label',
      dataIndex: 'name',
      key: 'name',
      render: (_, record) => (
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: record.color }} />
          <span className="text-github-text">{record.name}</span>
        </div>
      ),
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      render: (value: string) => value || <span className="text-github-muted">-</span>,
    },
    {
      title: 'Shortcut',
      dataIndex: 'shortcut',
      key: 'shortcut',
      render: (value: string) => value ? <Tag>{value}</Tag> : <span className="text-github-muted">-</span>,
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <div className="flex items-center gap-2">
          <Button size="small" onClick={() => openEditLabel(record)} disabled={!canManageLabels}>
            Edit
          </Button>
          <Popconfirm
            title="Delete this label?"
            okText="Delete"
            cancelText="Cancel"
            onConfirm={() => handleDeleteLabel(record.id)}
            disabled={!canManageLabels}
          >
            <Button size="small" danger disabled={!canManageLabels}>
              Delete
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ]

  const memberColumns: ColumnsType<ResourceMember> = [
    {
      title: 'Member',
      dataIndex: 'userFullName',
      key: 'member',
      render: (_, record) => {
        const displayName = record.userFullName || record.userEmail || 'User'
        return (
          <div className="flex items-center gap-3">
            <Avatar src={record.userAvatarUrl} icon={<UserOutlined />}>
              {displayName.charAt(0).toUpperCase()}
            </Avatar>
            <div>
              <div className="flex items-center gap-2 text-github-text">
                <span>{displayName}</span>
                {isSelfMember(record) ? (
                  <Tag color="blue" className="!m-0">
                    当前用户
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
      title: 'Role',
      dataIndex: 'roleId',
      key: 'role',
      render: (_, record) => {
        const roleLabel = record.roleDisplayName || record.roleName || 'Member'
        return (
          <div className="flex items-center gap-2">
            <Tag color={record.roleColor || 'default'} className="!m-0">
              {roleLabel}
            </Tag>
            {isOwnerMember(record) ? (
              <Tooltip title="Project owner cannot be removed.">
                <LockOutlined className="text-github-muted" />
              </Tooltip>
            ) : null}
          </div>
        )
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => {
        const displayName = record.userFullName || record.userEmail || 'User'
        const disableRemove = !canManageMembers || isSelfMember(record) || isOwnerMember(record)
        const disableEdit = !canManageMembers || isOwnerMember(record)
        return (
          <div className="flex items-center gap-2">
            <Button
              type="text"
              icon={<EditOutlined />}
              onClick={() => openEditMemberRole(record)}
              disabled={disableEdit}
              loading={memberActionId === record.id}
            />
            <Popconfirm
              title={
                isSelfMember(record)
                  ? `You cannot remove yourself (${displayName}).`
                  : isOwnerMember(record)
                    ? `You cannot remove the project owner (${displayName}).`
                    : `Remove ${displayName}?`
              }
              okText="Remove"
              cancelText="Cancel"
              onConfirm={() => handleRemoveMember(record)}
              disabled={disableRemove}
            >
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
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

  const renderBasicInfo = () => (
    <Card className="!border-github-border !bg-github-panel">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Title level={4} className="!mb-0">
            {project?.name ? `Project Info · ${project.name}` : 'Project Info'}
          </Title>
          <Text type="secondary">Manage the basic information of this project.</Text>
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
            <Form.Item name="name" label="Project Name" rules={[{ required: true, message: 'Name is required' }]}>
              <Input placeholder="Project name" />
            </Form.Item>
            <Form.Item
              label={
                <div className="flex items-center gap-2">
                  <span>Task Type</span>
                  <Tooltip title="任务类型决定标注方式与模型训练流程，创建后不可更改。">
                    <Button type="text" size="small" icon={<QuestionCircleOutlined />} />
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
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={4} placeholder="Describe the project" />
          </Form.Item>
          <Form.Item name="status" label="Status">
            <Select options={statusOptions} />
          </Form.Item>
          <div className="flex justify-end">
            <Button type="primary" htmlType="submit" loading={projectSaving} disabled={!canUpdateProject}>
              Save Changes
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
          <Title level={4} className="!mb-0">Project Labels</Title>
          <Text type="secondary">Manage labels used in this project.</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateLabel} disabled={!canManageLabels}>
          Add Label
        </Button>
      </div>
      <Spin spinning={labelsLoading}>
        <Table
          rowKey="id"
          columns={labelColumns}
          dataSource={labels}
          pagination={false}
          locale={{ emptyText: canReadLabels ? 'No labels yet' : 'No permission to view labels' }}
        />
      </Spin>

      <Modal
        title={editingLabel ? 'Edit Label' : 'Create Label'}
        open={labelModalOpen}
        onCancel={() => setLabelModalOpen(false)}
        onOk={handleSaveLabel}
        confirmLoading={labelSaving}
        okButtonProps={{ disabled: !canManageLabels }}
      >
        <Form form={labelForm} layout="vertical">
          <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Name is required' }]}>
            <Input placeholder="Label name" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={3} placeholder="Optional description" />
          </Form.Item>
          <Form.Item name="shortcut" label="Shortcut">
            <Input placeholder="Optional shortcut key" />
          </Form.Item>
          <Form.Item name="color" label="Color">
            <ColorPicker showText format="hex" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )

  const renderMembers = () => (
    <Card className="!border-github-border !bg-github-panel">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Title level={4} className="!mb-0">Project Members</Title>
          <Text type="secondary">Manage members and their roles in this project.</Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setMemberModalOpen(true)}
          disabled={!canManageMembers}
        >
          Add Member
        </Button>
      </div>
      {!canManageMembers ? (
        <div className="rounded-md border border-dashed border-github-border p-4 text-sm text-github-muted">
          You do not have permission to view or manage members.
        </div>
      ) : (
        <Spin spinning={membersLoading}>
          <Table
            rowKey="id"
            columns={memberColumns}
            dataSource={members}
            pagination={false}
            locale={{ emptyText: 'No members found' }}
          />
        </Spin>
      )}

      <Modal
        title="Add Member"
        open={memberModalOpen}
        onCancel={() => setMemberModalOpen(false)}
        onOk={handleAddMember}
        confirmLoading={memberSaving}
        okButtonProps={{ disabled: !canManageMembers }}
      >
        <Form form={memberForm} layout="vertical">
          <Form.Item
            name="userId"
            label="User"
            rules={[{ required: true, message: 'Please select a user' }]}
          >
            <Select
              showSearch
              placeholder="Select user"
              optionFilterProp="label"
              options={availableUsers.map((user) => ({
                value: user.id,
                label: `${user.fullName || user.email} (${user.email})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="roleId"
            label="Role"
            rules={[{ required: true, message: 'Please select a role' }]}
          >
            <Select
              placeholder="Select role"
              options={roles.map((role) => ({
                value: role.id,
                label: role.displayName || role.name,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Edit Member Role"
        open={memberEditModalOpen}
        onCancel={() => {
          setMemberEditModalOpen(false)
          setEditingMember(null)
        }}
        onOk={handleEditMemberRole}
        confirmLoading={memberActionId === editingMember?.id}
        okButtonProps={{ disabled: !canManageMembers }}
      >
        <Form form={memberEditForm} layout="vertical">
          <Form.Item
            name="roleId"
            label="Role"
            rules={[{ required: true, message: 'Please select a role' }]}
          >
            <Select
              placeholder="Select role"
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

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="flex flex-1 gap-6 overflow-hidden">
        <div className="w-[220px] shrink-0">
          <Card className="!border-github-border !bg-github-panel">
            <Menu
              mode="inline"
              selectedKeys={[section]}
              items={sectionItems}
              onClick={(info) => setSearchParams({ section: String(info.key) })}
            />
          </Card>
        </div>
        <div className="flex-1 min-w-0 overflow-y-auto pr-2">
          {section === 'basic' && renderBasicInfo()}
          {section === 'labels' && renderLabels()}
          {section === 'members' && renderMembers()}
        </div>
      </div>
    </div>
  )
}

export default ProjectSettings
