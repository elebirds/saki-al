import React from 'react'
import {Card, Divider, Steps, Tag} from 'antd'
import {
    ApiOutlined,
    BranchesOutlined,
    CheckCircleOutlined,
    CloudServerOutlined,
    DatabaseOutlined,
    ExperimentOutlined,
    EyeOutlined,
    RocketOutlined,
    SyncOutlined,
} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'

const About: React.FC = () => {
    const {t} = useTranslation()
    const cardClassName = '!border-github-border !bg-github-panel'

    return (
        <div className="space-y-6">
            <div
                className="rounded-xl border border-github-border bg-gradient-to-r from-[var(--github-panel)] via-[var(--github-base)] to-[var(--github-panel)] p-6">
                <div className="flex flex-wrap items-center gap-3">
                    <div
                        className="flex h-10 w-10 items-center justify-center rounded-lg bg-github-accent/10 text-github-accent">
                        <RocketOutlined/>
                    </div>
                    <div>
                        <h2 className="text-xl font-semibold text-github-text">Saki AL</h2>
                        <p className="text-sm text-github-muted">{t('app.about')} · Visual Active Learning Platform</p>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        <Tag color="blue">Human-in-the-loop</Tag>
                        <Tag color="green">Git-like Versioning</Tag>
                        <Tag color="purple">Active Learning Loop</Tag>
                    </div>
                </div>
                <p className="mt-4 text-sm text-github-text">
                    Saki 是一个集数据集管理、样本标注（支持版本控制）、模型训练与视觉主动学习于一体的闭环智能标注平台。
                    通过 Human-in-the-loop 流程，让高价值样本优先进入标注与训练，降低成本并提升迭代效率。
                </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <DatabaseOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">数据与资产</h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        数据集管理与内容寻址，保证数据可追溯、可复用、可去重。
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="geekblue">Asset SHA256</Tag>
                        <Tag color="geekblue">Dataset/Sample</Tag>
                        <Tag color="geekblue">MinIO</Tag>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <BranchesOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">标注版本控制</h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        标注记录不可变，Commit 快照 + Branch 指针，让标注版本像 Git 一样可回溯。
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="purple">Annotation</Tag>
                        <Tag color="purple">Commit/CAMap</Tag>
                        <Tag color="purple">Branch</Tag>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <ExperimentOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">训练与主动学习</h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        Runtime 以无状态执行器方式运行训练/推理任务，持续闭环筛选高价值样本。
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="green">ALLoop</Tag>
                        <Tag color="green">Job/Metric</Tag>
                        <Tag color="green">Model</Tag>
                    </div>
                </Card>
            </div>

            <Card className={cardClassName}>
                <div className="flex items-center gap-2">
                    <SyncOutlined className="text-github-accent"/>
                    <h3 className="text-base font-semibold text-github-text">核心工作流</h3>
                </div>
                <Divider className="!my-4"/>
                <Steps
                    size="small"
                    items={[
                        {title: '数据导入'},
                        {title: '样本标注'},
                        {title: '版本快照'},
                        {title: '模型训练'},
                        {title: '主动学习选样'},
                        {title: '迭代优化'},
                    ]}
                />
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <ApiOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">技术栈概览</h3>
                    </div>
                    <div className="mt-3 space-y-2 text-sm text-github-muted">
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="blue">Frontend</Tag>
                            <span>React 18 · Vite · TypeScript · Ant Design · Tailwind</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="green">Backend</Tag>
                            <span>FastAPI · SQLModel · PostgreSQL · MinIO</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="purple">Runtime</Tag>
                            <span>FastAPI · WebSocket · Subprocess · HTTPX</span>
                        </div>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <CloudServerOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">开发状态</h3>
                    </div>
                    <div className="mt-4 grid gap-3 text-sm">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <CheckCircleOutlined className="text-github-success"/>
                                <span>saki-api L1</span>
                            </div>
                            <Tag color="green">完成</Tag>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <EyeOutlined className="text-github-accent"/>
                                <span>saki-api L2</span>
                            </div>
                            <Tag color="orange">开发中</Tag>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <EyeOutlined className="text-github-muted"/>
                                <span>saki-runtime</span>
                            </div>
                            <Tag color="default">计划中</Tag>
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    )
}

export default About
