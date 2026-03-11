import type {ProjectModel} from '../../../../types';
import {resolvePredictionTargetModel} from '../predictionModelSelection';

const models: ProjectModel[] = [
    {
        id: 'model-plugin-fallback',
        projectId: 'project-1',
        sourceRoundId: 'round-older',
        sourceTaskId: null,
        sourceCommitId: null,
        parentModelId: null,
        pluginId: 'yolo_det_v1',
        modelArch: 'yolo_det_v1',
        name: 'fallback',
        versionTag: 'v1',
        primaryArtifactName: 'best.pt',
        weightsPath: '/tmp/fallback.pt',
        status: 'ready',
        metrics: {},
        artifacts: {},
        publishManifest: {},
        promotedAt: null,
        createdBy: null,
        createdAt: '',
        updatedAt: '',
    },
    {
        id: 'model-round-match',
        projectId: 'project-1',
        sourceRoundId: 'round-current',
        sourceTaskId: null,
        sourceCommitId: null,
        parentModelId: null,
        pluginId: 'yolo_det_v1',
        modelArch: 'yolo_det_v1',
        name: 'round-match',
        versionTag: 'v2',
        primaryArtifactName: 'best.pt',
        weightsPath: '/tmp/round.pt',
        status: 'ready',
        metrics: {},
        artifacts: {},
        publishManifest: {},
        promotedAt: null,
        createdBy: null,
        createdAt: '',
        updatedAt: '',
    },
    {
        id: 'model-latest-id',
        projectId: 'project-1',
        sourceRoundId: 'round-other',
        sourceTaskId: null,
        sourceCommitId: null,
        parentModelId: null,
        pluginId: 'yolo_det_v1',
        modelArch: 'yolo_det_v1',
        name: 'latest-id',
        versionTag: 'v3',
        primaryArtifactName: 'best.pt',
        weightsPath: '/tmp/latest.pt',
        status: 'ready',
        metrics: {},
        artifacts: {},
        publishManifest: {},
        promotedAt: null,
        createdBy: null,
        createdAt: '',
        updatedAt: '',
    },
];

const exactByLatestModelId = resolvePredictionTargetModel(
    {
        latestModelId: 'model-latest-id',
        modelArch: 'yolo_det_v1',
    },
    {
        id: 'round-current',
        pluginId: 'yolo_det_v1',
    },
    models,
);

if (exactByLatestModelId?.id !== 'model-latest-id') {
    throw new Error(`expected latestModelId match, got ${JSON.stringify(exactByLatestModelId)}`);
}

const exactByRoundId = resolvePredictionTargetModel(
    {
        latestModelId: null,
        modelArch: 'yolo_det_v1',
    },
    {
        id: 'round-current',
        pluginId: 'yolo_det_v1',
    },
    models,
);

if (exactByRoundId?.id !== 'model-round-match') {
    throw new Error(`expected round match, got ${JSON.stringify(exactByRoundId)}`);
}

const fallbackByPlugin = resolvePredictionTargetModel(
    {
        latestModelId: null,
        modelArch: 'yolo_det_v1',
    },
    {
        id: '',
        pluginId: 'yolo_det_v1',
    },
    [models[0]!],
);

if (fallbackByPlugin?.id !== 'model-plugin-fallback') {
    throw new Error(`expected plugin fallback, got ${JSON.stringify(fallbackByPlugin)}`);
}
