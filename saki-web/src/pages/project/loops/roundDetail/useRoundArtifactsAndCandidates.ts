import {useCallback, useEffect, useRef, useState} from 'react';

import {
    RuntimeRound,
    RuntimeRoundArtifact,
    RuntimeStep,
    RuntimeStepCandidate,
    RuntimeStepMetricPoint,
} from '../../../../types';
import {api} from '../../../../services/api';
import {buildArtifactKey} from './transforms';

interface UseRoundArtifactsAndCandidatesOptions {
    canManageLoops: boolean;
    round: RuntimeRound | null;
    trainStep: RuntimeStep | null;
    selectStep: RuntimeStep | null;
    scoreStep: RuntimeStep | null;
}

export const useRoundArtifactsAndCandidates = ({
    canManageLoops,
    round,
    trainStep,
    selectStep,
    scoreStep,
}: UseRoundArtifactsAndCandidatesOptions) => {
    const [trainMetricPoints, setTrainMetricPoints] = useState<RuntimeStepMetricPoint[]>([]);
    const [topkCandidates, setTopkCandidates] = useState<RuntimeStepCandidate[]>([]);
    const [topkSource, setTopkSource] = useState('-');
    const [roundArtifacts, setRoundArtifacts] = useState<RuntimeRoundArtifact[]>([]);
    const [artifactUrls, setArtifactUrls] = useState<Record<string, string>>({});
    const artifactUrlsRef = useRef<Record<string, string>>({});

    useEffect(() => {
        artifactUrlsRef.current = artifactUrls;
    }, [artifactUrls]);

    const ensureArtifactUrls = useCallback(async (items: RuntimeRoundArtifact[]) => {
        if (!items || items.length === 0) return;
        const currentMap = artifactUrlsRef.current;
        const missing = items.filter((item) => !currentMap[buildArtifactKey(item.stepId, item.name)]);
        if (missing.length === 0) return;

        const updates: Record<string, string> = {};
        for (const artifact of missing) {
            const key = buildArtifactKey(artifact.stepId, artifact.name);
            const uri = String(artifact.uri || '');
            if (uri.startsWith('http://') || uri.startsWith('https://')) {
                updates[key] = uri;
                continue;
            }
            if (!uri.startsWith('s3://')) continue;
            try {
                const row = await api.getStepArtifactDownloadUrl(artifact.stepId, artifact.name, 2);
                updates[key] = row.downloadUrl;
            } catch {
                // ignore unavailable artifacts
            }
        }

        if (Object.keys(updates).length > 0) {
            setArtifactUrls((prev) => ({...prev, ...updates}));
        }
    }, []);

    useEffect(() => {
        if (!canManageLoops || !round) return;
        let cancelled = false;

        const run = async () => {
            const trainPromise = trainStep?.id
                ? api.getStepMetricSeries(trainStep.id, 5000).catch(() => [])
                : Promise.resolve([]);

            const roundArtifactsPromise = api.getRoundArtifacts(round.id, 2000).catch(() => ({
                roundId: round.id,
                items: [] as RuntimeRoundArtifact[],
            }));

            const [trainPoints, roundArtifactsResp] = await Promise.all([trainPromise, roundArtifactsPromise]);

            if (cancelled) return;

            const roundArtifactItems = [...(roundArtifactsResp.items || [])].sort(
                (left, right) => Number(left.stepIndex || 0) - Number(right.stepIndex || 0),
            );

            setTrainMetricPoints(trainPoints);
            setRoundArtifacts(roundArtifactItems);
            void ensureArtifactUrls(roundArtifactItems);

            if (round.mode === 'manual') {
                setTopkCandidates([]);
                setTopkSource('-');
                return;
            }

            let rows: RuntimeStepCandidate[] = [];
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
            if (!selectionResolved && rows.length === 0 && selectStep?.id) {
                try {
                    rows = await api.getStepCandidates(selectStep.id, 500);
                    source = 'SELECT Step';
                } catch {
                    // ignore
                }
            }
            if (!selectionResolved && rows.length === 0 && scoreStep?.id) {
                try {
                    rows = await api.getStepCandidates(scoreStep.id, 500);
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
        trainStep?.id,
        trainStep?.updatedAt,
        selectStep?.id,
        selectStep?.updatedAt,
        selectStep?.state,
        scoreStep?.id,
        scoreStep?.updatedAt,
        scoreStep?.state,
        ensureArtifactUrls,
    ]);

    return {
        trainMetricPoints,
        setTrainMetricPoints,
        topkCandidates,
        topkSource,
        roundArtifacts,
        setRoundArtifacts,
        artifactUrls,
        ensureArtifactUrls,
    };
};
