import {useCallback, useEffect, useRef, useState} from 'react';

import {RuntimeRound, RuntimeStep} from '../../../../types';
import {api} from '../../../../services/api';
import {ROUND_META_REFRESH_THROTTLE_MS} from './constants';

export interface RoundDetailMessageApi {
    error: (...args: any[]) => void;
    success: (...args: any[]) => void;
}

interface UseRoundCoreDataOptions {
    canManageLoops: boolean;
    roundId?: string;
    loopId?: string;
    messageApi: RoundDetailMessageApi;
}

export const useRoundCoreData = ({
    canManageLoops,
    roundId,
    loopId,
    messageApi,
}: UseRoundCoreDataOptions) => {
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [retrying, setRetrying] = useState(false);
    const [round, setRound] = useState<RuntimeRound | null>(null);
    const [steps, setSteps] = useState<RuntimeStep[]>([]);
    const metaRefreshTimerRef = useRef<number | null>(null);

    const loadRoundData = useCallback(async (silent: boolean = false) => {
        if (!roundId || !canManageLoops) return;
        if (!silent) setLoading(true);
        if (silent) setRefreshing(true);
        try {
            const [roundRow, stepRows] = await Promise.all([
                api.getRound(roundId),
                api.getRoundSteps(roundId, 2000),
            ]);
            setRound(roundRow);
            setSteps(stepRows);
        } catch (error: any) {
            messageApi.error(error?.message || '加载 Round 详情失败');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [roundId, canManageLoops, messageApi]);

    const scheduleRoundMetaRefresh = useCallback(() => {
        if (metaRefreshTimerRef.current != null) return;
        metaRefreshTimerRef.current = window.setTimeout(() => {
            metaRefreshTimerRef.current = null;
            void loadRoundData(true);
        }, ROUND_META_REFRESH_THROTTLE_MS);
    }, [loadRoundData]);

    const handleRetryRound = useCallback(async () => {
        if (!round || !loopId) return;
        setRetrying(true);
        try {
            await api.actLoop(loopId, {
                action: 'retry_round',
                payload: {roundId: round.id, reason: 'round detail retry'},
            });
            messageApi.success('已触发重跑');
            await loadRoundData(false);
        } catch (error: any) {
            messageApi.error(error?.message || '重跑失败');
        } finally {
            setRetrying(false);
        }
    }, [round, loopId, messageApi, loadRoundData]);

    useEffect(() => {
        if (!canManageLoops) return;
        void loadRoundData(false);
    }, [canManageLoops, loadRoundData]);

    useEffect(() => {
        return () => {
            if (metaRefreshTimerRef.current != null) {
                window.clearTimeout(metaRefreshTimerRef.current);
                metaRefreshTimerRef.current = null;
            }
        };
    }, []);

    return {
        loading,
        refreshing,
        retrying,
        round,
        steps,
        setSteps,
        loadRoundData,
        scheduleRoundMetaRefresh,
        handleRetryRound,
    };
};
