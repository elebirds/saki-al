import {useCallback, useEffect, useState} from 'react';
import {api} from '../../services/api';
import {ProjectSample} from '../../types';

export interface ProjectSampleFilters {
    q?: string;
    status?: 'all' | 'labeled' | 'unlabeled' | 'draft';
    branchName?: string;
    sortBy?: string;
    sortOrder?: 'asc' | 'desc';
    page?: number;
    limit?: number;
    runtimeScope?: 'round_missing_labels';
    runtimeLoopId?: string;
    runtimeRoundId?: string;
}

export interface ProjectSampleListMeta {
    total: number;
    limit: number;
    offset: number;
    size: number;
    hasMore?: boolean;
}

export interface UseProjectSampleListOptions {
    projectId?: string;
    datasetId?: string;
    filters: ProjectSampleFilters;
    enabled?: boolean;
}

export function useProjectSampleList(options: UseProjectSampleListOptions) {
    const {projectId, datasetId, filters, enabled = true} = options;
    const {
        q,
        status,
        branchName,
        sortBy,
        sortOrder,
        page,
        limit,
        runtimeScope,
        runtimeLoopId,
        runtimeRoundId,
    } = filters;
    const [samples, setSamples] = useState<ProjectSample[]>([]);
    const [meta, setMeta] = useState<ProjectSampleListMeta>({
        total: 0,
        limit: limit || 24,
        offset: 0,
        size: 0,
    });
    const [loading, setLoading] = useState(false);

    const load = useCallback(async () => {
        if (!projectId || !datasetId || !enabled) return;
        setLoading(true);
        try {
            const isRoundMissingScope = runtimeScope === 'round_missing_labels' && !!runtimeLoopId && !!runtimeRoundId;
            const response = isRoundMissingScope
                ? await api.getRoundMissingSamples(runtimeLoopId!, runtimeRoundId!, {
                    datasetId: datasetId || undefined,
                    q,
                    sortBy,
                    sortOrder,
                    page,
                    limit,
                })
                : await api.getProjectSamples(projectId, datasetId, {
                    q,
                    status,
                    branchName,
                    sortBy,
                    sortOrder,
                    page,
                    limit,
                });
            setSamples(response.items || []);
            setMeta({
                total: response.total,
                limit: response.limit,
                offset: response.offset,
                size: response.size,
                hasMore: response.hasMore,
            });
        } finally {
            setLoading(false);
        }
    }, [
        projectId,
        datasetId,
        enabled,
        q,
        status,
        branchName,
        sortBy,
        sortOrder,
        page,
        limit,
        runtimeScope,
        runtimeLoopId,
        runtimeRoundId,
    ]);

    useEffect(() => {
        load();
    }, [load]);

    return {
        samples,
        meta,
        loading,
        reload: load,
    };
}
