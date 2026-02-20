import React, {useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Checkbox,
    Descriptions,
    Drawer,
    Input,
    List,
    Pagination,
    Progress,
    Radio,
    Select,
    Space,
    Steps,
    Tabs,
    Tag,
    Typography,
    Upload,
    message,
} from 'antd';
import VirtualList from 'rc-virtual-list';
import {
    ArrowLeftOutlined,
    CheckCircleOutlined,
    ClockCircleOutlined,
    ExclamationCircleOutlined,
    PlayCircleOutlined,
    QuestionCircleOutlined,
    UploadOutlined,
} from '@ant-design/icons';
import {useNavigate, useParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {
    Dataset,
    ImportDryRunResponse,
    ProjectBranch,
    type ImportFormat,
    type ImportProgressEventType,
    type FormatProfileCapability,
} from '../../types';
import {useImportTask, useResourcePermission} from '../../hooks';
import {localizeImportIssueMessage} from '../../utils/importIssue';
import {
    formatImportSummaryValue,
    getOrderedImportSummaryEntries,
    localizeImportSummaryKey,
} from '../../utils/importSummary';

const {Title, Text, Paragraph} = Typography;
const {Dragger} = Upload;

type ProjectImportMode = 'images' | 'annotations' | 'associated';
type ImportWorkspaceScope = 'project' | 'dataset';
type DatasetImportSourceMode = 'zip' | 'files';
type PreviewDetailTabKey = 'warnings' | 'errors' | 'labels';
type YoloObbLabelFormat = 'obb_rbox' | 'obb_poly8';
const EVENT_ROW_HEIGHT = 76;
const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, {numeric: 'auto'});

interface ProjectImportWorkspaceProps {
    scope?: ImportWorkspaceScope;
}

interface DryRunFailureState {
    message: string;
    statusCode?: number;
    appCode?: string | number;
    timestamp?: string;
    raw?: unknown;
}

const eventTagColorMap: Record<ImportProgressEventType, string> = {
    start: 'blue',
    phase: 'gold',
    item: 'default',
    annotation: 'geekblue',
    warning: 'orange',
    error: 'red',
    complete: 'green',
};

function formatProfileLabel(profileId: ImportFormat): string {
    if (profileId === 'coco') return 'COCO';
    if (profileId === 'voc') return 'VOC';
    if (profileId === 'yolo') return 'YOLO';
    return 'YOLO OBB';
}

function formatGlossaryKey(profileId: ImportFormat): string {
    if (profileId === 'coco') return 'formatCoco';
    if (profileId === 'voc') return 'formatVoc';
    if (profileId === 'yolo') return 'formatYolo';
    return 'formatYoloObb';
}

function compareByName(left: string, right: string): number {
    return left.localeCompare(right, undefined, {numeric: true, sensitivity: 'base'});
}

function sortDatasets(list: Dataset[]): Dataset[] {
    return [...list].sort((left, right) => compareByName(left.name, right.name));
}

function sortBranches(list: ProjectBranch[]): ProjectBranch[] {
    return [...list].sort((left, right) => {
        if (left.name === right.name) return 0;
        if (left.name === 'master') return -1;
        if (right.name === 'master') return 1;
        return compareByName(left.name, right.name);
    });
}

function buildFileIdentity(file: Pick<File, 'name' | 'size' | 'lastModified'>): string {
    return `${file.name}|${file.size}|${file.lastModified}`;
}

function buildDryRunFailureState(error: unknown, fallback: string): DryRunFailureState {
    if (!(error instanceof Error)) {
        return {message: fallback};
    }
    const known = error as Error & { statusCode?: number; originalError?: any };
    const raw = known.originalError?.response?.data;
    let message = known.message || fallback;
    let appCode: string | number | undefined;
    let timestamp: string | undefined;
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        const payload = raw as Record<string, unknown>;
        const payloadMessage = typeof payload.message === 'string' ? payload.message : undefined;
        if (payloadMessage?.trim()) {
            message = payloadMessage;
        }
        if (typeof payload.code === 'number' || typeof payload.code === 'string') {
            appCode = payload.code;
        }
        if (typeof payload.timestamp === 'string') {
            timestamp = payload.timestamp;
        }
    }
    return {
        message,
        statusCode: known.statusCode,
        appCode,
        timestamp,
        raw,
    };
}

function formatClock(iso?: string): string {
    if (!iso) return '-';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleTimeString([], {hour12: false});
}

function formatRelative(iso?: string, nowMs: number = Date.now()): string {
    if (!iso) return '-';
    const date = new Date(iso);
    const target = date.getTime();
    if (Number.isNaN(target)) return '-';
    const diffSeconds = Math.round((target - nowMs) / 1000);
    const absSeconds = Math.abs(diffSeconds);
    if (absSeconds < 60) return relativeTimeFormatter.format(diffSeconds, 'second');
    if (absSeconds < 3600) return relativeTimeFormatter.format(Math.round(diffSeconds / 60), 'minute');
    if (absSeconds < 86400) return relativeTimeFormatter.format(Math.round(diffSeconds / 3600), 'hour');
    return relativeTimeFormatter.format(Math.round(diffSeconds / 86400), 'day');
}

function formatDualTime(iso?: string, nowMs: number = Date.now()): string {
    const absolute = formatClock(iso);
    if (absolute === '-') return '-';
    const relative = formatRelative(iso, nowMs);
    if (relative === '-') return absolute;
    return `${relative} · ${absolute}`;
}

function formatElapsed(startIso?: string, endIso?: string): string {
    if (!startIso) return '-';
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '-';
    const seconds = Math.floor((end - start) / 1000);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours > 0) {
        return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

const ProjectImportWorkspace: React.FC<ProjectImportWorkspaceProps> = ({scope}) => {
    const {t} = useTranslation();
    const {projectId, id: datasetIdFromRoute} = useParams<{ projectId?: string; id?: string }>();
    const navigate = useNavigate();
    const resolvedScope: ImportWorkspaceScope = scope || (projectId ? 'project' : 'dataset');
    const isProjectScope = resolvedScope === 'project';
    const isDatasetScope = resolvedScope === 'dataset';

    const {can: canProject} = useResourcePermission('project', projectId);
    const {can: canDataset} = useResourcePermission('dataset', datasetIdFromRoute);
    const canAnnotate = canProject('annotation:create:assigned');
    const canCommit = canProject('commit:create:assigned');
    const canDatasetImport = canDataset('dataset:import:assigned');
    const canSampleCreate = canDataset('sample:create:assigned');

    const [mode, setMode] = useState<ProjectImportMode>('annotations');
    const [sourceMode, setSourceMode] = useState<DatasetImportSourceMode>('zip');
    const [archive, setArchive] = useState<File | null>(null);
    const [imageFiles, setImageFiles] = useState<File[]>([]);
    const [formatProfile, setFormatProfile] = useState<ImportFormat>('yolo');
    const [yoloObbLabelFormat, setYoloObbLabelFormat] = useState<YoloObbLabelFormat>('obb_rbox');
    const [branchName, setBranchName] = useState('master');
    const [targetDatasetId, setTargetDatasetId] = useState<string>('');
    const [associatedTargetMode, setAssociatedTargetMode] = useState<'existing' | 'new'>('existing');
    const [newDatasetName, setNewDatasetName] = useState('');
    const [newDatasetDescription, setNewDatasetDescription] = useState('');
    const [conflictStrategy, setConflictStrategy] = useState<'replace' | 'merge'>('replace');

    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [datasetInfo, setDatasetInfo] = useState<Dataset | null>(null);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [importProfiles, setImportProfiles] = useState<FormatProfileCapability[]>([]);
    const [dryRun, setDryRun] = useState<ImportDryRunResponse | null>(null);
    const [dryRunFailure, setDryRunFailure] = useState<DryRunFailureState | null>(null);
    const [confirmCreateLabels, setConfirmCreateLabels] = useState(false);
    const [dryRunLoading, setDryRunLoading] = useState(false);
    const [helpOpen, setHelpOpen] = useState(false);
    const [rightPanelTab, setRightPanelTab] = useState<'preview' | 'execution'>('preview');
    const [previewDetailTab, setPreviewDetailTab] = useState<PreviewDetailTabKey>('warnings');
    const [previewPager, setPreviewPager] = useState<Record<PreviewDetailTabKey, { current: number; pageSize: number }>>({
        warnings: {current: 1, pageSize: 20},
        errors: {current: 1, pageSize: 20},
        labels: {current: 1, pageSize: 20},
    });
    const [nowMs, setNowMs] = useState(() => Date.now());

    const importTask = useImportTask({
        onError: (err) => message.error(err),
    });

    useEffect(() => {
        if (isProjectScope) {
            if (!projectId) return;
            Promise.all([
                api.getProjectDatasetDetails(projectId),
                api.getProjectBranches(projectId),
                api.getProjectIOCapabilities(projectId),
            ]).then(([datasetList, branchList, capabilities]) => {
                const sortedDatasets = sortDatasets(datasetList || []);
                const sortedBranches = sortBranches(branchList || []);
                setDatasetInfo(null);
                setDatasets(sortedDatasets);
                setBranches(sortedBranches);
                const profiles = capabilities.importProfiles || [];
                setImportProfiles(profiles);
                if (sortedDatasets.length > 0 && !targetDatasetId) {
                    setTargetDatasetId(sortedDatasets[0].id);
                }
                if (sortedBranches.length > 0) {
                    setBranchName(sortedBranches[0].name);
                }
                const availableProfiles = profiles
                    .filter((profile) => profile.available)
                    .map((profile) => profile.id);
                if (availableProfiles.length > 0) {
                    setFormatProfile((prev) => (
                        availableProfiles.includes(prev) ? prev : (availableProfiles[0] as ImportFormat)
                    ));
                }
            }).catch((error) => {
                const msg = error instanceof Error ? error.message : t('import.workspace.metaLoadError');
                message.error(msg);
            });
            return;
        }
        if (!datasetIdFromRoute) return;
        api.getDataset(datasetIdFromRoute)
            .then((dataset) => {
                if (!dataset) return;
                setDatasetInfo(dataset);
                setDatasets([dataset]);
                setBranches([]);
                setImportProfiles([]);
                setTargetDatasetId(dataset.id);
            })
            .catch((error) => {
                const msg = error instanceof Error ? error.message : t('import.workspace.metaLoadError');
                message.error(msg);
            });
    }, [datasetIdFromRoute, isProjectScope, projectId, t, targetDatasetId]);

    useEffect(() => {
        setNowMs(Date.now());
        if (!importTask.isRunning) {
            return;
        }
        const timer = window.setInterval(() => {
            setNowMs(Date.now());
        }, 1000);
        return () => window.clearInterval(timer);
    }, [importTask.isRunning]);

    useEffect(() => {
        if (!isDatasetScope) return;
        setMode('images');
        setAssociatedTargetMode('existing');
    }, [isDatasetScope]);

    useEffect(() => {
        if (!isDatasetScope) return;
        setArchive(null);
    }, [isDatasetScope, sourceMode]);

    useEffect(() => {
        setDryRun(null);
        setDryRunFailure(null);
        setConfirmCreateLabels(false);
        setImageFiles([]);
        importTask.reset();
        setRightPanelTab('preview');
        setPreviewDetailTab('warnings');
        setPreviewPager({
            warnings: {current: 1, pageSize: 20},
            errors: {current: 1, pageSize: 20},
            labels: {current: 1, pageSize: 20},
        });
    }, [mode, formatProfile, yoloObbLabelFormat, branchName, targetDatasetId, associatedTargetMode, newDatasetName, newDatasetDescription, conflictStrategy, sourceMode]);

    const summaryEntries = useMemo(
        () => getOrderedImportSummaryEntries(dryRun?.summary).map(([key, value]) => ({
            key,
            label: localizeImportSummaryKey(t, key),
            value: formatImportSummaryValue(t, key, value),
        })),
        [dryRun, t],
    );
    const requiresProjectWritePermission = isProjectScope && mode !== 'images';
    const hasDatasetModePermission = sourceMode === 'zip' ? canDatasetImport : canSampleCreate;
    const blockedByUnsupportedAnnotationType = useMemo(
        () => Boolean(dryRun?.errors.some((item) => item.code === 'ANNOTATION_TYPE_NOT_ENABLED')),
        [dryRun],
    );
    const canExecute = useMemo(() => {
        if (isDatasetScope && sourceMode === 'files') {
            return imageFiles.length > 0;
        }
        return Boolean(
            dryRun
            && !blockedByUnsupportedAnnotationType
            && (!dryRun.plannedNewLabels.length || confirmCreateLabels),
        );
    }, [blockedByUnsupportedAnnotationType, confirmCreateLabels, dryRun, imageFiles.length, isDatasetScope, sourceMode]);
    const previewCounts = useMemo(() => ({
        warnings: dryRun?.warnings.length || 0,
        errors: dryRun?.errors.length || 0,
        labels: dryRun?.plannedNewLabels.length || 0,
    }), [dryRun]);
    const executionEvents = useMemo(
        () => [...importTask.state.events].reverse(),
        [importTask.state.events],
    );
    const executionStartedAt = importTask.state.events[0]?.receivedAt;
    const executionLastEventAt = importTask.state.events[importTask.state.events.length - 1]?.receivedAt;
    const executionElapsed = useMemo(
        () => formatElapsed(
            executionStartedAt,
            importTask.isRunning ? new Date(nowMs).toISOString() : executionLastEventAt,
        ),
        [executionLastEventAt, executionStartedAt, importTask.isRunning, nowMs],
    );

    const modeCards = useMemo(() => ([
        {
            value: 'annotations' as const,
            title: t('import.project.mode.annotationsOnly'),
            description: t('import.project.mode.annotationsOnlyDesc'),
        },
        {
            value: 'associated' as const,
            title: t('import.project.mode.associated'),
            description: t('import.project.mode.associatedDesc'),
        },
        {
            value: 'images' as const,
            title: t('import.project.mode.imagesOnly'),
            description: t('import.project.mode.imagesOnlyDesc'),
        },
    ]), [t]);

    const formatOptions = useMemo(
        () => importProfiles
            .filter((profile) => profile.available)
            .map((profile) => ({
                label: formatProfileLabel(profile.id as ImportFormat),
                value: profile.id as ImportFormat,
            })),
        [importProfiles],
    );
    const hasAvailableImportProfile = formatOptions.length > 0;

    const datasetOptions = useMemo(
        () => datasets.map((dataset) => ({label: dataset.name, value: dataset.id})),
        [datasets],
    );
    const selectedTargetDataset = useMemo(() => {
        if (isDatasetScope) {
            return datasetInfo || datasets.find((item) => item.id === targetDatasetId) || null;
        }
        return datasets.find((item) => item.id === targetDatasetId) || null;
    }, [datasetInfo, datasets, isDatasetScope, targetDatasetId]);
    const shouldShowDuplicatePolicyHint = useMemo(
        () => isDatasetScope
            || mode === 'images'
            || mode === 'annotations'
            || (mode === 'associated' && associatedTargetMode === 'existing'),
        [associatedTargetMode, isDatasetScope, mode],
    );

    const branchOptions = useMemo(
        () => branches.map((branch) => ({label: branch.name, value: branch.name})),
        [branches],
    );

    const glossaryItems = useMemo(() => ([
        {
            key: 'format',
            title: t('import.project.glossary.format'),
            description: t(`import.project.glossary.${formatGlossaryKey(formatProfile)}`),
        },
        {
            key: 'branch',
            title: t('import.project.glossary.branch'),
            description: t('import.project.glossary.branchDesc'),
        },
        {
            key: 'dataset',
            title: t('import.project.glossary.dataset'),
            description: t('import.project.glossary.datasetDesc'),
        },
        {
            key: 'strategy',
            title: t('import.project.glossary.strategy'),
            description: conflictStrategy === 'replace'
                ? t('import.project.glossary.replaceDesc')
                : t('import.project.glossary.mergeDesc'),
        },
    ]), [t, formatProfile, conflictStrategy]);

    const currentStep = useMemo(() => {
        if (importTask.state.status === 'running' || importTask.state.events.length > 0) return 2;
        if (dryRun) return 1;
        return 0;
    }, [dryRun, importTask.state.events.length, importTask.state.status]);

    const progressPercent = useMemo(() => {
        const {current, total} = importTask.state.progress;
        if (!total) return 0;
        return Math.min(100, Math.round((current / total) * 100));
    }, [importTask.state.progress]);

    const statusMeta = useMemo(() => {
        if (importTask.isRunning) {
            return {
                color: 'processing',
                icon: <PlayCircleOutlined/>,
                text: t('import.workspace.stateRunning'),
                progressStatus: 'active' as const,
            };
        }
        if (importTask.isComplete) {
            return {
                color: 'success',
                icon: <CheckCircleOutlined/>,
                text: t('import.workspace.stateComplete'),
                progressStatus: 'success' as const,
            };
        }
        if (importTask.isError) {
            return {
                color: 'error',
                icon: <ExclamationCircleOutlined/>,
                text: t('import.workspace.stateError'),
                progressStatus: 'exception' as const,
            };
        }
        return {
            color: 'default',
            icon: <ClockCircleOutlined/>,
            text: t('import.workspace.stateIdle'),
            progressStatus: 'normal' as const,
        };
    }, [importTask.isComplete, importTask.isError, importTask.isRunning, t]);

    useEffect(() => {
        if (!dryRun) return;
        const nextTab: PreviewDetailTabKey = dryRun.errors.length > 0
            ? 'errors'
            : dryRun.warnings.length > 0
                ? 'warnings'
                : dryRun.plannedNewLabels.length > 0
                    ? 'labels'
                    : 'warnings';
        setPreviewDetailTab(nextTab);
        setPreviewPager({
            warnings: {current: 1, pageSize: 20},
            errors: {current: 1, pageSize: 20},
            labels: {current: 1, pageSize: 20},
        });
    }, [dryRun]);

    const handleDryRun = async () => {
        if (!archive) return;
        setRightPanelTab('preview');

        if (isDatasetScope) {
            if (!targetDatasetId) return;
            if (!canDatasetImport) {
                message.warning(t('common.noPermission'));
                return;
            }
            setDryRunLoading(true);
            try {
                const result = await api.dryRunDatasetImageImport(targetDatasetId, archive);
                setDryRun(result);
                setDryRunFailure(null);
                setConfirmCreateLabels(result.plannedNewLabels.length === 0);
                message.success(t('import.workspace.dryRunSuccess'));
            } catch (error) {
                const failure = buildDryRunFailureState(
                    error,
                    error instanceof Error ? error.message : t('import.workspace.dryRunError'),
                );
                setDryRun(null);
                setConfirmCreateLabels(false);
                setDryRunFailure(failure);
                message.error(failure.message);
            } finally {
                setDryRunLoading(false);
            }
            return;
        }

        if (!projectId) return;
        if (mode !== 'images' && !hasAvailableImportProfile) {
            message.warning(t('import.workspace.noAvailableImportProfile'));
            return;
        }
        if (requiresProjectWritePermission && (!canAnnotate || !canCommit)) {
            message.warning(t('common.noPermission'));
            return;
        }

        if ((mode === 'images' || mode === 'annotations') && !targetDatasetId) {
            message.warning(t('import.workspace.selectDatasetFirst'));
            return;
        }

        if (mode === 'associated' && associatedTargetMode === 'new' && !newDatasetName.trim()) {
            message.warning(t('import.workspace.newDatasetNameRequired'));
            return;
        }

        setDryRunLoading(true);
        try {
            let result: ImportDryRunResponse;
            if (mode === 'images') {
                result = await api.dryRunDatasetImageImport(targetDatasetId, archive);
            } else if (mode === 'annotations') {
                result = await api.dryRunProjectAnnotationImport(projectId, {
                    file: archive,
                    formatProfile,
                    datasetId: targetDatasetId,
                    branchName,
                });
            } else {
                result = await api.dryRunProjectAssociatedImport(projectId, {
                    file: archive,
                    formatProfile,
                    branchName,
                    targetDatasetMode: associatedTargetMode,
                    targetDatasetId: associatedTargetMode === 'existing' ? targetDatasetId : undefined,
                    newDatasetName: associatedTargetMode === 'new' ? newDatasetName : undefined,
                    newDatasetDescription: associatedTargetMode === 'new' ? newDatasetDescription : undefined,
                });
            }
            setDryRun(result);
            setDryRunFailure(null);
            setConfirmCreateLabels(result.plannedNewLabels.length === 0);
            message.success(t('import.workspace.dryRunSuccess'));
        } catch (error) {
            const failure = buildDryRunFailureState(
                error,
                error instanceof Error ? error.message : t('import.workspace.dryRunError'),
            );
            setDryRun(null);
            setConfirmCreateLabels(false);
            setDryRunFailure(failure);
            message.error(failure.message);
        } finally {
            setDryRunLoading(false);
        }
    };

    const handleExecute = async () => {
        setRightPanelTab('execution');

        if (isDatasetScope) {
            if (!targetDatasetId) return;
            if (sourceMode === 'files') {
                if (!canSampleCreate) {
                    message.warning(t('common.noPermission'));
                    return;
                }
                if (imageFiles.length === 0) return;
                await importTask.run(() => api.bulkUploadSamples(targetDatasetId, imageFiles));
                return;
            }
            if (!dryRun) return;
            if (!canDatasetImport) {
                message.warning(t('common.noPermission'));
                return;
            }
            await importTask.run(() =>
                api.executeDatasetImageImport(
                    targetDatasetId,
                    {
                        previewToken: dryRun.previewToken,
                        confirmCreateLabels,
                    },
                )
            );
            return;
        }

        if (!projectId || !dryRun) return;

        const executePayload = {
            previewToken: dryRun.previewToken,
            conflictStrategy: mode === 'images' ? undefined : conflictStrategy,
            confirmCreateLabels,
        };

        if (mode === 'images') {
            await importTask.run(() =>
                api.executeDatasetImageImport(targetDatasetId, executePayload)
            );
            return;
        }

        if (mode === 'annotations') {
            await importTask.run(() =>
                api.executeProjectAnnotationImport(projectId, executePayload)
            );
            return;
        }

        await importTask.run(() =>
            api.executeProjectAssociatedImport(projectId, executePayload)
        );
    };

    const exportIssues = (formatType: 'json' | 'csv') => {
        const issues = importTask.issues;
        if (!issues.length) {
            message.info(t('import.workspace.noIssuesToExport'));
            return;
        }

        const now = new Date().toISOString().replace(/[:.]/g, '-');
        if (formatType === 'json') {
            const blob = new Blob([JSON.stringify(issues, null, 2)], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `import-issues-${now}.json`;
            a.click();
            URL.revokeObjectURL(url);
            return;
        }

        const lines = [
            'event,phase,item_key,status,message,detail',
            ...issues.map((item) => [
                item.event,
                item.phase || '',
                item.itemKey || '',
                item.status || '',
                (item.message || '').replace(/,/g, ' '),
                JSON.stringify(item.detail || {}).replace(/,/g, ';'),
            ].join(',')),
        ];
        const blob = new Blob([lines.join('\n')], {type: 'text/csv;charset=utf-8;'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `import-issues-${now}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const updatePreviewPager = (tab: PreviewDetailTabKey, current: number, pageSize: number) => {
        setPreviewPager((prev) => ({
            ...prev,
            [tab]: {current, pageSize},
        }));
    };

    const getPagedPreviewData = <T,>(items: T[], tab: PreviewDetailTabKey): T[] => {
        const {current, pageSize} = previewPager[tab];
        const start = (current - 1) * pageSize;
        return items.slice(start, start + pageSize);
    };

    return (
        <div className="flex h-full min-w-0 flex-col gap-4 overflow-x-hidden pb-4">
            <Card className="!border-github-border !bg-github-panel">
                <div className="relative overflow-hidden rounded-xl border border-github-border bg-gradient-to-r from-github-panel to-github-base p-5">
                    <div className="pointer-events-none absolute -top-20 -right-20 h-52 w-52 rounded-full bg-blue-400/10 blur-3xl"/>
                    <div className="relative">
                        <Space align="start" className="w-full justify-between">
                            <Space align="start">
                                <Button
                                    icon={<ArrowLeftOutlined/>}
                                    onClick={() => navigate(isProjectScope ? `/projects/${projectId}/samples` : `/datasets/${datasetIdFromRoute}`)}
                                >
                                    {t('common.back')}
                                </Button>
                                <div>
                                    <Title level={4} className="!mb-1 !mt-0">
                                        {isProjectScope ? t('import.project.title') : t('import.dataset.title')}
                                    </Title>
                                    <Paragraph className="!mb-0 !text-github-muted">
                                        {isProjectScope ? t('import.project.subtitle') : t('import.workspace.runHint')}
                                    </Paragraph>
                                </div>
                            </Space>
                        </Space>

                        <div className="mt-5">
                            <Steps
                                size="small"
                                current={currentStep}
                                items={[
                                    {title: t('import.project.steps.configure')},
                                    {title: t('import.project.steps.dryRun')},
                                    {title: t('import.project.steps.execute')},
                                ]}
                            />
                        </div>
                    </div>
                </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[4fr_6fr]">
                <div className="space-y-4 min-w-0">
                    <Card
                        title={t('import.workspace.configureSection')}
                        className="!border-github-border !bg-github-panel"
                        extra={isProjectScope ? (
                            <Button icon={<QuestionCircleOutlined/>} onClick={() => setHelpOpen(true)}>
                                {t('import.workspace.helpButton')}
                            </Button>
                        ) : undefined}
                    >
                        <Space direction="vertical" size={16} className="w-full">
                            {isProjectScope && requiresProjectWritePermission && (!canAnnotate || !canCommit) ? (
                                <Alert type="warning" showIcon message={t('common.noPermission')}/>
                            ) : null}
                            {isProjectScope && mode !== 'images' && !hasAvailableImportProfile ? (
                                <Alert type="error" showIcon message={t('import.workspace.noAvailableImportProfile')}/>
                            ) : null}
                            {isDatasetScope && !hasDatasetModePermission ? (
                                <Alert type="warning" showIcon message={t('common.noPermission')}/>
                            ) : null}
                            {shouldShowDuplicatePolicyHint && selectedTargetDataset ? (
                                <Alert
                                    type="info"
                                    showIcon
                                    message={selectedTargetDataset.allowDuplicateSampleNames
                                        ? t('import.workspace.duplicatePolicyAllow')
                                        : t('import.workspace.duplicatePolicyDedupe')}
                                />
                            ) : null}

                            {isProjectScope ? (
                                <div>
                                    <Text strong>{t('import.workspace.modeLabel')}</Text>
                                    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                                        {modeCards.map((item) => {
                                            const selected = mode === item.value;
                                            return (
                                                <button
                                                    key={item.value}
                                                    type="button"
                                                    onClick={() => setMode(item.value)}
                                                    className={`rounded-lg border px-4 py-3 text-left transition ${
                                                        selected
                                                            ? 'border-blue-500 bg-blue-500/10 shadow-[0_4px_16px_rgba(59,130,246,0.15)]'
                                                            : 'border-github-border bg-github-base hover:border-github-border-muted'
                                                    }`}
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <Text strong>{item.title}</Text>
                                                        {selected ? <Tag color="blue">{t('common.selected')}</Tag> : null}
                                                    </div>
                                                    <Text type="secondary" className="!mt-2 block">{item.description}</Text>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            ) : (
                                <div>
                                    <Text strong>{t('import.workspace.sourceTypeLabel')}</Text>
                                    <div className="mt-3">
                                        <Radio.Group
                                            value={sourceMode}
                                            onChange={(e) => setSourceMode(e.target.value as DatasetImportSourceMode)}
                                            optionType="button"
                                            buttonStyle="solid"
                                            options={[
                                                {label: t('import.workspace.sourceTypeZip'), value: 'zip'},
                                                {label: t('import.workspace.sourceTypeFiles'), value: 'files'},
                                            ]}
                                        />
                                    </div>
                                </div>
                            )}

                            <div>
                                <Text strong>{isDatasetScope && sourceMode === 'files' ? t('import.workspace.selectImages') : t('import.workspace.sourceArchive')}</Text>
                                <div className="mt-3">
                                    {isDatasetScope && sourceMode === 'files' ? (
                                        <Upload
                                            multiple
                                            accept="image/*,.jpg,.jpeg,.png,.bmp,.webp,.gif,.tif,.tiff"
                                            beforeUpload={() => false}
                                            onChange={(info) => {
                                                const nextMap = new Map<string, File>();
                                                info.fileList.forEach((item) => {
                                                    const file = item.originFileObj as File | undefined;
                                                    if (!file) return;
                                                    nextMap.set(buildFileIdentity(file), file);
                                                });
                                                setImageFiles(Array.from(nextMap.values()));
                                                setDryRun(null);
                                                setDryRunFailure(null);
                                                setConfirmCreateLabels(false);
                                                importTask.reset();
                                            }}
                                        >
                                            <Button icon={<UploadOutlined/>}>{t('import.workspace.selectImages')}</Button>
                                        </Upload>
                                    ) : (
                                        <Dragger
                                            accept=".zip"
                                            multiple={false}
                                            showUploadList={false}
                                            beforeUpload={(file) => {
                                                setArchive(file as unknown as File);
                                                setDryRun(null);
                                                setDryRunFailure(null);
                                                setConfirmCreateLabels(false);
                                                importTask.reset();
                                                return false;
                                            }}
                                            onRemove={() => {
                                                setArchive(null);
                                                setDryRunFailure(null);
                                                return true;
                                            }}
                                        >
                                            <p className="ant-upload-drag-icon">
                                                <UploadOutlined/>
                                            </p>
                                            <p className="ant-upload-text">{t('import.workspace.selectZip')}</p>
                                            <p className="ant-upload-hint">{t('import.workspace.zipHint')}</p>
                                        </Dragger>
                                    )}
                                </div>
                                {isDatasetScope && sourceMode === 'files' ? (
                                    <>
                                        <Text type="secondary" className="!mt-2 block">
                                            {t('import.workspace.selectedImagesCount', {count: imageFiles.length})}
                                        </Text>
                                        <Alert className="!mt-2" type="info" showIcon message={t('import.workspace.directUploadNoDryRun')}/>
                                    </>
                                ) : archive ? (
                                    <Space className="!mt-2">
                                        <Text type="secondary">
                                            {t('import.workspace.selectedArchive', {name: archive.name})}
                                        </Text>
                                        <Button type="link" size="small" className="!px-0" onClick={() => setArchive(null)}>
                                            {t('common.delete')}
                                        </Button>
                                    </Space>
                                ) : null}
                            </div>

                            {isProjectScope ? (
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    {mode !== 'images' ? (
                                        <div>
                                            <Text strong>{t('import.workspace.formatLabel')}</Text>
                                            <Select
                                                value={formatProfile}
                                                onChange={(value) => setFormatProfile(value as ImportFormat)}
                                                options={formatOptions}
                                                className="mt-2 w-full"
                                                disabled={!hasAvailableImportProfile}
                                            />
                                        </div>
                                    ) : null}

                                    {mode !== 'images' && formatProfile === 'yolo_obb' ? (
                                        <div>
                                            <Text strong>{t('import.workspace.yoloSubFormatLabel')}</Text>
                                            <Select
                                                value={yoloObbLabelFormat}
                                                onChange={(value) => setYoloObbLabelFormat(value as YoloObbLabelFormat)}
                                                options={[
                                                    {label: 'OBB RBox', value: 'obb_rbox'},
                                                    {label: 'OBB Poly8', value: 'obb_poly8'},
                                                ]}
                                                className="mt-2 w-full"
                                            />
                                        </div>
                                    ) : null}

                                    {mode !== 'images' ? (
                                        <div>
                                            <Text strong>{t('import.workspace.branchLabel')}</Text>
                                            <Select
                                                value={branchName}
                                                onChange={setBranchName}
                                                options={branchOptions}
                                                className="mt-2 w-full"
                                            />
                                        </div>
                                    ) : null}

                                    {mode === 'associated' ? (
                                        <div>
                                            <Text strong>{t('import.workspace.datasetModeLabel')}</Text>
                                            <Select
                                                value={associatedTargetMode}
                                                onChange={(value) => setAssociatedTargetMode(value)}
                                                options={[
                                                    {label: t('import.project.target.existing'), value: 'existing'},
                                                    {label: t('import.project.target.new'), value: 'new'},
                                                ]}
                                                className="mt-2 w-full"
                                            />
                                        </div>
                                    ) : null}

                                    {(mode === 'images' || mode === 'annotations' || (mode === 'associated' && associatedTargetMode === 'existing')) ? (
                                        <div>
                                            <Text strong>{t('import.workspace.datasetLabel')}</Text>
                                            <Select
                                                value={targetDatasetId || undefined}
                                                onChange={setTargetDatasetId}
                                                options={datasetOptions}
                                                className="mt-2 w-full"
                                                placeholder={t('import.workspace.selectDatasetFirst')}
                                            />
                                        </div>
                                    ) : null}

                                    {mode !== 'images' ? (
                                        <div>
                                            <Text strong>{t('import.workspace.strategyLabel')}</Text>
                                            <Select
                                                value={conflictStrategy}
                                                onChange={(value) => setConflictStrategy(value)}
                                                options={[
                                                    {label: t('import.workspace.strategyReplace'), value: 'replace'},
                                                    {label: t('import.workspace.strategyMerge'), value: 'merge'},
                                                ]}
                                                className="mt-2 w-full"
                                            />
                                        </div>
                                    ) : null}
                                </div>
                            ) : null}

                            {isProjectScope && mode === 'associated' && associatedTargetMode === 'new' ? (
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    <div>
                                        <Text strong>{t('import.workspace.newDatasetName')}</Text>
                                        <Input
                                            value={newDatasetName}
                                            onChange={(e) => setNewDatasetName(e.target.value)}
                                            placeholder={t('import.workspace.newDatasetNameRequired')}
                                            className="mt-2"
                                        />
                                    </div>
                                    <div>
                                        <Text strong>{t('import.workspace.newDatasetDescription')}</Text>
                                        <Input
                                            value={newDatasetDescription}
                                            onChange={(e) => setNewDatasetDescription(e.target.value)}
                                            placeholder={t('dataset.list.descriptionPlaceholder')}
                                            className="mt-2"
                                        />
                                    </div>
                                </div>
                            ) : null}

                            <Space wrap>
                                {(isProjectScope || sourceMode === 'zip') ? (
                                    <Button
                                        type="primary"
                                        onClick={handleDryRun}
                                        loading={dryRunLoading}
                                        disabled={
                                            !archive
                                            || (isDatasetScope && !hasDatasetModePermission)
                                            || (isProjectScope && mode !== 'images' && !hasAvailableImportProfile)
                                        }
                                    >
                                        {t('import.workspace.dryRun')}
                                    </Button>
                                ) : null}
                                <Button
                                    onClick={handleExecute}
                                    disabled={!canExecute || importTask.isRunning || (isDatasetScope && !hasDatasetModePermission)}
                                >
                                    {t('import.workspace.execute')}
                                </Button>
                                <Button onClick={importTask.cancel} disabled={!importTask.isRunning}>
                                    {t('common.cancel')}
                                </Button>
                            </Space>
                            {isProjectScope && blockedByUnsupportedAnnotationType ? (
                                <Alert
                                    type="error"
                                    showIcon
                                    message={t('import.workspace.executeBlockedByUnsupportedType')}
                                />
                            ) : null}
                        </Space>
                    </Card>

                </div>

                <div className="min-w-0">
                    <Card className="!border-github-border !bg-github-panel h-full">
                        <Tabs
                            activeKey={rightPanelTab}
                            onChange={(key) => setRightPanelTab(key as 'preview' | 'execution')}
                            items={[
                                {
                                    key: 'preview',
                                    label: t('import.workspace.preview'),
                                    children: (
                                        <Space direction="vertical" size={14} className="w-full">
                                            {isDatasetScope && sourceMode === 'files' ? (
                                                <Alert
                                                    type="info"
                                                    showIcon
                                                    message={t('import.workspace.directUploadNoDryRun')}
                                                />
                                            ) : dryRunFailure ? (
                                                <Space direction="vertical" size={12} className="w-full">
                                                    <Alert
                                                        type="error"
                                                        showIcon
                                                        message={dryRunFailure.message}
                                                        description={t('import.workspace.dryRunErrorPanelHint')}
                                                    />
                                                    <Descriptions size="small" column={2} bordered>
                                                        {typeof dryRunFailure.statusCode === 'number' ? (
                                                            <Descriptions.Item label={t('import.workspace.statusCodeLabel')}>
                                                                {dryRunFailure.statusCode}
                                                            </Descriptions.Item>
                                                        ) : null}
                                                        {dryRunFailure.appCode !== undefined ? (
                                                            <Descriptions.Item label={t('import.workspace.errorCodeLabel')}>
                                                                {String(dryRunFailure.appCode)}
                                                            </Descriptions.Item>
                                                        ) : null}
                                                        {dryRunFailure.timestamp ? (
                                                            <Descriptions.Item label={t('import.workspace.timestampLabel')}>
                                                                {dryRunFailure.timestamp}
                                                            </Descriptions.Item>
                                                        ) : null}
                                                    </Descriptions>
                                                    {dryRunFailure.raw !== undefined ? (
                                                        <div className="rounded-md border border-github-border bg-github-base p-3">
                                                            <Text strong>{t('import.workspace.rawResponseLabel')}</Text>
                                                            <pre className="mt-2 whitespace-pre-wrap break-all text-xs text-github-muted">
                                                                {JSON.stringify(dryRunFailure.raw, null, 2)}
                                                            </pre>
                                                        </div>
                                                    ) : null}
                                                </Space>
                                            ) : !dryRun ? (
                                                <Alert
                                                    type="info"
                                                    showIcon
                                                    message={t('import.workspace.previewEmpty')}
                                                />
                                            ) : (
                                                <div className="flex min-h-[620px] flex-col gap-3">
                                                    {summaryEntries.length > 0 ? (
                                                        <Descriptions size="small" column={2} bordered>
                                                            {summaryEntries.map((item) => (
                                                                <Descriptions.Item key={item.key} label={item.label}>
                                                                    {item.value}
                                                                </Descriptions.Item>
                                                            ))}
                                                        </Descriptions>
                                                    ) : null}

                                                    <Alert
                                                        type={dryRun.errors.length ? 'error' : 'info'}
                                                        showIcon
                                                        message={t('import.workspace.previewIssues', {
                                                            warnings: dryRun.warnings.length,
                                                            errors: dryRun.errors.length,
                                                        })}
                                                        description={t('import.workspace.expiresAt', {time: dryRun.expiresAt})}
                                                    />

                                                    <Tabs
                                                        activeKey={previewDetailTab}
                                                        onChange={(key) => setPreviewDetailTab(key as PreviewDetailTabKey)}
                                                        items={[
                                                            {
                                                                key: 'warnings',
                                                                label: (
                                                                    <Space size={8}>
                                                                        <span>{t('import.workspace.warnings')}</span>
                                                                        <Tag className="!m-0">{previewCounts.warnings}</Tag>
                                                                    </Space>
                                                                ),
                                                                children: (
                                                                    <div className="flex flex-col gap-3">
                                                                        <List
                                                                            size="small"
                                                                            bordered
                                                                            className="max-h-[360px] overflow-y-auto"
                                                                            dataSource={getPagedPreviewData(dryRun.warnings, 'warnings')}
                                                                            locale={{emptyText: t('import.workspace.previewNoItems')}}
                                                                            renderItem={(item) => {
                                                                                const localized = localizeImportIssueMessage(t, item);
                                                                                return (
                                                                                    <List.Item>
                                                                                        <Space direction="vertical" size={2} className="w-full">
                                                                                            <Space size={8}>
                                                                                                <Tag className="!m-0">{item.code}</Tag>
                                                                                            </Space>
                                                                                            <Text>{localized.message}</Text>
                                                                                            {item.path ? (
                                                                                                <Text type="secondary" className="break-all">{item.path}</Text>
                                                                                            ) : null}
                                                                                            {localized.rawMessage ? (
                                                                                                <Text type="secondary" className="break-all">
                                                                                                    {t('import.workspace.originalMessage', {message: localized.rawMessage})}
                                                                                                </Text>
                                                                                            ) : null}
                                                                                        </Space>
                                                                                    </List.Item>
                                                                                );
                                                                            }}
                                                                        />
                                                                        {previewCounts.warnings > 0 ? (
                                                                            <Pagination
                                                                                size="small"
                                                                                current={previewPager.warnings.current}
                                                                                pageSize={previewPager.warnings.pageSize}
                                                                                total={previewCounts.warnings}
                                                                                showSizeChanger
                                                                                pageSizeOptions={[20, 50, 100]}
                                                                                showTotal={(total) => `${total}`}
                                                                                onChange={(page, pageSize) => updatePreviewPager('warnings', page, pageSize)}
                                                                            />
                                                                        ) : null}
                                                                    </div>
                                                                ),
                                                            },
                                                            {
                                                                key: 'errors',
                                                                label: (
                                                                    <Space size={8}>
                                                                        <span>{t('import.workspace.errors')}</span>
                                                                        <Tag color={previewCounts.errors ? 'red' : 'default'} className="!m-0">
                                                                            {previewCounts.errors}
                                                                        </Tag>
                                                                    </Space>
                                                                ),
                                                                children: (
                                                                    <div className="flex flex-col gap-3">
                                                                        <List
                                                                            size="small"
                                                                            bordered
                                                                            className="max-h-[360px] overflow-y-auto"
                                                                            dataSource={getPagedPreviewData(dryRun.errors, 'errors')}
                                                                            locale={{emptyText: t('import.workspace.previewNoItems')}}
                                                                            renderItem={(item) => {
                                                                                const localized = localizeImportIssueMessage(t, item);
                                                                                return (
                                                                                    <List.Item>
                                                                                        <Space direction="vertical" size={2} className="w-full">
                                                                                            <Space size={8}>
                                                                                                <Tag color="red" className="!m-0">{item.code}</Tag>
                                                                                            </Space>
                                                                                            <Text>{localized.message}</Text>
                                                                                            {item.path ? (
                                                                                                <Text type="secondary" className="break-all">{item.path}</Text>
                                                                                            ) : null}
                                                                                            {localized.rawMessage ? (
                                                                                                <Text type="secondary" className="break-all">
                                                                                                    {t('import.workspace.originalMessage', {message: localized.rawMessage})}
                                                                                                </Text>
                                                                                            ) : null}
                                                                                        </Space>
                                                                                    </List.Item>
                                                                                );
                                                                            }}
                                                                        />
                                                                        {previewCounts.errors > 0 ? (
                                                                            <Pagination
                                                                                size="small"
                                                                                current={previewPager.errors.current}
                                                                                pageSize={previewPager.errors.pageSize}
                                                                                total={previewCounts.errors}
                                                                                showSizeChanger
                                                                                pageSizeOptions={[20, 50, 100]}
                                                                                showTotal={(total) => `${total}`}
                                                                                onChange={(page, pageSize) => updatePreviewPager('errors', page, pageSize)}
                                                                            />
                                                                        ) : null}
                                                                    </div>
                                                                ),
                                                            },
                                                            {
                                                                key: 'labels',
                                                                label: (
                                                                    <Space size={8}>
                                                                        <span>{t('import.workspace.plannedNewLabels')}</span>
                                                                        <Tag color={previewCounts.labels ? 'blue' : 'default'} className="!m-0">
                                                                            {previewCounts.labels}
                                                                        </Tag>
                                                                    </Space>
                                                                ),
                                                                children: (
                                                                    <div className="flex flex-col gap-3">
                                                                        <List
                                                                            size="small"
                                                                            bordered
                                                                            className="max-h-[360px] overflow-y-auto"
                                                                            dataSource={getPagedPreviewData(dryRun.plannedNewLabels, 'labels')}
                                                                            locale={{emptyText: t('import.workspace.previewNoItems')}}
                                                                            renderItem={(item) => <List.Item>{item}</List.Item>}
                                                                        />
                                                                        {previewCounts.labels > 0 ? (
                                                                            <Pagination
                                                                                size="small"
                                                                                current={previewPager.labels.current}
                                                                                pageSize={previewPager.labels.pageSize}
                                                                                total={previewCounts.labels}
                                                                                showSizeChanger
                                                                                pageSizeOptions={[20, 50, 100]}
                                                                                showTotal={(total) => `${total}`}
                                                                                onChange={(page, pageSize) => updatePreviewPager('labels', page, pageSize)}
                                                                            />
                                                                        ) : null}
                                                                    </div>
                                                                ),
                                                            },
                                                        ]}
                                                    />

                                                    {dryRun.plannedNewLabels.length > 0 ? (
                                                        <Checkbox
                                                            checked={confirmCreateLabels}
                                                            onChange={(e) => setConfirmCreateLabels(e.target.checked)}
                                                        >
                                                            {t('import.workspace.confirmCreateLabels')}
                                                        </Checkbox>
                                                    ) : null}
                                                </div>
                                            )}
                                        </Space>
                                    ),
                                },
                                {
                                    key: 'execution',
                                    label: t('import.workspace.execution'),
                                    children: (
                                        <Space direction="vertical" size={12} className="w-full">
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <Space>
                                                    <Tag color={statusMeta.color} icon={statusMeta.icon}>{statusMeta.text}</Tag>
                                                    {importTask.state.phase ? (
                                                        <Text type="secondary">{importTask.state.phase}</Text>
                                                    ) : null}
                                                </Space>
                                                <Text type="secondary">
                                                    {importTask.state.progress.current}/{importTask.state.progress.total}
                                                </Text>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-4">
                                                <Text type="secondary">
                                                    {t('import.workspace.startedAt', {time: formatDualTime(executionStartedAt, nowMs)})}
                                                </Text>
                                                <Text type="secondary">
                                                    {t('import.workspace.elapsed', {duration: executionElapsed})}
                                                </Text>
                                            </div>

                                            <Progress percent={progressPercent} status={statusMeta.progressStatus}/>

                                            {importTask.state.error ? (
                                                <Alert type="error" showIcon message={importTask.state.error}/>
                                            ) : null}

                                            <Space wrap>
                                                <Button onClick={() => exportIssues('json')} disabled={!importTask.issues.length}>
                                                    {t('import.workspace.exportJson')}
                                                </Button>
                                                <Button onClick={() => exportIssues('csv')} disabled={!importTask.issues.length}>
                                                    {t('import.workspace.exportCsv')}
                                                </Button>
                                            </Space>

                                            <Text type="secondary">{t('import.workspace.eventsLatest')}</Text>
                                            <div className="rounded-lg border border-github-border">
                                                {executionEvents.length === 0 ? (
                                                    <div className="px-4 py-8 text-center text-github-muted">
                                                        {t('import.workspace.noEvents')}
                                                    </div>
                                                ) : (
                                                    <VirtualList
                                                        data={executionEvents}
                                                        height={560}
                                                        itemHeight={EVENT_ROW_HEIGHT}
                                                        itemKey={(item) =>
                                                            String(item.seq ?? `${item.receivedAt || ''}-${item.event}-${item.itemKey || ''}`)
                                                        }
                                                    >
                                                        {(item) => (
                                                            <div className="border-b border-github-border/70 px-3 py-2 last:border-b-0">
                                                                <div className="flex w-full items-start justify-between gap-3">
                                                                    <Space direction="vertical" size={2} className="min-w-0">
                                                                        <Space size={8}>
                                                                            <Tag color={eventTagColorMap[item.event]} className="!m-0">{item.event}</Tag>
                                                                            {item.phase ? <Text type="secondary">{item.phase}</Text> : null}
                                                                        </Space>
                                                                        <Text className="break-all">
                                                                            {item.message || item.itemKey || item.phase || `${item.event}${item.status ? `(${item.status})` : ''}`}
                                                                        </Text>
                                                                    </Space>
                                                                    <Space direction="vertical" size={0} className="items-end">
                                                                        <Text type="secondary">{formatDualTime(item.receivedAt, nowMs)}</Text>
                                                                        {(typeof item.current === 'number' && typeof item.total === 'number') ? (
                                                                            <Text type="secondary">{item.current}/{item.total}</Text>
                                                                        ) : null}
                                                                    </Space>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </VirtualList>
                                                )}
                                            </div>
                                        </Space>
                                    ),
                                },
                            ]}
                        />
                    </Card>
                </div>
            </div>

            {isProjectScope ? (
                <Drawer
                    title={t('import.project.glossary.title')}
                    width={460}
                    open={helpOpen}
                    onClose={() => setHelpOpen(false)}
                >
                    <Space direction="vertical" size={14} className="w-full">
                        <Alert
                            type="info"
                            showIcon
                            message={t('import.project.introTitle')}
                            description={t('import.project.introBody')}
                        />

                        <div className="rounded-lg border border-github-border bg-github-base p-3">
                            <Text strong>{t('import.workspace.currentConfig')}</Text>
                            <Descriptions size="small" column={1} className="mt-3">
                                <Descriptions.Item label={t('import.workspace.modeLabel')}>
                                    {modeCards.find((item) => item.value === mode)?.title}
                                </Descriptions.Item>
                                {mode === 'associated' ? (
                                    <Descriptions.Item label={t('import.workspace.datasetModeLabel')}>
                                        {associatedTargetMode === 'existing'
                                            ? t('import.project.target.existing')
                                            : t('import.project.target.new')}
                                    </Descriptions.Item>
                                ) : null}
                                {(mode === 'images' || mode === 'annotations' || (mode === 'associated' && associatedTargetMode === 'existing')) ? (
                                    <Descriptions.Item label={t('import.workspace.datasetLabel')}>
                                        {datasets.find((item) => item.id === targetDatasetId)?.name || '-'}
                                    </Descriptions.Item>
                                ) : null}
                                {mode === 'associated' && associatedTargetMode === 'new' ? (
                                    <Descriptions.Item label={t('import.workspace.newDatasetName')}>
                                        {newDatasetName || '-'}
                                    </Descriptions.Item>
                                ) : null}
                                {mode !== 'images' ? (
                                    <Descriptions.Item label={t('import.workspace.formatLabel')}>
                                        {formatProfileLabel(formatProfile)}
                                    </Descriptions.Item>
                                ) : null}
                                {mode !== 'images' && formatProfile === 'yolo_obb' ? (
                                    <Descriptions.Item label={t('import.workspace.yoloSubFormatLabel')}>
                                        {yoloObbLabelFormat === 'obb_rbox' ? 'OBB RBox' : 'OBB Poly8'}
                                    </Descriptions.Item>
                                ) : null}
                                {mode !== 'images' ? (
                                    <Descriptions.Item label={t('import.workspace.branchLabel')}>
                                        {branchName}
                                    </Descriptions.Item>
                                ) : null}
                                {mode !== 'images' ? (
                                    <Descriptions.Item label={t('import.workspace.strategyLabel')}>
                                        {conflictStrategy === 'replace' ? t('import.workspace.strategyReplace') : t('import.workspace.strategyMerge')}
                                    </Descriptions.Item>
                                ) : null}
                            </Descriptions>
                        </div>

                        <List
                            size="small"
                            bordered
                            dataSource={glossaryItems}
                            renderItem={(item) => (
                                <List.Item>
                                    <Space direction="vertical" size={2}>
                                        <Text strong>{item.title}</Text>
                                        <Text type="secondary">{item.description}</Text>
                                    </Space>
                                </List.Item>
                            )}
                        />
                    </Space>
                </Drawer>
            ) : null}
        </div>
    );
};

export default ProjectImportWorkspace;
