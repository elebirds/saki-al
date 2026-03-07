import React from 'react'
import {Card, Divider, Tag, Timeline} from 'antd'
import {
    ApiOutlined,
    BranchesOutlined,
    CheckCircleOutlined,
    ClockCircleOutlined,
    CloudServerOutlined,
    DatabaseOutlined,
    DeploymentUnitOutlined,
    ExperimentOutlined,
    EyeOutlined,
    MonitorOutlined,
    RocketOutlined,
    SyncOutlined,
} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'

type StatusKey = 'done' | 'active' | 'planned'
type DevStatusState = 'completed' | 'inProgress' | 'planned'

type ArchitectureModuleKey = 'api' | 'dispatcher' | 'executor' | 'web'
type HeroMetricKey = 'clarity' | 'trust' | 'efficiency' | 'continuity'
type MainDesignKey = 'dataAssets' | 'annotationVersioning' | 'training'
type WorkflowStepKey = 'prepare' | 'annotate' | 'train' | 'review' | 'iterate'
type DevStatusKey = 'dataAnnotation' | 'runtimeExperience' | 'opsObservability'

const statusColorMap: Record<StatusKey, string> = {
    done: 'green',
    active: 'blue',
    planned: 'default',
}

const devStatusColorMap: Record<DevStatusState, string> = {
    completed: 'green',
    inProgress: 'blue',
    planned: 'default',
}

const About: React.FC = () => {
    const {t} = useTranslation()
    const cardClassName = '!border-github-border !bg-github-panel !shadow-none'

    const heroMetricKeys: HeroMetricKey[] = ['clarity', 'trust', 'efficiency', 'continuity']

    const architectureModules: Array<{ key: ArchitectureModuleKey; icon: React.ReactNode; status: StatusKey }> = [
        {key: 'api', icon: <ApiOutlined/>, status: 'done'},
        {key: 'dispatcher', icon: <DeploymentUnitOutlined/>, status: 'done'},
        {key: 'executor', icon: <CloudServerOutlined/>, status: 'active'},
        {key: 'web', icon: <MonitorOutlined/>, status: 'active'},
    ]
    const mainDesignItems: Array<{
        key: MainDesignKey
        icon: React.ReactNode
        tagColor: string
        tagKeys: string[]
    }> = [
        {
            key: 'dataAssets',
            icon: <DatabaseOutlined className="text-github-accent"/>,
            tagColor: 'geekblue',
            tagKeys: ['assetSha', 'datasetSample', 'minio'],
        },
        {
            key: 'annotationVersioning',
            icon: <BranchesOutlined className="text-github-accent"/>,
            tagColor: 'purple',
            tagKeys: ['annotation', 'commitMap', 'branch'],
        },
        {
            key: 'training',
            icon: <ExperimentOutlined className="text-github-accent"/>,
            tagColor: 'green',
            tagKeys: ['alLoop', 'jobMetric', 'model'],
        },
    ]
    const workflowStepKeys: WorkflowStepKey[] = ['prepare', 'annotate', 'train', 'review', 'iterate']
    const devStatusItems: Array<{ key: DevStatusKey; state: DevStatusState; icon: React.ReactNode }> = [
        {key: 'dataAnnotation', state: 'completed', icon: <CheckCircleOutlined className="text-github-success"/>},
        {key: 'runtimeExperience', state: 'inProgress', icon: <EyeOutlined className="text-github-accent"/>},
        {key: 'opsObservability', state: 'planned', icon: <ClockCircleOutlined className="text-github-muted"/>},
    ]

    return (
        <div className="space-y-6">
            <section className="relative overflow-hidden rounded-2xl border border-github-border bg-github-panel p-6">
                <div className="pointer-events-none absolute -right-14 -top-20 h-56 w-56 rounded-full bg-github-accent/20 blur-3xl"/>
                <div className="pointer-events-none absolute -bottom-24 left-8 h-52 w-52 rounded-full bg-github-link/10 blur-3xl"/>

                <div className="relative flex flex-wrap items-center gap-3">
                    <div
                        className="flex h-10 w-10 items-center justify-center rounded-lg border border-github-border bg-github-accent/10 text-github-accent">
                        <RocketOutlined/>
                    </div>
                    <div>
                        <h2 className="text-xl font-semibold text-github-text">{t('about.hero.title')}</h2>
                        <p className="text-sm text-github-muted">
                            {t('about.hero.subtitle')}
                        </p>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        <Tag color="blue">{t('about.hero.tags.humanLoop')}</Tag>
                        <Tag color="green">{t('about.hero.tags.gitLike')}</Tag>
                        <Tag color="orange">{t('about.hero.tags.activeLoop')}</Tag>
                    </div>
                </div>

                <p className="relative mt-4 max-w-4xl text-sm leading-6 text-github-text">
                    {t('about.hero.description')}
                </p>

                <div className="relative mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {heroMetricKeys.map((key) => (
                        <div
                            key={key}
                            className="rounded-xl border border-github-border bg-[var(--github-base)]/70 p-3 backdrop-blur-sm"
                        >
                            <p className="text-xs text-github-muted">{t(`about.hero.metrics.${key}.label`)}</p>
                            <p className="mt-1 text-sm font-semibold text-github-text">
                                {t(`about.hero.metrics.${key}.value`)}
                            </p>
                            <p className="mt-1 text-xs text-github-muted">{t(`about.hero.metrics.${key}.hint`)}</p>
                        </div>
                    ))}
                </div>
            </section>

            <Card className={cardClassName}>
                <div className="flex items-center gap-2">
                    <SyncOutlined className="text-github-accent"/>
                    <h3 className="text-base font-semibold text-github-text">
                        {t('about.sections.architecture.title')}
                    </h3>
                </div>
                <Divider className="!my-4"/>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {architectureModules.map((item) => (
                        <div
                            key={item.key}
                            className="rounded-xl border border-github-border bg-[var(--github-base)] px-4 py-3"
                        >
                            <div className="flex items-center justify-between">
                                <span className="text-github-accent">{item.icon}</span>
                                <Tag color={statusColorMap[item.status]}>
                                    {t(`about.sections.status.${item.status}`)}
                                </Tag>
                            </div>
                            <h4 className="mt-2 text-sm font-semibold text-github-text">
                                {t(`about.sections.architecture.modules.${item.key}.name`)}
                            </h4>
                            <p className="mt-1 text-xs leading-5 text-github-muted">
                                {t(`about.sections.architecture.modules.${item.key}.role`)}
                            </p>
                            <p className="mt-2 text-xs font-medium text-github-text">
                                {t(`about.sections.architecture.modules.${item.key}.status`)}
                            </p>
                        </div>
                    ))}
                </div>
            </Card>

            <Card className={cardClassName}>
                <div className="flex items-center gap-2">
                    <RocketOutlined className="text-github-accent"/>
                    <h3 className="text-base font-semibold text-github-text">
                        {t('about.sections.mainDesign.title')}
                    </h3>
                </div>
                <p className="mt-2 text-sm text-github-muted">{t('about.sections.mainDesign.intro')}</p>
                <Divider className="!my-4"/>
                <div className="grid gap-3 lg:grid-cols-3">
                    {mainDesignItems.map((item) => (
                        <div key={item.key} className="rounded-xl border border-github-border bg-[var(--github-base)] px-4 py-3">
                            <div className="flex items-center gap-2">
                                {item.icon}
                                <h4 className="text-sm font-semibold text-github-text">
                                    {t(`about.sections.mainDesign.items.${item.key}.title`)}
                                </h4>
                            </div>
                            <p className="mt-2 text-xs leading-5 text-github-muted">
                                {t(`about.sections.mainDesign.items.${item.key}.body`)}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-2 text-xs">
                                {item.tagKeys.map((tagKey) => (
                                    <Tag key={tagKey} color={item.tagColor}>
                                        {t(`about.sections.mainDesign.items.${item.key}.tags.${tagKey}`)}
                                    </Tag>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <SyncOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.workflow.title')}
                        </h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">{t('about.sections.workflow.intro')}</p>
                    <Timeline
                        className="mt-4"
                        items={workflowStepKeys.map((key) => ({
                            color: 'blue',
                            children: (
                                <div className="pb-2">
                                    <p className="text-sm font-semibold text-github-text">
                                        {t(`about.sections.workflow.steps.${key}.title`)}
                                    </p>
                                    <p className="mt-1 text-xs leading-5 text-github-muted">
                                        {t(`about.sections.workflow.steps.${key}.desc`)}
                                    </p>
                                </div>
                            ),
                        }))}
                    />
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <ApiOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.techStack.title')}
                        </h3>
                    </div>
                    <div className="mt-4 space-y-3 text-sm text-github-muted">
                        <div className="rounded-lg border border-github-border bg-[var(--github-base)] px-3 py-2">
                            <div className="mb-1 flex items-center gap-2">
                                <Tag color="blue">{t('about.sections.techStack.frontend.label')}</Tag>
                            </div>
                            <p>{t('about.sections.techStack.frontend.stack')}</p>
                        </div>
                        <div className="rounded-lg border border-github-border bg-[var(--github-base)] px-3 py-2">
                            <div className="mb-1 flex items-center gap-2">
                                <Tag color="green">{t('about.sections.techStack.backend.label')}</Tag>
                            </div>
                            <p>{t('about.sections.techStack.backend.stack')}</p>
                        </div>
                        <div className="rounded-lg border border-github-border bg-[var(--github-base)] px-3 py-2">
                            <div className="mb-1 flex items-center gap-2">
                                <Tag color="orange">{t('about.sections.techStack.runtime.label')}</Tag>
                            </div>
                            <p>{t('about.sections.techStack.runtime.stack')}</p>
                        </div>
                    </div>
                </Card>
            </div>

            <Card className={cardClassName}>
                <div className="flex items-center gap-2">
                    <CloudServerOutlined className="text-github-accent"/>
                    <h3 className="text-base font-semibold text-github-text">
                        {t('about.sections.devStatus.title')}
                    </h3>
                </div>
                <div className="mt-4 space-y-3 text-sm">
                    {devStatusItems.map((item) => (
                        <div
                            key={item.key}
                            className="flex items-center justify-between rounded-lg border border-github-border bg-[var(--github-base)] px-3 py-2"
                        >
                            <div className="flex items-center gap-2 text-github-text">
                                {item.icon}
                                <span>{t(`about.sections.devStatus.items.${item.key}`)}</span>
                            </div>
                            <Tag color={devStatusColorMap[item.state]}>
                                {t(`about.sections.devStatus.status.${item.state}`)}
                            </Tag>
                        </div>
                    ))}
                    <div className="rounded-lg border border-dashed border-github-border px-3 py-2 text-xs text-github-muted">
                        {t('about.sections.devStatus.note')}
                    </div>
                </div>
            </Card>
        </div>
    )
}

export default About
