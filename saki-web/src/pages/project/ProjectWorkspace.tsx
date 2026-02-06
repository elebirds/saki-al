import React, {useEffect, useState} from 'react';
import {Spin} from 'antd';
import {useParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {Dataset} from '../../types';
import ProjectClassicWorkspace from '../annotation/ProjectClassicWorkspace';
import ProjectFedoWorkspace from '../annotation/ProjectFedoWorkspace';

const ProjectWorkspace: React.FC = () => {
    const {t} = useTranslation();
    const {datasetId} = useParams<{ datasetId: string }>();
    const [dataset, setDataset] = useState<Dataset | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!datasetId) return;
        setLoading(true);
        api.getDataset(datasetId)
            .then((ds) => setDataset(ds || null))
            .finally(() => setLoading(false));
    }, [datasetId]);

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
        <ProjectFedoWorkspace dataset={dataset}/>
    ) : (
        <ProjectClassicWorkspace dataset={dataset}/>
    );
};

export default ProjectWorkspace;
