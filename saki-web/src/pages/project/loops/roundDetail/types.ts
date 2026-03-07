import {RuntimeStep} from '../../../../types';

export type RoundStageKey = 'train' | 'eval' | 'score' | 'select' | 'custom';

export type ConsoleStageFilter = 'all' | RoundStageKey;

export interface RoundStageSnapshot {
    key: RoundStageKey;
    label: string;
    steps: RuntimeStep[];
    representativeStep: RuntimeStep | null;
    totalDurationSec: number;
    representativeDurationSec: number;
    stateSummary: string;
    metricSummary: Record<string, any>;
}

export interface RoundArtifactTableRow {
    key: string;
    stage: string;
    stageLabel: string;
    artifactClass: string;
    artifactClassLabel: string;
    stepId: string;
    taskId: string;
    stepIndex: number;
    name: string;
    kind: string;
    size?: number | null;
    createdAt?: string | null;
}
