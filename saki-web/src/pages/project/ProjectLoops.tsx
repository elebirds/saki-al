import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {
    Alert,
    Button,
    Card,
    Col,
    Descriptions,
    Empty,
    Form,
    Input,
    InputNumber,
    List,
    Progress,
    Row,
    Select,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd'
import {useParams} from 'react-router-dom'
import {
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
    CartesianGrid,
} from 'recharts'

import {api} from '../../services/api'
import {useAuthStore} from '../../store/authStore'
import {
    ALLoop,
    LoopCreateRequest,
    ProjectBranch,
    RuntimeJob,
    RuntimeJobEvent,
    RuntimeMetricPoint,
    RuntimeTopKCandidate,
} from '../../types'

const {Text, Paragraph} = Typography

const STATUS_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    success: 'success',
    failed: 'error',
    cancelled: 'warning',
}

const TERMINAL_STATUS = new Set(['success', 'failed', 'cancelled'])

const formatDateTime = (value?: string | null) => {
    if (!value) return '-'
    try {
        return new Date(value).toLocaleString()
    } catch {
        return value
    }
}

const buildWsUrl = (jobId: string, afterSeq: number, token: string): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw
    const suffix = `/jobs/${jobId}/events/ws?after_seq=${afterSeq}&token=${encodeURIComponent(token)}`
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl.replace(/^http/, 'ws')}${suffix}`
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`
    return `${protocol}//${window.location.host}${path}${suffix}`
}

const eventToText = (event: RuntimeJobEvent): string => {
    if (event.eventType === 'log') {
        return `[${event.payload.level || 'INFO'}] ${event.payload.message || ''}`
    }
    if (event.eventType === 'status') {
        return `状态 => ${event.payload.status || ''} ${event.payload.reason || ''}`.trim()
    }
    if (event.eventType === 'progress') {
        return `进度 epoch=${event.payload.epoch ?? '-'} step=${event.payload.step ?? '-'} / ${event.payload.totalSteps ?? '-'}`
    }
    if (event.eventType === 'metric') {
        return `指标 ${JSON.stringify(event.payload.metrics || {})}`
    }
    if (event.eventType === 'artifact') {
        return `制品 ${event.payload.name || ''} -> ${event.payload.uri || ''}`
    }
    return `${event.eventType} ${JSON.stringify(event.payload || {})}`
}

const ProjectLoops: React.FC = () => {
    const {projectId} = useParams<{ projectId: string }>()
    const token = useAuthStore((state) => state.token)
    const [loops, setLoops] = useState<ALLoop[]>([])
    const [branches, setBranches] = useState<ProjectBranch[]>([])
    const [jobs, setJobs] = useState<RuntimeJob[]>([])

    const [selectedLoopId, setSelectedLoopId] = useState<string>()
    const [selectedJobId, setSelectedJobId] = useState<string>()

    const [jobDetail, setJobDetail] = useState<RuntimeJob | null>(null)
    const [metricPoints, setMetricPoints] = useState<RuntimeMetricPoint[]>([])
    const [topk, setTopk] = useState<RuntimeTopKCandidate[]>([])
    const [events, setEvents] = useState<RuntimeJobEvent[]>([])
    const [artifactsCount, setArtifactsCount] = useState<number>(0)
    const eventCursorRef = useRef<number>(0)
    const [wsConnected, setWsConnected] = useState<boolean>(false)

    const [loadingMeta, setLoadingMeta] = useState<boolean>(true)
    const [loadingJob, setLoadingJob] = useState<boolean>(false)
    const [startJobLoading, setStartJobLoading] = useState<boolean>(false)
    const [stopJobLoading, setStopJobLoading] = useState<boolean>(false)
    const [createLoopLoading, setCreateLoopLoading] = useState<boolean>(false)

    const [createLoopForm] = Form.useForm<LoopCreateRequest>()
    const [createJobForm] = Form.useForm<{
        pluginId: string;
        mode: string;
        jobType: string;
        queryStrategy: string;
        topk: number;
        epochs: number;
        batchSize: number;
        resourcesGpuCount: number;
    }>()

    const selectedLoop = useMemo(
        () => loops.find((item) => item.id === selectedLoopId),
        [loops, selectedLoopId]
    )
    const selectedBranch = useMemo(
        () => branches.find((item) => item.id === selectedLoop?.branchId),
        [branches, selectedLoop?.branchId]
    )

    const metricNames = useMemo(() => {
        const names = new Set<string>()
        metricPoints.forEach((item) => names.add(item.metricName))
        return Array.from(names)
    }, [metricPoints])

    const metricChartData = useMemo(() => {
        const rows = new Map<number, Record<string, number>>()
        metricPoints.forEach((point) => {
            const stepKey = Number(point.step || 0)
            const current = rows.get(stepKey) || {step: stepKey}
            current[point.metricName] = Number(point.metricValue)
            rows.set(stepKey, current)
        })
        return Array.from(rows.values()).sort((a, b) => (a.step || 0) - (b.step || 0))
    }, [metricPoints])

    const topkDataSource = useMemo(() => {
        return topk.map((item, idx) => ({
            rank: idx + 1,
            sampleId: item.sampleId,
            score: item.score,
            extra: item.extra,
        }))
    }, [topk])

    const loadJobs = useCallback(async (loopId: string, preferredJobId?: string) => {
        const list = await api.getLoopJobs(loopId, 100)
        setJobs(list)
        const nextJobId = preferredJobId || list[0]?.id
        setSelectedJobId(nextJobId)
        return nextJobId
    }, [])

    const loadJobDashboard = useCallback(async (jobId: string) => {
        setLoadingJob(true)
        try {
            const [job, points, candidates, artifacts, initialEvents] = await Promise.all([
                api.getJob(jobId),
                api.getJobMetricSeries(jobId, 5000),
                api.getJobSamplingTopK(jobId, 200),
                api.getJobArtifacts(jobId),
                api.getJobEvents(jobId, 0),
            ])
            setJobDetail(job)
            setMetricPoints(points)
            setTopk(candidates)
            setArtifactsCount(artifacts.artifacts.length)
            setEvents(initialEvents)
            eventCursorRef.current = initialEvents.reduce((max, item) => Math.max(max, item.seq), 0)
            setJobs((prev) => prev.map((item) => (item.id === job.id ? job : item)))
        } catch (error: any) {
            message.error(error?.message || '加载任务详情失败')
        } finally {
            setLoadingJob(false)
        }
    }, [])

    const loadMeta = useCallback(async () => {
        if (!projectId) return
        setLoadingMeta(true)
        try {
            const [loopList, branchList] = await Promise.all([
                api.getProjectLoops(projectId),
                api.getProjectBranches(projectId),
            ])
            setLoops(loopList)
            setBranches(branchList)

            if (branchList.length > 0 && !createLoopForm.getFieldValue('branchId')) {
                createLoopForm.setFieldValue('branchId', branchList[0].id)
            }

            const loopId = selectedLoopId && loopList.find((item) => item.id === selectedLoopId)
                ? selectedLoopId
                : loopList[0]?.id
            setSelectedLoopId(loopId)
            if (loopId) {
                const jobId = await loadJobs(loopId)
                if (jobId) {
                    await loadJobDashboard(jobId)
                } else {
                    setSelectedJobId(undefined)
                    setJobDetail(null)
                    setMetricPoints([])
                    setTopk([])
                    setEvents([])
                    setArtifactsCount(0)
                }
            } else {
                setJobs([])
                setSelectedJobId(undefined)
                setJobDetail(null)
                setMetricPoints([])
                setTopk([])
                setEvents([])
                setArtifactsCount(0)
            }
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 信息失败')
        } finally {
            setLoadingMeta(false)
        }
    }, [projectId, selectedLoopId, createLoopForm, loadJobs, loadJobDashboard])

    useEffect(() => {
        createJobForm.setFieldsValue({
            pluginId: 'demo_det_v1',
            mode: 'active_learning',
            jobType: 'train_detection',
            queryStrategy: 'uncertainty_1_minus_max_conf',
            topk: 200,
            epochs: 5,
            batchSize: 8,
            resourcesGpuCount: 1,
        })
        void loadMeta()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [projectId])

    useEffect(() => {
        if (!selectedJobId) return
        const timer = setInterval(async () => {
            try {
                const [newEvents, job] = await Promise.all([
                    api.getJobEvents(selectedJobId, eventCursorRef.current),
                    api.getJob(selectedJobId),
                ])
                if (newEvents.length > 0) {
                    setEvents((prev) => {
                        const merged = [...prev, ...newEvents]
                        const dedup = new Map<number, RuntimeJobEvent>()
                        merged.forEach((item) => dedup.set(item.seq, item))
                        return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq)
                    })
                    eventCursorRef.current = Math.max(
                        eventCursorRef.current,
                        ...newEvents.map((item) => item.seq),
                    )
                }
                setJobDetail(job)
                setJobs((prev) => prev.map((item) => (item.id === job.id ? job : item)))

                if (newEvents.some((item) => item.eventType === 'metric') || job.status === 'running') {
                    const points = await api.getJobMetricSeries(selectedJobId, 5000)
                    setMetricPoints(points)
                }
                if (TERMINAL_STATUS.has(job.status)) {
                    const [candidates, artifacts] = await Promise.all([
                        api.getJobSamplingTopK(selectedJobId, 200),
                        api.getJobArtifacts(selectedJobId),
                    ])
                    setTopk(candidates)
                    setArtifactsCount(artifacts.artifacts.length)
                }
            } catch {
                // 忽略轮询错误，下一轮继续
            }
        }, 3000)
        return () => clearInterval(timer)
    }, [selectedJobId])

    useEffect(() => {
        if (!selectedJobId || !token) return
        const ws = new WebSocket(buildWsUrl(selectedJobId, eventCursorRef.current, token))

        ws.onopen = () => setWsConnected(true)
        ws.onclose = () => setWsConnected(false)
        ws.onerror = () => setWsConnected(false)
        ws.onmessage = (event: MessageEvent<string>) => {
            try {
                const payload = JSON.parse(event.data || '{}') as RuntimeJobEvent
                if (!payload || typeof payload.seq !== 'number') return
                setEvents((prev) => {
                    const merged = [...prev, payload]
                    const dedup = new Map<number, RuntimeJobEvent>()
                    merged.forEach((item) => dedup.set(item.seq, item))
                    return Array.from(dedup.values()).sort((a, b) => a.seq - b.seq)
                })
                eventCursorRef.current = Math.max(eventCursorRef.current, payload.seq)
            } catch {
                // ignore malformed ws payload
            }
        }

        return () => {
            ws.close()
            setWsConnected(false)
        }
    }, [selectedJobId, token])

    const handleLoopChange = async (value: string) => {
        setSelectedLoopId(value)
        setSelectedJobId(undefined)
        setJobDetail(null)
        setMetricPoints([])
        setTopk([])
        setEvents([])
        setArtifactsCount(0)
        try {
            const jobId = await loadJobs(value)
            if (jobId) {
                await loadJobDashboard(jobId)
            }
        } catch (error: any) {
            message.error(error?.message || '加载 Loop 任务失败')
        }
    }

    const handleJobChange = async (value: string) => {
        setSelectedJobId(value)
        await loadJobDashboard(value)
    }

    const handleCreateLoop = async (values: LoopCreateRequest) => {
        if (!projectId) return
        setCreateLoopLoading(true)
        try {
            const created = await api.createProjectLoop(projectId, values)
            message.success('Loop 创建成功')
            await loadMeta()
            setSelectedLoopId(created.id)
            const nextJobId = await loadJobs(created.id)
            if (nextJobId) {
                setSelectedJobId(nextJobId)
                await loadJobDashboard(nextJobId)
            } else {
                setSelectedJobId(undefined)
                setJobDetail(null)
                setMetricPoints([])
                setTopk([])
                setEvents([])
                setArtifactsCount(0)
            }
            createLoopForm.resetFields(['name'])
        } catch (error: any) {
            message.error(error?.message || 'Loop 创建失败')
        } finally {
            setCreateLoopLoading(false)
        }
    }

    const handleStartJob = async () => {
        if (!projectId || !selectedLoop) {
            message.warning('请先选择一个 Loop')
            return
        }
        if (!selectedBranch?.headCommitId) {
            message.error('该 Loop 绑定分支没有可用的 head commit，无法启动任务')
            return
        }

        const values = createJobForm.getFieldsValue()
        setStartJobLoading(true)
        try {
            const created = await api.createLoopJob(
                selectedLoop.id,
                {
                    projectId,
                    sourceCommitId: selectedBranch.headCommitId,
                    pluginId: values.pluginId,
                    mode: values.mode,
                    jobType: values.jobType,
                    queryStrategy: values.queryStrategy,
                    params: {
                        epochs: values.epochs,
                        batchSize: values.batchSize,
                        topk: values.topk,
                    },
                    resources: {
                        gpuCount: values.resourcesGpuCount,
                    },
                },
                true
            )
            message.success('任务已创建并尝试派发')
            const nextJobId = await loadJobs(selectedLoop.id, created.id)
            if (nextJobId) {
                setSelectedJobId(nextJobId)
                await loadJobDashboard(nextJobId)
            }
        } catch (error: any) {
            message.error(error?.message || '创建任务失败')
        } finally {
            setStartJobLoading(false)
        }
    }

    const handleStopJob = async () => {
        if (!selectedJobId) return
        setStopJobLoading(true)
        try {
            const resp = await api.stopJob(selectedJobId, 'user requested stop')
            message.info(`停止命令已提交，状态：${resp.status}`)
            await loadJobDashboard(selectedJobId)
        } catch (error: any) {
            message.error(error?.message || '停止任务失败')
        } finally {
            setStopJobLoading(false)
        }
    }

    if (loadingMeta) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        )
    }

    return (
        <div className="flex h-full flex-col gap-4 overflow-auto pr-1">
            <Card className="!border-github-border !bg-github-panel">
                <Row gutter={[16, 16]}>
                    <Col xs={24} lg={14}>
                        <Space direction="vertical" size="middle" className="w-full">
                            <Space wrap>
                                <Select
                                    className="min-w-[220px]"
                                    placeholder="选择 Loop"
                                    value={selectedLoopId}
                                    onChange={handleLoopChange}
                                    options={loops.map((item) => ({label: item.name, value: item.id}))}
                                />
                                <Select
                                    className="min-w-[260px]"
                                    placeholder="选择任务"
                                    value={selectedJobId}
                                    onChange={handleJobChange}
                                    options={jobs.map((item) => ({
                                        label: `iter#${item.iteration} · ${item.status} · ${item.id.slice(0, 8)}`,
                                        value: item.id,
                                    }))}
                                />
                                <Button onClick={loadMeta}>刷新</Button>
                                <Button
                                    danger
                                    onClick={handleStopJob}
                                    loading={stopJobLoading}
                                    disabled={!jobDetail || jobDetail.status !== 'running'}
                                >
                                    停止任务
                                </Button>
                            </Space>

                            {!selectedLoop ? (
                                <Alert type="info" showIcon message="当前项目还没有 Loop，请先在右侧创建。"/>
                            ) : (
                                <Alert
                                    type="info"
                                    showIcon
                                    message={`当前 Loop：${selectedLoop.name}`}
                                    description={
                                        <>
                                            <div>策略：{selectedLoop.queryStrategy}</div>
                                            <div>分支：{selectedBranch?.name || selectedLoop.branchId}</div>
                                            <div>事件流：{wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接（HTTP 轮询中）'}</div>
                                        </>
                                    }
                                />
                            )}

                            <Form form={createJobForm} layout="inline">
                                <Form.Item name="pluginId" label="插件">
                                    <Input className="w-[140px]"/>
                                </Form.Item>
                                <Form.Item name="mode" label="模式">
                                    <Select
                                        className="w-[150px]"
                                        options={[
                                            {label: '主动学习', value: 'active_learning'},
                                            {label: '模拟训练', value: 'simulation'},
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item name="jobType" label="任务类型">
                                    <Input className="w-[150px]"/>
                                </Form.Item>
                                <Form.Item name="queryStrategy" label="采样策略">
                                    <Select
                                        className="w-[240px]"
                                        options={[
                                            {label: 'uncertainty_1_minus_max_conf', value: 'uncertainty_1_minus_max_conf'},
                                            {label: 'aug_iou_disagreement', value: 'aug_iou_disagreement'},
                                            {label: 'random_baseline', value: 'random_baseline'},
                                            {label: 'plugin_native_strategy', value: 'plugin_native_strategy'},
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item name="epochs" label="epochs">
                                    <InputNumber min={1} max={200}/>
                                </Form.Item>
                                <Form.Item name="batchSize" label="batch">
                                    <InputNumber min={1} max={2048}/>
                                </Form.Item>
                                <Form.Item name="topk" label="topk">
                                    <InputNumber min={1} max={5000}/>
                                </Form.Item>
                                <Form.Item name="resourcesGpuCount" label="gpu">
                                    <InputNumber min={0} max={16}/>
                                </Form.Item>
                            </Form>

                            <Button
                                type="primary"
                                loading={startJobLoading}
                                onClick={handleStartJob}
                                disabled={!selectedLoop}
                            >
                                启动任务
                            </Button>
                        </Space>
                    </Col>

                    <Col xs={24} lg={10}>
                        <Card
                            size="small"
                            title="创建 Loop"
                            className="!border-github-border !bg-github-panel"
                        >
                            <Form form={createLoopForm} layout="vertical" onFinish={handleCreateLoop}>
                                <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入 loop 名称'}]}>
                                    <Input placeholder="例如：det-uncertainty-master"/>
                                </Form.Item>
                                <Form.Item name="branchId" label="绑定分支" rules={[{required: true, message: '请选择分支'}]}>
                                    <Select options={branches.map((item) => ({label: item.name, value: item.id}))}/>
                                </Form.Item>
                                <Form.Item name="queryStrategy" label="默认采样策略" initialValue="uncertainty_1_minus_max_conf">
                                    <Input/>
                                </Form.Item>
                                <Form.Item name="modelArch" label="模型架构" initialValue="demo_det_v1">
                                    <Input/>
                                </Form.Item>
                                <Button type="dashed" htmlType="submit" loading={createLoopLoading}>
                                    创建 Loop
                                </Button>
                            </Form>
                        </Card>
                    </Col>
                </Row>
            </Card>

            {!selectedJobId ? (
                <Card className="!border-github-border !bg-github-panel">
                    <Empty description="当前 Loop 还没有任务"/>
                </Card>
            ) : loadingJob ? (
                <Card className="!border-github-border !bg-github-panel">
                    <div className="flex h-[320px] items-center justify-center">
                        <Spin/>
                    </div>
                </Card>
            ) : (
                <>
                    <Card className="!border-github-border !bg-github-panel" title="任务概览">
                        <Descriptions size="small" column={3}>
                            <Descriptions.Item label="任务 ID">
                                <Text code>{jobDetail?.id || '-'}</Text>
                            </Descriptions.Item>
                            <Descriptions.Item label="状态">
                                <Tag color={STATUS_COLOR[jobDetail?.status || 'pending']}>
                                    {jobDetail?.status || '-'}
                                </Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="执行器">
                                {jobDetail?.assignedExecutorId || '-'}
                            </Descriptions.Item>
                            <Descriptions.Item label="插件">{jobDetail?.pluginId || '-'}</Descriptions.Item>
                            <Descriptions.Item label="开始时间">{formatDateTime(jobDetail?.startedAt)}</Descriptions.Item>
                            <Descriptions.Item label="结束时间">{formatDateTime(jobDetail?.endedAt)}</Descriptions.Item>
                            <Descriptions.Item label="采样策略">{jobDetail?.queryStrategy || '-'}</Descriptions.Item>
                            <Descriptions.Item label="重试次数">{jobDetail?.retryCount ?? 0}</Descriptions.Item>
                            <Descriptions.Item label="制品数量">{artifactsCount}</Descriptions.Item>
                        </Descriptions>
                        {jobDetail?.lastError ? (
                            <Alert type="error" showIcon className="mt-3" message={jobDetail.lastError}/>
                        ) : null}
                        <Paragraph className="!mb-0 !mt-3">
                            <Text type="secondary">超参：{JSON.stringify(jobDetail?.params || {})}</Text>
                        </Paragraph>
                    </Card>

                    <Row gutter={[16, 16]}>
                        <Col xs={24} lg={14}>
                            <Card className="!border-github-border !bg-github-panel" title="训练曲线">
                                {metricChartData.length === 0 ? (
                                    <Empty description="暂无指标曲线"/>
                                ) : (
                                    <div className="h-[320px]">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <LineChart data={metricChartData}>
                                                <CartesianGrid strokeDasharray="3 3"/>
                                                <XAxis dataKey="step"/>
                                                <YAxis/>
                                                <Tooltip/>
                                                {metricNames.map((name, idx) => (
                                                    <Line
                                                        key={name}
                                                        type="monotone"
                                                        dataKey={name}
                                                        dot={false}
                                                        stroke={['#1677ff', '#52c41a', '#faad14', '#13c2c2', '#eb2f96'][idx % 5]}
                                                        strokeWidth={2}
                                                    />
                                                ))}
                                            </LineChart>
                                        </ResponsiveContainer>
                                    </div>
                                )}
                            </Card>
                        </Col>
                        <Col xs={24} lg={10}>
                            <Card className="!border-github-border !bg-github-panel" title="实时日志（最新 200 条）">
                                <List
                                    size="small"
                                    dataSource={events.slice(-200)}
                                    locale={{emptyText: '暂无日志'}}
                                    className="max-h-[320px] overflow-auto"
                                    renderItem={(item) => (
                                        <List.Item className="!items-start">
                                            <div className="w-full">
                                                <div className="text-xs text-github-muted">
                                                    #{item.seq} · {formatDateTime(item.ts)}
                                                </div>
                                                <div className="font-mono text-xs whitespace-pre-wrap break-all">
                                                    {eventToText(item)}
                                                </div>
                                            </div>
                                        </List.Item>
                                    )}
                                />
                            </Card>
                        </Col>
                    </Row>

                    <Card className="!border-github-border !bg-github-panel" title="TopK 候选样本">
                        <Table
                            size="small"
                            pagination={{pageSize: 10, showSizeChanger: false}}
                            dataSource={topkDataSource}
                            rowKey={(item) => item.sampleId}
                            columns={[
                                {
                                    title: '#',
                                    dataIndex: 'rank',
                                    width: 60,
                                },
                                {
                                    title: 'Sample ID',
                                    dataIndex: 'sampleId',
                                    render: (value: string) => <Text code>{value}</Text>,
                                },
                                {
                                    title: 'Score',
                                    dataIndex: 'score',
                                    width: 260,
                                    render: (value: number) => (
                                        <Space direction="vertical" size={2} className="w-full">
                                            <Progress percent={Math.max(0, Math.min(100, Number((value * 100).toFixed(2))))}/>
                                            <Text type="secondary">{value.toFixed(6)}</Text>
                                        </Space>
                                    ),
                                },
                                {
                                    title: 'Detail',
                                    dataIndex: 'extra',
                                    render: (value: Record<string, number>) => (
                                        <Text type="secondary">{JSON.stringify(value || {})}</Text>
                                    ),
                                },
                            ]}
                        />
                    </Card>
                </>
            )}
        </div>
    )
}

export default ProjectLoops
