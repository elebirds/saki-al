import {LoopLifecycle} from '../../../types';

const DELETABLE_LIFECYCLES: ReadonlySet<LoopLifecycle> = new Set<LoopLifecycle>([
    'draft',
    'stopped',
    'completed',
    'failed',
]);

export const isLoopDeletable = (lifecycle: LoopLifecycle | string | null | undefined): boolean => {
    const text = String(lifecycle || '').trim().toLowerCase() as LoopLifecycle;
    return DELETABLE_LIFECYCLES.has(text);
};
