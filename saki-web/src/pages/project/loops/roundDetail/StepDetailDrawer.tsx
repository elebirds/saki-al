import React from 'react';
import {Descriptions, Drawer, Empty, Tag} from 'antd';

import {RuntimeStep} from '../../../../types';
import {STEP_STATE_COLOR} from './constants';
import {computeDurationMs, formatDateTime, formatDuration} from '../runtimeTime';

interface StepDetailDrawerProps {
    open: boolean;
    onClose: () => void;
    step: RuntimeStep | null;
    nowMs: number;
}

const StepDetailDrawer: React.FC<StepDetailDrawerProps> = ({open, onClose, step, nowMs}) => {
    return (
        <Drawer
            open={open}
            onClose={onClose}
            width={560}
            title={step ? `Step #${step.stepIndex} · ${step.stepType}` : 'Step 详情'}
        >
            {!step ? (
                <Empty description="暂无选中 Step"/>
            ) : (
                <Descriptions size="small" column={1}>
                    <Descriptions.Item label="Step ID">{step.id}</Descriptions.Item>
                    <Descriptions.Item label="类型">{step.stepType}</Descriptions.Item>
                    <Descriptions.Item label="状态">
                        <Tag color={STEP_STATE_COLOR[step.state] || 'default'}>{step.state}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="执行器">{step.assignedExecutorId || '-'}</Descriptions.Item>
                    <Descriptions.Item label="Attempt">{`${step.attempt || 1}/${step.maxAttempts || 1}`}</Descriptions.Item>
                    <Descriptions.Item label="开始时间">{formatDateTime(step.startedAt)}</Descriptions.Item>
                    <Descriptions.Item label="结束时间">{formatDateTime(step.endedAt)}</Descriptions.Item>
                    <Descriptions.Item label="运行时长">
                        {formatDuration(computeDurationMs(step.startedAt, step.endedAt, nowMs))}
                    </Descriptions.Item>
                    <Descriptions.Item label="依赖 Step">
                        {(step.dependsOnStepIds || []).length > 0
                            ? (step.dependsOnStepIds || []).map((item) => <Tag key={item}>{item}</Tag>)
                            : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="错误信息">{step.lastError || '-'}</Descriptions.Item>
                </Descriptions>
            )}
        </Drawer>
    );
};

export default StepDetailDrawer;
