import React from 'react'
import {Card} from 'antd'
import {useTranslation} from 'react-i18next'

const ProjectInsights: React.FC = () => {
    const {t} = useTranslation()
    return (
        <Card className="!border-github-border !bg-github-panel">
            <div className="text-sm text-github-muted">{t('project.insights.comingSoon')}</div>
        </Card>
    )
}

export default ProjectInsights
