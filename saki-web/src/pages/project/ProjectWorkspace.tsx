import React, {useEffect, useState} from 'react';
import {Spin} from 'antd';
import {useParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {
    Dataset,
    DEFAULT_DETECTION_ANNOTATION_TYPES,
    DetectionAnnotationType,
    isDetectionAnnotationType,
} from '../../types';
import ProjectClassicWorkspace from '../annotation/ProjectClassicWorkspace';
import ProjectFedoWorkspace from '../annotation/ProjectFedoWorkspace';

const ProjectWorkspace: React.FC = () => {
    const {t} = useTranslation();
    const {projectId, datasetId} = useParams<{ projectId: string; datasetId: string }>();
    const [dataset, setDataset] = useState<Dataset | null>(null);
    const [enabledAnnotationTypes, setEnabledAnnotationTypes] = useState<DetectionAnnotationType[]>(
        DEFAULT_DETECTION_ANNOTATION_TYPES
    );
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!projectId || !datasetId) return;
        setLoading(true);
        Promise.all([
            api.getProject(projectId),
            api.getProjectDatasetDetails(projectId),
        ])
            .then(([project, items]) => {
                const enabled = (project.enabledAnnotationTypes || DEFAULT_DETECTION_ANNOTATION_TYPES)
                    .filter((item): item is DetectionAnnotationType => isDetectionAnnotationType(item));
                setEnabledAnnotationTypes(
                    enabled.length > 0 ? enabled : DEFAULT_DETECTION_ANNOTATION_TYPES
                );
                setDataset(items.find((item) => item.id === datasetId) || null);
            })
            .catch(() => {
                setEnabledAnnotationTypes(DEFAULT_DETECTION_ANNOTATION_TYPES);
                setDataset(null);
            })
            .finally(() => setLoading(false));
    }, [projectId, datasetId]);

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        );
    }

    if (!dataset) {
        return <div className="text-github-muted">{t('dataset.detail.notFound')}</div>;
    }

    return dataset.type === 'fedo' ? (
        <ProjectFedoWorkspace dataset={dataset} enabledAnnotationTypes={enabledAnnotationTypes}/>
    ) : (
        <ProjectClassicWorkspace dataset={dataset} enabledAnnotationTypes={enabledAnnotationTypes}/>
    );
};

export default ProjectWorkspace;
