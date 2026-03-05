import {RoundStageKey} from './types';

export const ROUND_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    completed: 'success',
    failed: 'error',
    cancelled: 'warning',
};

export const STEP_STATE_COLOR: Record<string, string> = {
    pending: 'default',
    ready: 'processing',
    dispatching: 'processing',
    syncing_env: 'processing',
    probing_runtime: 'processing',
    binding_device: 'processing',
    running: 'processing',
    retrying: 'warning',
    succeeded: 'success',
    failed: 'error',
    cancelled: 'warning',
    skipped: 'default',
};

export const MAX_EVENT_BUFFER = 20000;
export const ROUND_EVENT_SYNC_LIMIT = 5000;
export const ROUND_META_REFRESH_THROTTLE_MS = 2000;
export const TERMINAL_STEP_STATES = new Set(['succeeded', 'failed', 'cancelled', 'skipped']);

export const STAGE_LABEL: Record<RoundStageKey, string> = {
    train: '训练',
    eval: '评估',
    score: '评分',
    select: '选样',
    custom: '自定义',
};

export const FINAL_METRIC_SOURCE_LABEL: Record<'eval' | 'train' | 'other' | 'none', string> = {
    eval: 'Eval(Test)',
    train: 'Train',
    other: 'Other Step',
    none: 'None',
};

export const ARTIFACT_CLASS_LABEL: Record<string, string> = {
    model_artifact: '模型',
    eval_artifact: '评估',
    selection_artifact: '选样',
    prediction_artifact: '预测',
    generic_artifact: '通用',
};

export const TRAIN_METRIC_COLORS = ['#1677ff', '#52c41a', '#faad14', '#13c2c2', '#eb2f96'];
export const LOSS_METRIC_NAME_RE = /loss/i;

export const MODE_STAGE_ORDER: Record<string, RoundStageKey[]> = {
    active_learning: ['train', 'eval', 'score', 'select', 'custom'],
    simulation: ['train', 'eval', 'score', 'select', 'custom'],
    manual: ['train', 'eval', 'custom'],
};
