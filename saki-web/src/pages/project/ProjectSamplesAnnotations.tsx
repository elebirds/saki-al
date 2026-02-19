import React, {useCallback, useEffect, useState} from 'react';
import {Button, Card, Empty, Input, message, Segmented, Select, Spin, Tag, Tooltip, Typography,} from 'antd';
import {useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {
    CloudUploadOutlined,
    DatabaseOutlined,
    FileSearchOutlined,
    FileTextOutlined,
    FilterOutlined,
    PartitionOutlined,
    PlayCircleOutlined,
    SaveOutlined,
    SortAscendingOutlined,
} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {Dataset, ProjectBranch, ProjectSample} from '../../types';
import {useResourcePermission} from '../../hooks/permission/usePermission';
import CommitModal from '../../components/project/CommitModal';
import {PaginatedList} from '../../components/common/PaginatedList';
import {createEmptyPaginationResponse} from '../../types/pagination';
import {parseProjectSampleSort} from '../../utils/projectSampleSort';

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
    const canAnnotate = canProject('annotation:create:assigned');

    const selectedDatasetId = searchParams.get('datasetId') || '';
    const q = searchParams.get('q') || '';
    const status = (searchParams.get('status') || 'all') as 'all' | 'labeled' | 'unlabeled' | 'draft';
    const parsedSort = parseProjectSampleSort(searchParams.get('sort'));
    const sortValue = parsedSort.sortValue;
    const branchName = searchParams.get('branch') || 'master';
    const page = Number(searchParams.get('page') || 1);
    const pageSize = Number(searchParams.get('pageSize') || 24);

    const sortBy = parsedSort.sortBy;
    const sortOrder = parsedSort.sortOrder;
    const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId);
    const selectedBranch = branches.find((branch) => branch.name === branchName);
    const [samplesRefreshToken, setSamplesRefreshToken] = useState(0);
    const [sampleMeta, setSampleMeta] = useState({
        total: 0,
        limit: pageSize,
        offset: (page - 1) * pageSize,
        size: 0,
    });

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

    useEffect(() => {
        if (!projectId) return;
        setLoadingMeta(true);
        Promise.all([
            api.getProjectDatasetDetails(projectId),
            api.getProjectBranches(projectId),
        ])
            .then(([resolved, branchList]) => {
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

    useEffect(() => {
        setSampleMeta((prev) => ({
            ...prev,
            limit: pageSize,
            offset: (page - 1) * pageSize,
        }));
    }, [page, pageSize]);

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
        if (!canAnnotate) {
            message.warning(t('common.noPermission'));
            return;
        }
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
    }, [canAnnotate, projectId, selectedDatasetId, q, status, branchName, sortBy, sortOrder, sortValue, pageSize, navigate, t]);

    const handleSampleClick = useCallback((sample: ProjectSample) => {
        if (!canAnnotate) {
            message.warning(t('common.noPermission'));
            return;
        }
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
    }, [canAnnotate, projectId, selectedDatasetId, branchName, q, status, sortValue, page, pageSize, navigate, t]);

    const handleCommit = useCallback(async (message: string) => {
        if (!projectId) return;
        setCommitLoading(true);
        try {
            await api.commitAnnotationDrafts(projectId, {
                branchName,
                commitMessage: message,
            });
            setCommitModalOpen(false);
            setSamplesRefreshToken((value) => value + 1);
        } finally {
            setCommitLoading(false);
        }
    }, [projectId, branchName]);

    const fetchSamples = useCallback(async (nextPage: number, nextPageSize: number) => {
        if (!projectId || !selectedDatasetId) {
            return createEmptyPaginationResponse<ProjectSample>(nextPageSize, nextPage);
        }
        return await api.getProjectSamples(projectId, selectedDatasetId, {
            q: q || undefined,
            status,
            branchName,
            sortBy,
            sortOrder: sortOrder as 'asc' | 'desc',
            page: nextPage,
            limit: nextPageSize,
        });
    }, [projectId, selectedDatasetId, q, status, branchName, sortBy, sortOrder]);

    const totalSamplePages = Math.max(1, Math.ceil(sampleMeta.total / (sampleMeta.limit || 1)));

    return (
        <div className="flex h-full min-w-0 flex-col gap-4 overflow-x-hidden">
            <Card className="relative overflow-hidden !border-github-border !bg-github-panel">
                <div
                    className="pointer-events-none absolute inset-0 opacity-80"
                    style={{
                        background: 'radial-gradient(1200px 280px at -5% -20%, rgba(56, 139, 253, 0.16), transparent 62%), radial-gradient(700px 240px at 90% 0%, rgba(47, 129, 247, 0.10), transparent 70%)',
                    }}
                />
                <div className="relative flex flex-col gap-3">
                    <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                        <div className="flex min-w-0 items-center gap-2">
                            <span className="flex items-center gap-1 text-xs text-github-muted">
                                <DatabaseOutlined/>
                                {t('project.samples.datasetLabel')}
                            </span>
                            <Select
                                value={selectedDatasetId || undefined}
                                placeholder={t('project.samples.filters.datasetPlaceholder')}
                                className="w-[210px] shrink-0"
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
                                className="min-w-[220px] flex-1"
                                prefix={<FileSearchOutlined className="text-github-muted"/>}
                            />
                        </div>

                        <div className="flex items-center gap-2 lg:justify-end">
                            <Button
                                type="default"
                                icon={<CloudUploadOutlined/>}
                                onClick={() => navigate(`/projects/${projectId}/import`)}
                                disabled={!canAnnotate || !canCommit}
                            >
                                {t('import.project.entry')}
                            </Button>
                            {canAnnotate ? (
                                <Button
                                    type="primary"
                                    icon={<PlayCircleOutlined/>}
                                    onClick={handleStartAnnotate}
                                    disabled={!selectedDatasetId}
                                >
                                    {t('project.samples.startAnnotating')}
                                </Button>
                            ) : (
                                <Tooltip title={t('common.noPermission')}>
                                    <Button type="primary" icon={<PlayCircleOutlined/>} disabled>
                                        {t('project.samples.startAnnotating')}
                                    </Button>
                                </Tooltip>
                            )}
                            <Button
                                onClick={() => setCommitModalOpen(true)}
                                disabled={!canCommit}
                                icon={<SaveOutlined/>}
                            >
                                {t('project.samples.commitDrafts')}
                            </Button>
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        <span className="flex items-center gap-1 text-xs text-github-muted">
                            <FilterOutlined/>
                            {t('project.samples.filterLabel')}
                        </span>
                        <Segmented
                            options={statusOptions}
                            value={status}
                            onChange={(value) => updateParams({status: String(value), page: '1'})}
                        />

                        <span className="ml-2 flex items-center gap-1 text-xs text-github-muted">
                            <PartitionOutlined/>
                            {t('project.samples.branchLabel')}
                        </span>
                        <Select
                            value={branchName}
                            onChange={(value) => updateParams({branch: value, page: '1'})}
                            className="w-[150px]"
                            placeholder={t('project.samples.filters.branchPlaceholder')}
                        >
                            {branches.map((branch) => (
                                <Select.Option key={branch.id} value={branch.name}>
                                    {branch.name}
                                </Select.Option>
                            ))}
                        </Select>

                        <span className="flex items-center gap-1 text-xs text-github-muted">
                            <SortAscendingOutlined/>
                            {t('project.samples.sortLabel')}
                        </span>
                        <Select
                            value={sortValue}
                            onChange={(value) => updateParams({sort: value, page: '1'})}
                            options={sortOptions}
                            className="w-[200px]"
                        />

                        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-github-muted">
                            {selectedDataset ? <Tag color="blue">{selectedDataset.name}</Tag> : null}
                            {selectedBranch ? <Tag color="geekblue">{selectedBranch.name}</Tag> : null}
                            <span>{t('project.samples.resultHint', {count: sampleMeta.total})}</span>
                        </div>
                    </div>
                </div>
            </Card>

            <Card className="!border-github-border !bg-github-panel flex-1 min-w-0">
                {loadingMeta ? (
                    <div className="flex h-full items-center justify-center">
                        <Spin/>
                    </div>
                ) : !selectedDataset ? (
                    <Empty description={t('project.samples.emptySelectDataset')}/>
                ) : (
                    <PaginatedList<ProjectSample>
                        fetchData={fetchSamples}
                        enabled={!!projectId && !!selectedDatasetId}
                        controlledPage={page}
                        controlledPageSize={pageSize}
                        adaptivePageSize={{
                            enabled: true,
                            mode: 'grid',
                            itemMinWidth: 260,
                            itemHeight: 270,
                            rowGap: 16,
                            colGap: 16,
                        }}
                        onPageChange={(nextPage, nextSize) => {
                            updateParams({
                                page: String(nextPage),
                                pageSize: String(nextSize),
                            });
                        }}
                        refreshKey={`${projectId || ''}:${selectedDatasetId}:${q}:${status}:${branchName}:${sortValue}:${samplesRefreshToken}`}
                        onMetaChange={(nextMeta) => setSampleMeta(nextMeta)}
                        renderItems={(items) =>
                            items.length === 0 ? (
                                <div className="flex h-full flex-col items-center justify-center gap-2 py-12">
                                    <FileTextOutlined className="text-4xl text-gray-300"/>
                                    <Title level={5} className="!m-0">{t('project.samples.emptyTitle')}</Title>
                                    <Text type="secondary">{t('project.samples.emptyHint')}</Text>
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                                    {items.map((sample) => (
                                        <Card
                                            key={sample.id}
                                            hoverable={canAnnotate}
                                            onClick={() => handleSampleClick(sample)}
                                            className={canAnnotate ? 'cursor-pointer' : 'cursor-not-allowed opacity-80'}
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
                                                title={
                                                    <Tooltip title={sample.name} placement="topLeft">
                                                        <span className="block truncate" title={sample.name}>{sample.name}</span>
                                                    </Tooltip>
                                                }
                                                description={sample.remark || t('project.samples.noRemark')}
                                            />
                                            <div className="mt-3 flex flex-wrap gap-2">
                                                {sample.hasDraft ? <Tag color="orange">{t('project.samples.filters.draft')}</Tag> : null}
                                                {sample.isLabeled
                                                    ? <Tag color="green">{t('project.samples.filters.labeled')}</Tag>
                                                    : <Tag>{t('project.samples.filters.unlabeled')}</Tag>}
                                                <Tag>{t('project.samples.annotationCountShort', {count: sample.annotationCount})}</Tag>
                                            </div>
                                        </Card>
                                    ))}
                                </div>
                            )
                        }
                        renderPaginationWrapper={(node) => (
                            <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                                <Text type="secondary">
                                    {t('project.samples.pageStatus', {
                                        page: Math.floor(sampleMeta.offset / (sampleMeta.limit || 1)) + 1,
                                        totalPages: totalSamplePages,
                                        total: sampleMeta.total,
                                    })}
                                </Text>
                                {node}
                            </div>
                        )}
                        paginationProps={{
                            showTotal: (tot, range) =>
                                range
                                    ? t('common.pagination.range', {start: range[0], end: range[1], total: tot})
                                    : t('common.pagination.total', {total: tot}),
                        }}
                    />
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
