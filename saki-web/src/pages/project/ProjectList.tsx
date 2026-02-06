import React, {useCallback, useEffect, useState} from 'react'
import {Button, Card, Form, Input, message, Modal, Select, Tag, Tooltip, Typography} from 'antd'
import {useNavigate} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import {PlusOutlined} from '@ant-design/icons'
import {api} from '../../services/api'
import {PaginatedList} from '../../components/common/PaginatedList'
import {Dataset, Project, TaskType} from '../../types'
import {usePermission} from '../../hooks'

const {Title, Text} = Typography
const {Option} = Select

const ProjectList: React.FC = () => {
    const {t} = useTranslation()
    const navigate = useNavigate()
    const [createOpen, setCreateOpen] = useState(false)
    const [creating, setCreating] = useState(false)
    const [refreshKey, setRefreshKey] = useState(0)
    const [datasets, setDatasets] = useState<Dataset[]>([])
    const [datasetsLoading, setDatasetsLoading] = useState(false)
    const [form] = Form.useForm()
    const {can} = usePermission()
    const canCreate = can('project:create')

    const taskTypeLabel: Record<string, string> = {
        classification: t('project.settings.taskType.classification'),
        detection: t('project.settings.taskType.detection'),
        segmentation: t('project.settings.taskType.segmentation'),
    }

    const statusLabel: Record<string, string> = {
        active: t('project.settings.status.active'),
        archived: t('project.settings.status.archived'),
    }

    const fetchProjects = useCallback(
        (page: number, pageSize: number) => api.getProjects(page, pageSize),
        []
    )

    useEffect(() => {
        if (!createOpen) return
        setDatasetsLoading(true)
        api.getDatasets(1, 200)
            .then((res) => {
                setDatasets(res.items || [])
            })
            .catch(() => {
                message.error(t('dataset.list.loadError'))
            })
            .finally(() => setDatasetsLoading(false))
    }, [createOpen, t])

    const handleCreateProject = async () => {
        try {
            const values = await form.validateFields()
            setCreating(true)
            await api.createProject({
                name: values.name,
                description: values.description,
                taskType: values.taskType as TaskType,
                datasetIds: values.datasetIds || [],
            })
            message.success(t('project.list.createSuccess'))
            setCreateOpen(false)
            form.resetFields()
            setRefreshKey((v) => v + 1)
        } catch (error: any) {
            if (error?.errorFields) return
            message.error(t('project.list.createError'))
        } finally {
            setCreating(false)
        }
    }

    return (
        <div className="flex h-full flex-col">
            <div className="mb-4 flex items-center justify-between">
                <Title level={3} className="!mb-0">{t('project.list.title')}</Title>
                {canCreate ? (
                    <Button type="primary" icon={<PlusOutlined/>} onClick={() => setCreateOpen(true)}>
                        {t('project.list.newProject')}
                    </Button>
                ) : (
                    <Tooltip title={t('common.noPermission')}>
                        <Button type="primary" icon={<PlusOutlined/>} disabled>
                            {t('project.list.newProject')}
                        </Button>
                    </Tooltip>
                )}
            </div>

            <div className="flex-1 overflow-hidden">
                <PaginatedList<Project>
                    fetchData={fetchProjects}
                    refreshKey={refreshKey}
                    resetPageOnRefresh
                    initialPageSize={12}
                    pageSizeOptions={['8', '12', '20', '32', '50']}
                    renderItems={(items) => (
                        <div className="grid gap-4">
                            {items.map((project) => (
                                <Card
                                    key={project.id}
                                    className="!border-github-border !bg-github-panel hover:!border-github-border-muted"
                                    onClick={() => navigate(`/projects/${project.id}`)}
                                >
                                    <div className="flex flex-wrap items-center justify-between gap-4">
                                        <div>
                                            <div
                                                className="text-base font-semibold text-github-text">{project.name}</div>
                                            {project.description && (
                                                <Text type="secondary" className="text-sm">
                                                    {project.description}
                                                </Text>
                                            )}
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <Tag
                                                color="blue">{taskTypeLabel[project.taskType] || project.taskType}</Tag>
                                            <Tag color={project.status === 'active' ? 'green' : 'default'}>
                                                {statusLabel[project.status] || project.status}
                                            </Tag>
                                        </div>
                                    </div>
                                    <div
                                        className="mt-4 grid grid-cols-2 gap-4 text-xs text-github-muted sm:grid-cols-4">
                                        <div>
                                            <div className="text-github-text font-semibold">{project.datasetCount}</div>
                                            <div>{t('project.list.stats.datasets')}</div>
                                        </div>
                                        <div>
                                            <div className="text-github-text font-semibold">{project.labelCount}</div>
                                            <div>{t('project.list.stats.labels')}</div>
                                        </div>
                                        <div>
                                            <div className="text-github-text font-semibold">{project.branchCount}</div>
                                            <div>{t('project.list.stats.branches')}</div>
                                        </div>
                                        <div>
                                            <div className="text-github-text font-semibold">{project.commitCount}</div>
                                            <div>{t('project.list.stats.commits')}</div>
                                        </div>
                                    </div>
                                </Card>
                            ))}
                        </div>
                    )}
                />
            </div>

            <Modal
                title={t('project.list.newProject')}
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                onOk={handleCreateProject}
                okButtonProps={{loading: creating}}
                cancelButtonProps={{disabled: creating}}
            >
                <Form form={form} layout="vertical" initialValues={{taskType: 'classification'}}>
                    <Form.Item
                        name="name"
                        label={t('project.settings.basic.projectName')}
                        rules={[{required: true, message: t('project.settings.basic.projectNameRequired')}]}
                    >
                        <Input placeholder={t('project.settings.basic.projectNamePlaceholder')}/>
                    </Form.Item>
                    <Form.Item name="description" label={t('project.settings.basic.description')}>
                        <Input.TextArea placeholder={t('project.settings.basic.descriptionPlaceholder')} rows={3}/>
                    </Form.Item>
                    <Form.Item
                        name="taskType"
                        label={t('project.settings.basic.taskType')}
                        rules={[{required: true}]}
                    >
                        <Select>
                            <Option value="classification">{taskTypeLabel.classification}</Option>
                            <Option value="detection">{taskTypeLabel.detection}</Option>
                            <Option value="segmentation">{taskTypeLabel.segmentation}</Option>
                        </Select>
                    </Form.Item>
                    <Form.Item name="datasetIds" label={t('project.form.dataPool')}>
                        <Select
                            mode="multiple"
                            placeholder={t('dataset.list.newDataset')}
                            loading={datasetsLoading}
                            options={datasets.map((dataset) => ({
                                value: dataset.id,
                                label: dataset.name,
                            }))}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    )
}

export default ProjectList
