import type {Loop, ProjectModel, RuntimeRound} from '../../../types';

type LoopPredictionContext = Pick<Loop, 'latestModelId' | 'modelArch'>;
type RoundPredictionContext = Pick<RuntimeRound, 'id' | 'pluginId'>;

function text(value: unknown): string {
    return String(value || '').trim();
}

export function resolvePredictionTargetModel(
    loop: LoopPredictionContext | null | undefined,
    latestRound: RoundPredictionContext | null | undefined,
    models: ProjectModel[],
): ProjectModel | null {
    const latestModelId = text(loop?.latestModelId);
    if (latestModelId) {
        const byId = models.find((item) => text(item.id) === latestModelId);
        if (byId) {
            return byId;
        }
    }

    const roundId = text(latestRound?.id);
    if (roundId) {
        const byRound = models.find((item) => text(item.sourceRoundId) === roundId);
        if (byRound) {
            return byRound;
        }
    }

    const pluginId = text(latestRound?.pluginId || loop?.modelArch);
    if (!pluginId) {
        return null;
    }
    return models.find((item) => text(item.pluginId) === pluginId) || null;
}
