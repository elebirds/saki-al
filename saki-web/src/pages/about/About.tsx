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
                        <p className="text-sm text-github-muted">
                            {t('app.about')} · {t('about.hero.subtitle')}
                        </p>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        <Tag color="blue">{t('about.hero.tags.humanLoop')}</Tag>
                        <Tag color="green">{t('about.hero.tags.gitLike')}</Tag>
                        <Tag color="purple">{t('about.hero.tags.activeLoop')}</Tag>
                    </div>
                </div>
                <p className="mt-4 text-sm text-github-text">
                    {t('about.hero.description1')}
                    {t('about.hero.description2')}
                </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <DatabaseOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.dataAssets.title')}
                        </h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        {t('about.sections.dataAssets.body')}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="geekblue">{t('about.sections.dataAssets.tags.assetSha')}</Tag>
                        <Tag color="geekblue">{t('about.sections.dataAssets.tags.datasetSample')}</Tag>
                        <Tag color="geekblue">{t('about.sections.dataAssets.tags.minio')}</Tag>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <BranchesOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.annotationVersioning.title')}
                        </h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        {t('about.sections.annotationVersioning.body')}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="purple">{t('about.sections.annotationVersioning.tags.annotation')}</Tag>
                        <Tag color="purple">{t('about.sections.annotationVersioning.tags.commitMap')}</Tag>
                        <Tag color="purple">{t('about.sections.annotationVersioning.tags.branch')}</Tag>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <ExperimentOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.training.title')}
                        </h3>
                    </div>
                    <p className="mt-2 text-sm text-github-muted">
                        {t('about.sections.training.body')}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Tag color="green">{t('about.sections.training.tags.alLoop')}</Tag>
                        <Tag color="green">{t('about.sections.training.tags.jobMetric')}</Tag>
                        <Tag color="green">{t('about.sections.training.tags.model')}</Tag>
                    </div>
                </Card>
            </div>

            <Card className={cardClassName}>
                <div className="flex items-center gap-2">
                    <SyncOutlined className="text-github-accent"/>
                    <h3 className="text-base font-semibold text-github-text">
                        {t('about.sections.coreWorkflow.title')}
                    </h3>
                </div>
                <Divider className="!my-4"/>
                <Steps
                    size="small"
                    items={[
                        {title: t('about.sections.coreWorkflow.steps.dataImport')},
                        {title: t('about.sections.coreWorkflow.steps.sampleAnnotation')},
                        {title: t('about.sections.coreWorkflow.steps.versionSnapshot')},
                        {title: t('about.sections.coreWorkflow.steps.modelTraining')},
                        {title: t('about.sections.coreWorkflow.steps.activeSampling')},
                        {title: t('about.sections.coreWorkflow.steps.iteration')},
                    ]}
                />
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <ApiOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.techStack.title')}
                        </h3>
                    </div>
                    <div className="mt-3 space-y-2 text-sm text-github-muted">
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="blue">{t('about.sections.techStack.frontend.label')}</Tag>
                            <span>{t('about.sections.techStack.frontend.stack')}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="green">{t('about.sections.techStack.backend.label')}</Tag>
                            <span>{t('about.sections.techStack.backend.stack')}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color="purple">{t('about.sections.techStack.runtime.label')}</Tag>
                            <span>{t('about.sections.techStack.runtime.stack')}</span>
                        </div>
                    </div>
                </Card>

                <Card className={cardClassName}>
                    <div className="flex items-center gap-2">
                        <CloudServerOutlined className="text-github-accent"/>
                        <h3 className="text-base font-semibold text-github-text">
                            {t('about.sections.devStatus.title')}
                        </h3>
                    </div>
                    <div className="mt-4 grid gap-3 text-sm">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <CheckCircleOutlined className="text-github-success"/>
                                <span>saki-api L1</span>
                            </div>
                            <Tag color="green">{t('about.sections.devStatus.status.completed')}</Tag>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <EyeOutlined className="text-github-accent"/>
                                <span>saki-api L2</span>
                            </div>
                            <Tag color="orange">{t('about.sections.devStatus.status.inProgress')}</Tag>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-github-text">
                                <EyeOutlined className="text-github-muted"/>
                                <span>saki-runtime</span>
                            </div>
                            <Tag color="default">{t('about.sections.devStatus.status.planned')}</Tag>
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    )
}

export default About
