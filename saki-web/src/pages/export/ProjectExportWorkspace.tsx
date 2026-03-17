import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Checkbox,
    Descriptions,
    Divider,
    Input,
    Progress,
    Radio,
    Select,
    Space,
    Switch,
    Tag,
    Typography,
    message,
} from 'antd';
import {ArrowLeftOutlined, DownloadOutlined, StopOutlined} from '@ant-design/icons';
import {useNavigate, useParams} from 'react-router-dom';
import {useTranslation} from 'react-i18next';
import {BlobReader, BlobWriter, TextReader, ZipWriter} from '@zip.js/zip.js';
import {api} from '../../services/api';
import {
    Dataset,
    ExportBundleLayout,
    FormatProfileCapability,
    FormatProfileId,
    PredictionsJSONDetectionTraceField,
    PredictionsJSONEntryTraceField,
    PredictionsJSONObbCompatField,
    PredictionsJSONOptions,
    PredictionsJSONRectCompatField,
    Project,
    ProjectBranch,
    ProjectExportResolveResponse,
    ProjectIOCapabilities,
    SampleScope,
    YoloLabelFormat,
} from '../../types';
import {useResourcePermission} from '../../hooks';

const {Title, Text, Paragraph} = Typography;
const {TextArea} = Input;

const ASSET_CONCURRENCY = 4;
const CHUNK_LIMIT = 200;

interface ExportProgress {
    phase: 'idle' | 'resolving' | 'streaming' | 'done' | 'error' | 'canceled';
    samplesDone: number;
    samplesTotal: number;
    assetsDone: number;
    assetsTotal: number;
    currentDataset?: string;
}

interface StreamZipParams {
    projectId: string;
    resolvedCommitId: string;
    datasetIds: string[];
    zipWriter: ZipWriter<unknown>;
    formatProfile: FormatProfileId;
    yoloLabelFormat?: YoloLabelFormat;
    predictionsJsonOptions?: PredictionsJSONOptions;
    sampleScope: SampleScope;
    includeAssets: boolean;
    bundleLayout: ExportBundleLayout;
    failFast: boolean;
    signal: AbortSignal;
    appendIssue: (text: string) => void;
    setProgress: React.Dispatch<React.SetStateAction<ExportProgress>>;
}

interface ExportRuntimeCapability {
    isSecureContext: boolean;
    hasSaveFilePicker: boolean;
    hasDirectoryPicker: boolean;
}

function detectExportRuntimeCapability(): ExportRuntimeCapability {
    if (typeof window === 'undefined') {
        return {
            isSecureContext: false,
            hasSaveFilePicker: false,
            hasDirectoryPicker: false,
        };
    }
    return {
        isSecureContext: Boolean(window.isSecureContext),
        hasSaveFilePicker: typeof (window as any).showSaveFilePicker === 'function',
        hasDirectoryPicker: typeof (window as any).showDirectoryPicker === 'function',
    };
}

function downloadBlob(blob: Blob, fileName: string): void {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function sanitizePathSegment(value: string): string {
    const cleaned = String(value || '')
        .trim()
        .replace(/[<>:"|?*\x00-\x1f]/g, '_');
    return cleaned || 'unknown';
}

function formatSize(value: number): string {
    if (value <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let idx = 0;
    while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx += 1;
    }
    return `${size.toFixed(size >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function isAbortError(error: unknown): boolean {
    const value = error as any;
    const code = String(value?.code || '');
    const name = String(value?.name || '');
    return code === 'ERR_CANCELED' || name === 'AbortError';
}

async function runWithConcurrency(tasks: Array<() => Promise<void>>, limit: number): Promise<void> {
    if (tasks.length === 0) return;
    const workerCount = Math.max(1, Math.min(limit, tasks.length));
    let index = 0;
    const workers = Array.from({length: workerCount}, async () => {
        while (index < tasks.length) {
            const current = tasks[index];
            index += 1;
            await current();
        }
    });
    await Promise.all(workers);
}

function getFormatLabel(id: FormatProfileId): string {
    if (id === 'coco') return 'COCO';
    if (id === 'voc') return 'VOC';
    if (id === 'yolo') return 'YOLO';
    if (id === 'dota') return 'DOTA';
    if (id === 'predictions_json') return 'Predictions JSON';
    return 'YOLO OBB';
}

async function streamZipByChunks(params: StreamZipParams): Promise<void> {
    const {
        projectId,
        resolvedCommitId,
        datasetIds,
        zipWriter,
        formatProfile,
        yoloLabelFormat,
        predictionsJsonOptions,
        sampleScope,
        includeAssets,
        bundleLayout,
        failFast,
        signal,
        appendIssue,
        setProgress,
    } = params;
    const writtenPaths = new Set<string>();
    let cursor: number | null | undefined = undefined;
    while (true) {
        if (signal.aborted) throw new DOMException('aborted', 'AbortError');
        const chunk = await api.getProjectExportChunk(
            projectId,
            {
                resolvedCommitId,
                datasetIds,
                sampleScope,
                formatProfile,
                yoloLabelFormat,
                predictionsJsonOptions,
                bundleLayout,
                includeAssets,
                cursor: cursor ?? null,
                limit: CHUNK_LIMIT,
            },
            signal,
        );

        for (const issue of chunk.issues || []) {
            appendIssue(issue);
            if (failFast) {
                throw new Error(issue);
            }
        }

        const files = chunk.files || [];
        const assetTasks: Array<() => Promise<void>> = [];
        let assetsPlanned = 0;

        for (const file of files) {
            const path = String(file.path || '').trim();
            if (!path) continue;
            if (writtenPaths.has(path)) {
                appendIssue(`duplicate export path skipped: ${path}`);
                continue;
            }

            if (file.sourceType === 'text') {
                await zipWriter.add(path, new TextReader(file.textContent || ''));
                writtenPaths.add(path);
                continue;
            }

            if (file.sourceType !== 'url') {
                appendIssue(`unsupported file source type: ${String(file.sourceType)}`);
                if (failFast) {
                    throw new Error(`unsupported file source type: ${String(file.sourceType)}`);
                }
                continue;
            }

            if (!file.downloadUrl) {
                const issue = `missing download url for path=${path}`;
                appendIssue(issue);
                if (failFast) {
                    throw new Error(issue);
                }
                continue;
            }

            assetsPlanned += 1;
            assetTasks.push(async () => {
                if (signal.aborted) throw new DOMException('aborted', 'AbortError');
                try {
                    const response = await fetch(file.downloadUrl as string, {signal});
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    if (response.body) {
                        await zipWriter.add(path, response.body, {level: 0});
                    } else {
                        const blob = await response.blob();
                        await zipWriter.add(path, new BlobReader(blob), {level: 0});
                    }
                    writtenPaths.add(path);
                } catch (error) {
                    const issue = `asset download failed path=${path}: ${error instanceof Error ? error.message : String(error)}`;
                    appendIssue(issue);
                    if (failFast) throw error;
                } finally {
                    setProgress((prev) => ({...prev, assetsDone: prev.assetsDone + 1}));
                }
            });
        }

        setProgress((prev) => ({
            ...prev,
            samplesDone: prev.samplesDone + Number(chunk.sampleCount || 0),
            assetsTotal: prev.assetsTotal + assetsPlanned,
        }));

        await runWithConcurrency(assetTasks, ASSET_CONCURRENCY);

        if (chunk.nextCursor === null || chunk.nextCursor === undefined) {
            break;
        }
        if (cursor === chunk.nextCursor) {
            appendIssue('chunk cursor did not advance, stopped to prevent infinite loop');
            break;
        }
        cursor = chunk.nextCursor;
    }
}

const ProjectExportWorkspace: React.FC = () => {
    const {t} = useTranslation();
    const {projectId} = useParams<{ projectId: string }>();
    const navigate = useNavigate();
    const {can: canProject} = useResourcePermission('project', projectId);

    const canExport = canProject('project:export:assigned');
    const runtimeCapability = detectExportRuntimeCapability();

    const [project, setProject] = useState<Project | null>(null);
    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [capabilities, setCapabilities] = useState<ProjectIOCapabilities | null>(null);
    const [loadingMeta, setLoadingMeta] = useState(true);

    const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
    const [snapshotType, setSnapshotType] = useState<'branch_head' | 'commit'>('branch_head');
    const [branchName, setBranchName] = useState('master');
    const [commitId, setCommitId] = useState('');
    const [sampleScope, setSampleScope] = useState<SampleScope>('all');
    const [formatProfile, setFormatProfile] = useState<FormatProfileId>('coco');
    const [yoloLabelFormat, setYoloLabelFormat] = useState<YoloLabelFormat>('obb_rbox');
    const [predictionsJsonIncludeEmptyEntries, setPredictionsJsonIncludeEmptyEntries] = useState(false);
    const [predictionsJsonEntryTraceFields, setPredictionsJsonEntryTraceFields] = useState<PredictionsJSONEntryTraceField[]>([]);
    const [predictionsJsonDetectionTraceFields, setPredictionsJsonDetectionTraceFields] = useState<PredictionsJSONDetectionTraceField[]>([]);
    const [predictionsJsonRectCompatFields, setPredictionsJsonRectCompatFields] = useState<PredictionsJSONRectCompatField[]>(['xyxy', 'xywh']);
    const [predictionsJsonObbCompatFields, setPredictionsJsonObbCompatFields] = useState<PredictionsJSONObbCompatField[]>(['xyxyxyxy', 'xywhr']);
    const [predictionsJsonFilterText, setPredictionsJsonFilterText] = useState('');
    const [includeAssets, setIncludeAssets] = useState(true);
    const [bundleLayout, setBundleLayout] = useState<ExportBundleLayout>('merged_zip');
    const [failFast, setFailFast] = useState(false);

    const [resolving, setResolving] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [resolveResult, setResolveResult] = useState<ProjectExportResolveResponse | null>(null);
    const [report, setReport] = useState<string[]>([]);
    const [progress, setProgress] = useState<ExportProgress>({
        phase: 'idle',
        samplesDone: 0,
        samplesTotal: 0,
        assetsDone: 0,
        assetsTotal: 0,
    });

    const abortRef = useRef<AbortController | null>(null);
    const writableRef = useRef<Array<{close: () => Promise<void>; abort?: (reason?: unknown) => Promise<void>}>>([]);

    useEffect(() => {
        if (!projectId) return;
        setLoadingMeta(true);
        Promise.all([
            api.getProject(projectId),
            api.getProjectDatasetDetails(projectId),
            api.getProjectBranches(projectId),
            api.getProjectIOCapabilities(projectId),
        ]).then(([projectInfo, datasetList, branchList, io]) => {
            setProject(projectInfo);
            setDatasets(datasetList || []);
            setBranches(branchList || []);
            setCapabilities(io);
            setSelectedDatasetIds((datasetList || []).map((item) => item.id));

            const preferredBranch = (branchList || []).find((item) => item.name === 'master')?.name
                || branchList?.[0]?.name
                || 'master';
            setBranchName(preferredBranch);

            const availableExportProfiles = (io.exportProfiles || []).filter((item) => item.available);
            if (availableExportProfiles.length > 0) {
                setFormatProfile(availableExportProfiles[0].id as FormatProfileId);
            }
        }).catch((error) => {
            message.error(error instanceof Error ? error.message : t('export.project.metaLoadError'));
        }).finally(() => {
            setLoadingMeta(false);
        });
    }, [projectId, t]);

    const datasetNameById = useMemo(
        () => new Map(datasets.map((item) => [item.id, item.name])),
        [datasets],
    );

    const selectedDatasets = useMemo(
        () => datasets.filter((item) => selectedDatasetIds.includes(item.id)),
        [datasets, selectedDatasetIds],
    );

    const exportProfiles = useMemo(
        () => (capabilities?.exportProfiles || []).filter((item) => item.available),
        [capabilities],
    );
    const selectedFormatCapability = useMemo(
        () => exportProfiles.find((item) => item.id === formatProfile) as FormatProfileCapability | undefined,
        [exportProfiles, formatProfile],
    );
    const selectedYoloLabelOptions = useMemo(
        () => (selectedFormatCapability?.yoloLabelOptions || []) as YoloLabelFormat[],
        [selectedFormatCapability],
    );
    const isPredictionsJson = formatProfile === 'predictions_json';

    useEffect(() => {
        if (exportProfiles.length === 0) return;
        const exists = exportProfiles.some((item) => item.id === formatProfile);
        if (!exists) {
            const next = exportProfiles[0].id as FormatProfileId;
            setFormatProfile(next);
        }
    }, [exportProfiles, formatProfile]);

    useEffect(() => {
        if (formatProfile !== 'yolo_obb') return;
        if (selectedYoloLabelOptions.length === 0) {
            setYoloLabelFormat('obb_rbox');
            return;
        }
        if (!selectedYoloLabelOptions.includes(yoloLabelFormat)) {
            setYoloLabelFormat(selectedYoloLabelOptions[0]);
        }
    }, [formatProfile, selectedYoloLabelOptions, yoloLabelFormat]);

    const buildPredictionsJsonOptions = useCallback((): PredictionsJSONOptions | undefined => {
        if (formatProfile !== 'predictions_json') {
            return undefined;
        }

        const rawFilter = predictionsJsonFilterText.trim();
        let parsedFilter: PredictionsJSONOptions['filter'] = null;
        if (rawFilter) {
            try {
                parsedFilter = JSON.parse(rawFilter) as PredictionsJSONOptions['filter'];
            } catch (error) {
                throw new Error(`predictions_json filter JSON 解析失败: ${error instanceof Error ? error.message : String(error)}`);
            }
        }

        return {
            includeEmptyEntries: predictionsJsonIncludeEmptyEntries,
            includeEntryTraceFields: predictionsJsonEntryTraceFields,
            includeDetectionTraceFields: predictionsJsonDetectionTraceFields,
            geometryCompatFields: {
                rect: predictionsJsonRectCompatFields,
                obb: predictionsJsonObbCompatFields,
            },
            filter: parsedFilter,
        };
    }, [
        formatProfile,
        predictionsJsonFilterText,
        predictionsJsonIncludeEmptyEntries,
        predictionsJsonEntryTraceFields,
        predictionsJsonDetectionTraceFields,
        predictionsJsonRectCompatFields,
        predictionsJsonObbCompatFields,
    ]);

    const estimatedTotalBytes = resolveResult?.estimatedTotalAssetBytes || 0;

    const appendReportIssue = useCallback((value: string) => {
        setReport((prev) => [...prev, value]);
    }, []);

    const cleanupWritables = useCallback(async () => {
        const all = [...writableRef.current];
        writableRef.current = [];
        await Promise.allSettled(all.map((item) => item.abort?.('cleanup') || item.close()));
    }, []);

    const cancelRunning = useCallback(async () => {
        abortRef.current?.abort();
        abortRef.current = null;
        const all = [...writableRef.current];
        writableRef.current = [];
        await Promise.allSettled(all.map((item) => item.abort?.('user canceled') || item.close()));
        setProgress((prev) => ({...prev, phase: 'canceled'}));
    }, []);

    const buildResolvePayload = useCallback(() => {
        if (!projectId) return null;

        const snapshot = snapshotType === 'branch_head'
            ? {type: 'branch_head' as const, branchName}
            : {type: 'commit' as const, commitId};

        return {
            datasetIds: selectedDatasetIds,
            snapshot,
            sampleScope,
            formatProfile,
            yoloLabelFormat: formatProfile === 'yolo_obb' ? yoloLabelFormat : undefined,
            predictionsJsonOptions: buildPredictionsJsonOptions(),
            includeAssets,
            bundleLayout,
        };
    }, [
        projectId,
        formatProfile,
        yoloLabelFormat,
        snapshotType,
        branchName,
        commitId,
        selectedDatasetIds,
        sampleScope,
        includeAssets,
        bundleLayout,
        buildPredictionsJsonOptions,
    ]);

    const writeZipPayload = useCallback(async (args: {
        zipWriter: ZipWriter<unknown>;
        title: string;
        resolve: ProjectExportResolveResponse;
        datasetIds: string[];
        signal: AbortSignal;
    }) => {
        const {zipWriter, title, resolve, datasetIds, signal} = args;

        await streamZipByChunks({
            projectId: projectId!,
            resolvedCommitId: resolve.resolvedCommitId,
            datasetIds,
            zipWriter,
            formatProfile,
            yoloLabelFormat: formatProfile === 'yolo_obb' ? yoloLabelFormat : undefined,
            predictionsJsonOptions: buildPredictionsJsonOptions(),
            sampleScope,
            includeAssets,
            bundleLayout,
            failFast,
            signal,
            appendIssue: appendReportIssue,
            setProgress,
        });

        const reportPayload = {
            exportedAt: new Date().toISOString(),
            projectId,
            title,
            formatProfile,
            yoloLabelFormat: formatProfile === 'yolo_obb' ? yoloLabelFormat : undefined,
            predictionsJsonOptions: buildPredictionsJsonOptions(),
            includeAssets,
            sampleScope,
            datasetIds,
        };
        await zipWriter.add('export_manifest.json', new TextReader(`${JSON.stringify(reportPayload, null, 2)}\n`));
    }, [
        projectId,
        formatProfile,
        yoloLabelFormat,
        sampleScope,
        includeAssets,
        bundleLayout,
        failFast,
        buildPredictionsJsonOptions,
        appendReportIssue,
    ]);

    const exportOneZip = useCallback(async (args: {
        handle: any;
        title: string;
        resolve: ProjectExportResolveResponse;
        datasetIds: string[];
        signal: AbortSignal;
    }) => {
        const {handle, title, resolve, datasetIds, signal} = args;
        const writable = await handle.createWritable();
        writableRef.current.push(writable);

        const zipWriter = new ZipWriter(writable as WritableStream, {zip64: true});
        try {
            await writeZipPayload({
                zipWriter,
                title,
                resolve,
                datasetIds,
                signal,
            });
            await zipWriter.close();
        } catch (error) {
            await zipWriter.close().catch(() => undefined);
            await writable.abort(error).catch(() => undefined);
            throw error;
        } finally {
            writableRef.current = writableRef.current.filter((item) => item !== writable);
        }
    }, [
        writeZipPayload,
    ]);

    const exportOneZipToBlob = useCallback(async (args: {
        title: string;
        resolve: ProjectExportResolveResponse;
        datasetIds: string[];
        signal: AbortSignal;
    }): Promise<Blob> => {
        const {title, resolve, datasetIds, signal} = args;
        const zipWriter = new ZipWriter(new BlobWriter('application/zip'), {zip64: true});
        try {
            await writeZipPayload({
                zipWriter,
                title,
                resolve,
                datasetIds,
                signal,
            });
            return await zipWriter.close() as Blob;
        } catch (error) {
            await zipWriter.close().catch(() => undefined);
            throw error;
        }
    }, [writeZipPayload]);

    const handleStart = useCallback(async () => {
        if (!projectId) return;
        if (!canExport) {
            message.warning(t('common.noPermission'));
            return;
        }
        if (selectedDatasetIds.length === 0) {
            message.warning(t('export.project.selectDatasetFirst'));
            return;
        }
        if (snapshotType === 'commit' && !commitId.trim()) {
            message.warning(t('export.project.commitRequired'));
            return;
        }

        let payload: ReturnType<typeof buildResolvePayload>;
        try {
            payload = buildResolvePayload();
        } catch (error) {
            message.error(error instanceof Error ? error.message : t('export.project.startFailed'));
            return;
        }
        if (!payload) return;

        setReport([]);
        setResolving(true);
        setProgress((prev) => ({
            ...prev,
            phase: 'resolving',
            samplesDone: 0,
            samplesTotal: 0,
            assetsDone: 0,
            assetsTotal: 0,
        }));

        const resolveAbort = new AbortController();
        abortRef.current = resolveAbort;

        try {
            const resolved = await api.resolveProjectExport(projectId, payload, resolveAbort.signal);
            setResolveResult(resolved);

            const totalSamples = (resolved.datasetStats || []).reduce((sum, item) => sum + (item.sampleCount || 0), 0);
            setProgress((prev) => ({
                ...prev,
                phase: 'streaming',
                samplesDone: 0,
                samplesTotal: totalSamples,
                assetsDone: 0,
                assetsTotal: 0,
            }));

            if (resolved.blocked) {
                setProgress((prev) => ({...prev, phase: 'error'}));
                message.error(resolved.blockReason || t('export.project.resolveBlocked'));
                return;
            }

            setExporting(true);

            if (bundleLayout === 'merged_zip') {
                const defaultName = `${sanitizePathSegment(project?.name || 'project')}-${formatProfile}.zip`;
                if (runtimeCapability.isSecureContext && runtimeCapability.hasSaveFilePicker) {
                    const picker = (window as any).showSaveFilePicker;
                    const handle = await picker({
                        suggestedName: defaultName,
                        types: [{description: 'ZIP', accept: {'application/zip': ['.zip']}}],
                    });

                    await exportOneZip({
                        handle,
                        title: project?.name || projectId,
                        resolve: resolved,
                        datasetIds: selectedDatasetIds,
                        signal: resolveAbort.signal,
                    });
                } else {
                    message.warning(t('export.project.browserFallbackNotice'));
                    const blob = await exportOneZipToBlob({
                        title: project?.name || projectId,
                        resolve: resolved,
                        datasetIds: selectedDatasetIds,
                        signal: resolveAbort.signal,
                    });
                    downloadBlob(blob, defaultName);
                }
            } else {
                if (runtimeCapability.isSecureContext && runtimeCapability.hasDirectoryPicker) {
                    const picker = (window as any).showDirectoryPicker;
                    const directoryHandle = await picker();
                    for (const datasetId of selectedDatasetIds) {
                        if (resolveAbort.signal.aborted) {
                            throw new DOMException('aborted', 'AbortError');
                        }
                        const datasetName = datasetNameById.get(datasetId) || datasetId;
                        setProgress((prev) => ({...prev, currentDataset: datasetName}));
                        const fileName = `${sanitizePathSegment(datasetName)}-${formatProfile}.zip`;
                        const fileHandle = await directoryHandle.getFileHandle(fileName, {create: true});

                        await exportOneZip({
                            handle: fileHandle,
                            title: datasetName,
                            resolve: resolved,
                            datasetIds: [datasetId],
                            signal: resolveAbort.signal,
                        });
                    }
                } else {
                    message.warning(t('export.project.browserFallbackNotice'));
                    for (const datasetId of selectedDatasetIds) {
                        if (resolveAbort.signal.aborted) {
                            throw new DOMException('aborted', 'AbortError');
                        }
                        const datasetName = datasetNameById.get(datasetId) || datasetId;
                        setProgress((prev) => ({...prev, currentDataset: datasetName}));
                        const fileName = `${sanitizePathSegment(datasetName)}-${formatProfile}.zip`;
                        const blob = await exportOneZipToBlob({
                            title: datasetName,
                            resolve: resolved,
                            datasetIds: [datasetId],
                            signal: resolveAbort.signal,
                        });
                        downloadBlob(blob, fileName);
                    }
                }
            }

            setProgress((prev) => ({...prev, phase: 'done'}));
            message.success(t('export.project.done'));
        } catch (error) {
            if (isAbortError(error)) {
                setProgress((prev) => ({...prev, phase: 'canceled'}));
                message.info(t('export.project.canceled'));
            } else {
                setProgress((prev) => ({...prev, phase: 'error'}));
                message.error(error instanceof Error ? error.message : t('export.project.startFailed'));
            }
        } finally {
            setResolving(false);
            setExporting(false);
            abortRef.current = null;
            await cleanupWritables();
        }
    }, [
        projectId,
        canExport,
        runtimeCapability,
        selectedDatasetIds,
        snapshotType,
        commitId,
        buildResolvePayload,
        bundleLayout,
        datasetNameById,
        exportOneZip,
        exportOneZipToBlob,
        formatProfile,
        project,
        cleanupWritables,
        t,
    ]);

    const progressPercent = useMemo(() => {
        if (progress.samplesTotal <= 0) return 0;
        return Math.round((progress.samplesDone / progress.samplesTotal) * 100);
    }, [progress.samplesDone, progress.samplesTotal]);

    const canStart = !loadingMeta
        && !resolving
        && !exporting
        && canExport
        && exportProfiles.length > 0
        && selectedDatasetIds.length > 0;

    return (
        <div className="flex h-full min-w-0 flex-col gap-4 overflow-x-hidden pb-4">
            <Card className="!border-github-border !bg-github-panel">
                <Space align="start" className="w-full justify-between">
                    <Space align="start">
                        <Button icon={<ArrowLeftOutlined/>} onClick={() => navigate(`/projects/${projectId}`)}>
                            {t('common.back')}
                        </Button>
                        <div>
                            <Title level={4} className="!mb-1 !mt-0">{t('export.project.title')}</Title>
                            <Paragraph className="!mb-0 !text-github-muted">
                                {t('export.project.subtitle')}
                            </Paragraph>
                        </div>
                    </Space>
                    <Space>
                        <Button
                            icon={<StopOutlined/>}
                            onClick={() => {
                                void cancelRunning();
                            }}
                            disabled={!exporting && !resolving}
                        >
                            {t('common.cancel')}
                        </Button>
                        <Button
                            type="primary"
                            icon={<DownloadOutlined/>}
                            onClick={() => {
                                void handleStart();
                            }}
                            loading={resolving || exporting}
                            disabled={!canStart}
                        >
                            {t('export.project.start')}
                        </Button>
                    </Space>
                </Space>
            </Card>

            {!canExport ? (
                <Alert type="warning" showIcon message={t('common.noPermission')}/>
            ) : null}
            {!runtimeCapability.isSecureContext ? (
                <Alert type="warning" showIcon message={t('export.project.browserBlocked')}/>
            ) : null}
            {(runtimeCapability.isSecureContext && (!runtimeCapability.hasSaveFilePicker || !runtimeCapability.hasDirectoryPicker)) ? (
                <Alert type="warning" showIcon message={t('export.project.browserFallbackNotice')}/>
            ) : null}
            {exportProfiles.length === 0 ? (
                <Alert type="error" showIcon message={t('export.project.noAvailableExportProfile')}/>
            ) : null}
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[4fr_6fr]">
                <Card title={t('export.project.configTitle')} className="!border-github-border !bg-github-panel">
                    <Space direction="vertical" size={14} className="w-full">
                        <div>
                            <Text strong>{t('export.project.datasetLabel')}</Text>
                            <Checkbox.Group
                                className="mt-2 w-full"
                                value={selectedDatasetIds}
                                onChange={(values) => setSelectedDatasetIds(values.map((value) => String(value)))}
                            >
                                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                                    {datasets.map((dataset) => (
                                        <Checkbox key={dataset.id} value={dataset.id}>
                                            {dataset.name}
                                        </Checkbox>
                                    ))}
                                </div>
                            </Checkbox.Group>
                        </div>

                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <div>
                                <Text strong>{t('export.project.snapshotTypeLabel')}</Text>
                                <Radio.Group
                                    className="mt-2"
                                    value={snapshotType}
                                    onChange={(event) => setSnapshotType(event.target.value as 'branch_head' | 'commit')}
                                    options={[
                                        {label: t('export.project.snapshotBranchHead'), value: 'branch_head'},
                                        {label: t('export.project.snapshotCommit'), value: 'commit'},
                                    ]}
                                    optionType="button"
                                    buttonStyle="solid"
                                />
                            </div>
                            {snapshotType === 'branch_head' ? (
                                <div>
                                    <Text strong>{t('export.project.branchLabel')}</Text>
                                    <Select
                                        className="mt-2 w-full"
                                        value={branchName}
                                        onChange={setBranchName}
                                        options={branches.map((item) => ({label: item.name, value: item.name}))}
                                    />
                                </div>
                            ) : (
                                <div>
                                    <Text strong>{t('export.project.commitIdLabel')}</Text>
                                    <Input
                                        className="mt-2"
                                        value={commitId}
                                        onChange={(event) => setCommitId(event.target.value)}
                                        placeholder={t('export.project.commitIdPlaceholder')}
                                    />
                                </div>
                            )}
                        </div>

                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <div>
                                <Text strong>{t('export.project.sampleScopeLabel')}</Text>
                                <Select
                                    className="mt-2 w-full"
                                    value={sampleScope}
                                    onChange={(value) => setSampleScope(value as SampleScope)}
                                    options={[
                                        {label: t('export.project.sampleScopeAll'), value: 'all'},
                                        {label: t('export.project.sampleScopeLabeled'), value: 'labeled'},
                                        {label: t('export.project.sampleScopeUnlabeled'), value: 'unlabeled'},
                                    ]}
                                />
                            </div>
                            <div>
                                <Text strong>{t('export.project.formatLabel')}</Text>
                                <Select
                                    className="mt-2 w-full"
                                    value={formatProfile}
                                    onChange={(value) => setFormatProfile(value as FormatProfileId)}
                                    options={exportProfiles.map((item) => ({
                                        label: getFormatLabel(item.id as FormatProfileId),
                                        value: item.id,
                                    }))}
                                />
                            </div>
                        </div>
                        {formatProfile === 'yolo_obb' ? (
                            <div>
                                <Text strong>{t('export.project.yoloSubFormatLabel')}</Text>
                                <Select
                                    className="mt-2 w-full"
                                    value={yoloLabelFormat}
                                    onChange={(value) => setYoloLabelFormat(value as YoloLabelFormat)}
                                    options={selectedYoloLabelOptions.map((value) => ({
                                        label: value === 'obb_poly8'
                                            ? t('export.project.yoloSubFormatObbPoly8')
                                            : t('export.project.yoloSubFormatObbRbox'),
                                        value,
                                    }))}
                                />
                            </div>
                        ) : null}
                        {isPredictionsJson ? (
                            <Card size="small" title="predictions_json 选项" className="!border-github-border !bg-github-panel">
                                <Space direction="vertical" size={14} className="w-full">
                                    <div>
                                        <Text strong>保留空样本 entry</Text>
                                        <div className="mt-2">
                                            <Switch
                                                checked={predictionsJsonIncludeEmptyEntries}
                                                onChange={setPredictionsJsonIncludeEmptyEntries}
                                                checkedChildren={t('common.yes')}
                                                unCheckedChildren={t('common.no')}
                                            />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                        <div>
                                            <Text strong>Entry 追踪字段</Text>
                                            <Checkbox.Group
                                                className="mt-2 w-full"
                                                value={predictionsJsonEntryTraceFields}
                                                onChange={(values) => setPredictionsJsonEntryTraceFields(
                                                    values.map((value) => String(value) as PredictionsJSONEntryTraceField),
                                                )}
                                                options={[
                                                    {label: 'sample_id', value: 'sample_id'},
                                                    {label: 'dataset_id', value: 'dataset_id'},
                                                    {label: 'annotation_commit_id', value: 'annotation_commit_id'},
                                                    {label: 'branch_name', value: 'branch_name'},
                                                    {label: 'exported_at', value: 'exported_at'},
                                                ]}
                                            />
                                        </div>
                                        <div>
                                            <Text strong>Detection 追踪字段</Text>
                                            <Checkbox.Group
                                                className="mt-2 w-full"
                                                value={predictionsJsonDetectionTraceFields}
                                                onChange={(values) => setPredictionsJsonDetectionTraceFields(
                                                    values.map((value) => String(value) as PredictionsJSONDetectionTraceField),
                                                )}
                                                options={[
                                                    {label: 'annotation_id', value: 'annotation_id'},
                                                    {label: 'label_id', value: 'label_id'},
                                                    {label: 'source', value: 'source'},
                                                    {label: 'attrs', value: 'attrs'},
                                                ]}
                                            />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                        <div>
                                            <Text strong>Rect 兼容几何字段</Text>
                                            <Checkbox.Group
                                                className="mt-2 w-full"
                                                value={predictionsJsonRectCompatFields}
                                                onChange={(values) => setPredictionsJsonRectCompatFields(
                                                    values.map((value) => String(value) as PredictionsJSONRectCompatField),
                                                )}
                                                options={[
                                                    {label: 'xyxy', value: 'xyxy'},
                                                    {label: 'xywh', value: 'xywh'},
                                                ]}
                                            />
                                        </div>
                                        <div>
                                            <Text strong>OBB 兼容几何字段</Text>
                                            <Checkbox.Group
                                                className="mt-2 w-full"
                                                value={predictionsJsonObbCompatFields}
                                                onChange={(values) => setPredictionsJsonObbCompatFields(
                                                    values.map((value) => String(value) as PredictionsJSONObbCompatField),
                                                )}
                                                options={[
                                                    {label: 'xyxyxyxy', value: 'xyxyxyxy'},
                                                    {label: 'xywhr', value: 'xywhr'},
                                                ]}
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <Text strong>过滤条件 JSON</Text>
                                        <Paragraph className="!mb-2 !mt-1 !text-github-muted">
                                            留空表示不过滤。字段范围按后端契约，仅支持 `annotation.*` 与 `annotation.attrs.*`。
                                        </Paragraph>
                                        <TextArea
                                            className="font-mono"
                                            autoSize={{minRows: 6, maxRows: 14}}
                                            value={predictionsJsonFilterText}
                                            onChange={(event) => setPredictionsJsonFilterText(event.target.value)}
                                            placeholder={'{\n  "op": "and",\n  "items": [\n    {\n      "field": "annotation.source",\n      "operator": "in",\n      "value": ["model", "confirmed_model"]\n    }\n  ]\n}'}
                                        />
                                    </div>
                                </Space>
                            </Card>
                        ) : null}
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <div>
                                <Text strong>{t('export.project.bundleLayoutLabel')}</Text>
                                <Select
                                    className="mt-2 w-full"
                                    value={bundleLayout}
                                    onChange={(value) => setBundleLayout(value as ExportBundleLayout)}
                                    options={[
                                        {label: t('export.project.layoutMerged'), value: 'merged_zip'},
                                        {label: t('export.project.layoutPerDataset'), value: 'per_dataset_zip'},
                                    ]}
                                />
                            </div>
                            <div>
                                <Text strong>{t('export.project.includeAssetsLabel')}</Text>
                                <div className="mt-2">
                                    <Switch
                                        checked={includeAssets}
                                        onChange={setIncludeAssets}
                                        checkedChildren={t('common.yes')}
                                        unCheckedChildren={t('common.no')}
                                    />
                                </div>
                            </div>
                        </div>

                        <div>
                            <Text strong>{t('export.project.failFastLabel')}</Text>
                            <div className="mt-2">
                                <Switch
                                    checked={failFast}
                                    onChange={setFailFast}
                                    checkedChildren={t('common.yes')}
                                    unCheckedChildren={t('common.no')}
                                />
                            </div>
                        </div>
                    </Space>
                </Card>

                <Card title={t('export.project.statusTitle')} className="!border-github-border !bg-github-panel">
                    <Space direction="vertical" size={12} className="w-full">
                        <Progress
                            percent={progressPercent}
                            status={progress.phase === 'error' ? 'exception' : progress.phase === 'done' ? 'success' : 'active'}
                        />
                        <Descriptions column={1} size="small" bordered>
                            <Descriptions.Item label={t('export.project.phaseLabel')}>
                                {t(`export.project.phase.${progress.phase}`)}
                            </Descriptions.Item>
                            <Descriptions.Item label={t('export.project.samplesProgressLabel')}>
                                {progress.samplesDone} / {progress.samplesTotal}
                            </Descriptions.Item>
                            <Descriptions.Item label={t('export.project.assetsProgressLabel')}>
                                {progress.assetsDone} / {progress.assetsTotal}
                            </Descriptions.Item>
                            {progress.currentDataset ? (
                                <Descriptions.Item label={t('export.project.currentDatasetLabel')}>
                                    {progress.currentDataset}
                                </Descriptions.Item>
                            ) : null}
                        </Descriptions>

                        {resolveResult ? (
                            <>
                                <Divider className="!my-2"/>
                                <Descriptions column={1} size="small" bordered>
                                    <Descriptions.Item label={t('export.project.resolveCommitLabel')}>
                                        <Text copyable>{resolveResult.resolvedCommitId}</Text>
                                    </Descriptions.Item>
                                    <Descriptions.Item label={t('export.project.formatCompatibilityLabel')}>
                                        <Tag color={resolveResult.formatCompatibility === 'ok' ? 'green' : 'red'}>
                                            {resolveResult.formatCompatibility}
                                        </Tag>
                                    </Descriptions.Item>
                                    <Descriptions.Item label={t('export.project.estimatedSizeLabel')}>
                                        {formatSize(estimatedTotalBytes)}
                                    </Descriptions.Item>
                                    <Descriptions.Item label={t('export.project.blockedLabel')}>
                                        {resolveResult.blocked ? <Tag color="red">{t('common.yes')}</Tag> : <Tag color="green">{t('common.no')}</Tag>}
                                    </Descriptions.Item>
                                </Descriptions>
                                {resolveResult.blockReason ? (
                                    <Alert type="error" showIcon message={`${t('export.project.blockReasonLabel')}: ${resolveResult.blockReason}`}/>
                                ) : null}
                                {resolveResult.suggestions?.length ? (
                                    <Alert
                                        type="info"
                                        showIcon
                                        message={resolveResult.suggestions.join('；')}
                                    />
                                ) : null}
                            </>
                        ) : null}

                        {report.length > 0 ? (
                            <>
                                <Divider className="!my-2"/>
                                <Text strong>{t('export.project.reportTitle')}</Text>
                                <div className="max-h-56 overflow-auto rounded border border-github-border bg-github-base p-2 text-xs">
                                    {report.map((item, index) => (
                                        <div key={`${index}-${item}`}>{item}</div>
                                    ))}
                                </div>
                            </>
                        ) : null}
                    </Space>
                </Card>
            </div>

            {selectedDatasets.length > 0 ? (
                <Card title={t('export.project.selectedDatasetsTitle')} className="!border-github-border !bg-github-panel">
                    <Space wrap>
                        {selectedDatasets.map((dataset) => (
                            <Tag key={dataset.id} color="blue">{dataset.name}</Tag>
                        ))}
                    </Space>
                </Card>
            ) : null}
        </div>
    );
};

export default ProjectExportWorkspace;
