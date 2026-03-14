import type {PredictionRead, ProjectBranch} from '../../../../types';
import {
    resolvePredictionApplyBranchId,
    resolvePredictionApplyBranchName,
} from '../predictionApplyBranch';

const branches: ProjectBranch[] = [
    {
        id: 'branch-master',
        name: 'master',
        headCommitId: 'commit-master',
        isProtected: true,
    },
    {
        id: 'branch-feature',
        name: 'feature/predict',
        headCommitId: 'commit-feature',
        isProtected: false,
    },
];

const prediction = {
    id: 'prediction-1',
    projectId: 'project-1',
    pluginId: 'yolo_det_v1',
    modelId: 'model-1',
    targetBranchId: 'branch-feature',
    targetBranchName: 'feature/predict',
    taskId: 'task-1',
    scopeType: 'sample_status',
    scopePayload: {},
    status: 'ready',
    totalItems: 12,
    params: {},
    createdAt: '',
    updatedAt: '',
} satisfies PredictionRead;

const selected = resolvePredictionApplyBranchId(prediction, branches);
if (selected !== 'branch-feature') {
    throw new Error(`expected feature branch to be selected by default, got ${selected}`);
}

const fallbackPrediction: PredictionRead = {
    ...prediction,
    targetBranchId: 'missing-branch',
    targetBranchName: 'missing',
};

const fallbackSelected = resolvePredictionApplyBranchId(fallbackPrediction, branches);
if (fallbackSelected !== 'branch-master') {
    throw new Error(`expected first branch fallback, got ${fallbackSelected}`);
}

const branchName = resolvePredictionApplyBranchName('branch-feature', branches);
if (branchName !== 'feature/predict') {
    throw new Error(`expected branch name lookup to return feature/predict, got ${branchName}`);
}
