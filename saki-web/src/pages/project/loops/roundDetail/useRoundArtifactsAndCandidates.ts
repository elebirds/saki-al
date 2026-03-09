import {useCallback, useEffect, useRef, useState} from 'react';

import {
    RuntimeRound,
    RuntimeRoundArtifact,
    RuntimeStep,
    RuntimeTaskCandidate,
    RuntimeTaskMetricPoint,
} from '../../../../types';
import {api} from '../../../../services/api';
import {buildArtifactKey} from './transforms';

interface UseRoundArtifactsAndCandidatesOptions {
    canManageLoops: boolean;
    round: RuntimeRound | null;
    trainStep: RuntimeStep | null;
    evalStep: RuntimeStep | null;
    selectStep: RuntimeStep | null;
    scoreStep: RuntimeStep | null;
}

export const useRoundArtifactsAndCandidates = ({
    canManageLoops,
    round,
    trainStep,
    evalStep,
    selectStep,
    scoreStep,
}: UseRoundArtifactsAndCandidatesOptions) => {
    const [trainMetricPoints, setTrainMetricPoints] = useState<RuntimeTaskMetricPoint[]>([]);
    const [evalMetricPoints, setEvalMetricPoints] = useState<RuntimeTaskMetricPoint[]>([]);
    const [topkCandidates, setTopkCandidates] = useState<RuntimeTaskCandidate[]>([]);
    const [topkSource, setTopkSource] = useState('-');
    const [roundArtifacts, setRoundArtifacts] = useState<RuntimeRoundArtifact[]>([]);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});
    const artifactUrlsRef = useRef<Record<string, string>>({});

    useEffect(() => {
        artifactUrlsRef.current = artifactUrls;
    }, [artifactUrls]);

    const resolveArtifactUrl = useCallback(async (
        row: {taskId: string; name: string; uri?: string | null},
    ): Promise<string | null> => {
        const taskId = String(row.taskId || '').trim();
        const artifactName = String(row.name || '').trim();
        if (!taskId || !artifactName) return null;
        const key = buildArtifactKey(taskId, artifactName);
        const cached = artifactUrlsRef.current[key];
        if (cached) return cached;

        const uri = String(row.uri || '').trim();
        if (uri.startsWith('http://') || uri.startsWith('https://')) {
            setArtifactUrls((prev) => ({...prev, [key]: uri}));
            return uri;
        }

        const download = await api.getTaskArtifactDownloadUrl(taskId, artifactName, 2);
        const resolved = String(download.downloadUrl || '').trim();
        if (!resolved) return null;
        setArtifactUrls((prev) => ({...prev, [key]: resolved}));
        return resolved;
    }, []);

    useEffect(() => {
        if (!canManageLoops || !round) return;
        let cancelled = false;

        const run = async () => {
            const trainTaskId = String(trainStep?.taskId || '').trim();
            const evalTaskId = String(evalStep?.taskId || '').trim();
            const selectTaskId = String(selectStep?.taskId || '').trim();
            const scoreTaskId = String(scoreStep?.taskId || '').trim();
            const trainPromise = trainTaskId
                ? api.getTaskMetricSeries(trainTaskId, 5000).catch(() => [])
                : Promise.resolve([]);
            const evalPromise = evalTaskId
                ? api.getTaskMetricSeries(evalTaskId, 5000).catch(() => [])
                : Promise.resolve([]);

            const roundArtifactsPromise = api.getRoundArtifacts(round.id, 2000).catch(() => ({
                roundId: round.id,
                items: [] as RuntimeRoundArtifact[],
            }));

            const [trainPoints, evalPoints, roundArtifactsResp] = await Promise.all([
                trainPromise,
                evalPromise,
                roundArtifactsPromise,
            ]);

            if (cancelled) return;

            const roundArtifactItems = [...(roundArtifactsResp.items || [])].sort(
                (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
            );

            setTrainMetricPoints(trainPoints);
            setEvalMetricPoints(evalPoints);
            setRoundArtifacts(roundArtifactItems);

            if (round.mode === 'manual') {
                setTopkCandidates([]);
                setTopkSource('-');
                return;
            }

            let rows: RuntimeTaskCandidate[] = [];
            let source = '-';
            let selectionResolved = false;
            if (round.mode === 'active_learning') {
                try {
                    const selection = await api.getRoundSelection(round.id);
                    rows = selection.effectiveSelected || [];
                    source = 'Round Selection';
                    selectionResolved = true;
                } catch {
                    // latest round/phase constraints may reject history round, fallback below
                }
            }
            if (!selectionResolved && rows.length === 0 && selectTaskId && String(selectStep?.state || '').toLowerCase() === 'succeeded') {
                try {
                    rows = await api.getTaskCandidates(selectTaskId, 500);
                    source = 'SELECT Step';
                } catch {
                    // ignore
                }
            }
            if (!selectionResolved && rows.length === 0 && scoreTaskId && String(scoreStep?.state || '').toLowerCase() === 'succeeded') {
                try {
                    rows = await api.getTaskCandidates(scoreTaskId, 500);
                    source = 'SCORE Step';
                } catch {
                    // ignore
                }
            }
            if (!cancelled) {
                setTopkCandidates(rows);
                setTopkSource(source);
            }
        };

        void run();
        return () => {
            cancelled = true;
        };
    }, [
        canManageLoops,
        round?.id,
        round?.mode,
        trainStep?.taskId,
        trainStep?.updatedAt,
        evalStep?.taskId,
        evalStep?.updatedAt,
        selectStep?.taskId,
        selectStep?.updatedAt,
        selectStep?.state,
        scoreStep?.taskId,
        scoreStep?.updatedAt,
        scoreStep?.state,
    ]);

    return {
        trainMetricPoints,
        setTrainMetricPoints,
        evalMetricPoints,
        setEvalMetricPoints,
        topkCandidates,
        topkSource,
        roundArtifacts,
        setRoundArtifacts,
        artifactUrls,
        resolveArtifactUrl,
    };
};
