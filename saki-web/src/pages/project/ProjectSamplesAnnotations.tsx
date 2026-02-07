import React, {useCallback, useEffect, useState} from 'react';
import {Button, Card, Empty, Input, Pagination, Select, Space, Spin, Tag, Typography,} from 'antd';
import {useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {FileTextOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {Dataset, ProjectBranch, ProjectSample} from '../../types';
import {useProjectSampleList} from '../../hooks/project/useProjectSampleList';
import {useResourcePermission} from '../../hooks/permission/usePermission';
import CommitModal from '../../components/project/CommitModal';

const {Title, Text} = Typography;

const ProjectSamplesAnnotations: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [loadingMeta, setLoadingMeta] = useState(true);
    const [commitModalOpen, setCommitModalOpen] = useState(false);
    const [commitLoading, setCommitLoading] = useState(false);

    const {can: canProject} = useResourcePermission('project', projectId);
    const canCommit = canProject('commit:create:assigned');

    const selectedDatasetId = searchParams.get('datasetId') || '';
    const q = searchParams.get('q') || '';
    const status = (searchParams.get('status') || 'all') as 'all' | 'labeled' | 'unlabeled' | 'draft';
    const sortValue = searchParams.get('sort') || 'createdAt:desc';
    const branchName = searchParams.get('branch') || 'master';
    const page = Number(searchParams.get('page') || 1);
    const pageSize = Number(searchParams.get('pageSize') || 24);

    const [sortBy, sortOrder] = sortValue.split(':');
    const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId);

    const statusOptions = [
        {label: t('project.samples.filters.all'), value: 'all'},
        {label: t('project.samples.filters.labeled'), value: 'labeled'},
        {label: t('project.samples.filters.unlabeled'), value: 'unlabeled'},
        {label: t('project.samples.filters.draft'), value: 'draft'},
    ];

    const sortOptions = [
        {label: t('project.samples.sort.createdNewest'), value: 'createdAt:desc'},
        {label: t('project.samples.sort.createdOldest'), value: 'createdAt:asc'},
        {label: t('project.samples.sort.updatedNewest'), value: 'updatedAt:desc'},
        {label: t('project.samples.sort.updatedOldest'), value: 'updatedAt:asc'},
        {label: t('project.samples.sort.nameAZ'), value: 'name:asc'},
        {label: t('project.samples.sort.nameZA'), value: 'name:desc'},
    ];

    const {samples, meta, loading, reload} = useProjectSampleList({
        projectId,
        datasetId: selectedDatasetId || undefined,
        filters: {
            q: q || undefined,
            status,
            branchName,
            sortBy,
            sortOrder: sortOrder as 'asc' | 'desc',
            page,
            limit: pageSize,
        },
        enabled: !!projectId && !!selectedDatasetId,
    });

    useEffect(() => {
        if (!projectId) return;
        setLoadingMeta(true);
        Promise.all([
            api.getProjectDatasets(projectId),
            api.getProjectBranches(projectId),
        ])
            .then(async ([datasetIds, branchList]) => {
                const datasetResults = await Promise.all(
                    datasetIds.map((id) => api.getDataset(id))
                );
                const resolved = datasetResults.filter(Boolean) as Dataset[];
                setDatasets(resolved);
                setBranches(branchList || []);

                const datasetParam = searchParams.get('datasetId');
                if (resolved.length > 0 && (!datasetParam || !resolved.find((d) => d.id === datasetParam))) {
                    const next = new URLSearchParams(searchParams);
                    next.set('datasetId', resolved[0].id);
                    setSearchParams(next, {replace: true});
                }

                const branchParam = searchParams.get('branch');
                if (branchList.length > 0 && (!branchParam || !branchList.find((b) => b.name === branchParam))) {
                    const next = new URLSearchParams(searchParams);
                    next.set('branch', branchList.find(b => b.name === 'master')?.name || branchList[0].name);
                    setSearchParams(next, {replace: true});
                }
            })
            .finally(() => setLoadingMeta(false));
    }, [projectId]);

    const updateParams = useCallback((updates: Record<string, string | null>) => {
        const next = new URLSearchParams(searchParams);
        Object.entries(updates).forEach(([key, value]) => {
            if (value === null) {
                next.delete(key);
            } else {
                next.set(key, value);
            }
        });
        setSearchParams(next);
    }, [searchParams, setSearchParams]);

    const handleStartAnnotate = useCallback(async () => {
        if (!projectId || !selectedDatasetId) return;
        const response = await api.getProjectSamples(projectId, selectedDatasetId, {
            q: q || undefined,
            status,
            branchName,
            sortBy,
            sortOrder: sortOrder as 'asc' | 'desc',
            page: 1,
            limit: 1,
        });
        const firstSample = response.items?.[0];
        if (!firstSample) return;
        const nextParams = new URLSearchParams();
        nextParams.set('sampleId', firstSample.id);
        nextParams.set('branch', branchName);
        nextParams.set('q', q);
        nextParams.set('status', status);
        nextParams.set('sort', sortValue);
        nextParams.set('page', '1');
        nextParams.set('pageSize', String(pageSize));
        navigate(`/projects/${projectId}/workspace/${selectedDatasetId}?${nextParams.toString()}`);
    }, [projectId, selectedDatasetId, q, status, branchName, sortBy, sortOrder, sortValue, pageSize, navigate]);

    const handleSampleClick = useCallback((sample: ProjectSample) => {
        if (!projectId || !selectedDatasetId) return;
        const nextParams = new URLSearchParams();
        nextParams.set('sampleId', sample.id);
        nextParams.set('branch', branchName);
        nextParams.set('q', q);
        nextParams.set('status', status);
        nextParams.set('sort', sortValue);
        nextParams.set('page', String(page));
        nextParams.set('pageSize', String(pageSize));
        navigate(`/projects/${projectId}/workspace/${selectedDatasetId}?${nextParams.toString()}`);
    }, [projectId, selectedDatasetId, branchName, q, status, sortValue, page, pageSize, navigate]);

    const handleCommit = useCallback(async (message: string) => {
        if (!projectId) return;
        setCommitLoading(true);
        try {
            await api.commitAnnotationDrafts(projectId, {
                branchName,
                commitMessage: message,
            });
            setCommitModalOpen(false);
            reload();
        } finally {
            setCommitLoading(false);
        }
    }, [projectId, branchName, reload]);

    return (
        <div className="flex h-full flex-col gap-4">
            <Card className="!border-github-border !bg-github-panel">
                <div className="flex flex-wrap items-center gap-3">
                    <Select
                        value={selectedDatasetId || undefined}
                        placeholder={t('project.samples.filters.datasetPlaceholder')}
                        className="min-w-[200px]"
                        onChange={(value) => updateParams({datasetId: value, page: '1'})}
                        loading={loadingMeta}
                    >
                        {datasets.map((dataset) => (
                            <Select.Option key={dataset.id} value={dataset.id}>
                                {dataset.name}
                            </Select.Option>
                        ))}
                    </Select>

                    <Input.Search
                        allowClear
                        placeholder={t('project.samples.filters.searchPlaceholder')}
                        value={q}
                        onChange={(e) => updateParams({q: e.target.value || null, page: '1'})}
                        className="min-w-[220px]"
                    />

                    <Select
                        value={status}
                        onChange={(value) => updateParams({status: value, page: '1'})}
                        options={statusOptions}
                        className="min-w-[140px]"
                    />

                    <Select
                        value={sortValue}
                        onChange={(value) => updateParams({sort: value, page: '1'})}
                        options={sortOptions}
                        className="min-w-[200px]"
                    />

                    <Select
                        value={branchName}
                        onChange={(value) => updateParams({branch: value, page: '1'})}
                        className="min-w-[160px]"
                        placeholder={t('project.samples.filters.branchPlaceholder')}
                    >
                        {branches.map((branch) => (
                            <Select.Option key={branch.id} value={branch.name}>
                                {branch.name}
                            </Select.Option>
                        ))}
                    </Select>

                    <div className="flex-1"/>

                    <Space>
                        <Button type="primary" onClick={handleStartAnnotate} disabled={!selectedDatasetId}>
                            Start Annotating
                        </Button>
                        <Button
                            onClick={() => setCommitModalOpen(true)}
                            disabled={!canCommit}
                        >
                            {t('project.samples.commitDrafts')}
                        </Button>
                    </Space>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel flex-1">
                {loadingMeta ? (
                    <div className="flex h-full items-center justify-center">
                        <Spin/>
                    </div>
                ) : !selectedDataset ? (
                    <Empty description={t('project.samples.emptySelectDataset')}/>
                ) : loading ? (
                    <div className="flex h-full items-center justify-center">
                        <Spin/>
                    </div>
                ) : samples.length === 0 ? (
                    <div className="flex h-full flex-col items-center justify-center gap-2 py-12">
                        <FileTextOutlined className="text-4xl text-gray-300"/>
                        <Title level={5} className="!m-0">{t('project.samples.emptyTitle')}</Title>
                        <Text type="secondary">{t('project.samples.emptyHint')}</Text>
                    </div>
                ) : (
                    <div>
                        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                            {samples.map((sample) => (
                                <Card
                                    key={sample.id}
                                    hoverable
                                    onClick={() => handleSampleClick(sample)}
                                    cover={
                                        sample.primaryAssetUrl ? (
                                            <img
                                                alt={sample.name}
                                                src={sample.primaryAssetUrl}
                                                className="h-[150px] w-full object-cover"
                                                onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                                                    e.currentTarget.style.display = 'none';
                                                }}
                                            />
                                        ) : null
                                    }
                                >
                                    <Card.Meta
                                        title={<span className="block truncate">{sample.name}</span>}
                                        description={sample.remark || 'No remark'}
                                    />
                                    <div className="mt-3 flex flex-wrap gap-2">
                                        {sample.hasDraft ? <Tag color="orange">{t('project.samples.filters.draft')}</Tag> : null}
                                        {sample.isLabeled
                                            ? <Tag color="green">{t('project.samples.filters.labeled')}</Tag>
                                            : <Tag>{t('project.samples.filters.unlabeled')}</Tag>}
                                        <Tag>{sample.annotationCount} anns</Tag>
                                    </div>
                                </Card>
                            ))}
                        </div>
                        <div className="mt-4 flex items-center justify-between">
                            <Text type="secondary">
                                Page {Math.floor(meta.offset / (meta.limit || 1)) + 1} / {Math.max(1, Math.ceil(meta.total / (meta.limit || 1)))} · {meta.total} items
                            </Text>
                            <Pagination
                                current={page}
                                total={meta.total}
                                pageSize={pageSize}
                                showSizeChanger
                                onChange={(nextPage, nextSize) => {
                                    updateParams({
                                        page: String(nextPage),
                                        pageSize: String(nextSize),
                                    });
                                }}
                            />
                        </div>
                    </div>
                )}
            </Card>

            <CommitModal
                open={commitModalOpen}
                onCancel={() => setCommitModalOpen(false)}
                onCommit={handleCommit}
                loading={commitLoading}
            />
        </div>
    );
};

export default ProjectSamplesAnnotations;
