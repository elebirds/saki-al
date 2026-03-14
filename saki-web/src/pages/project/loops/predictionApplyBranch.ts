import type {PredictionRead, ProjectBranch} from '../../../types';

export function resolvePredictionApplyBranchId(
    prediction: Pick<PredictionRead, 'targetBranchId'> | null | undefined,
    branches: ProjectBranch[],
): string {
    const targetBranchId = String(prediction?.targetBranchId || '').trim();
    if (targetBranchId && branches.some((item) => item.id === targetBranchId)) {
        return targetBranchId;
    }
    return String(branches[0]?.id || '').trim();
}

export function resolvePredictionApplyBranchName(
    branchId: string,
    branches: ProjectBranch[],
): string {
    const hit = branches.find((item) => item.id === branchId);
    return String(hit?.name || '').trim();
}
