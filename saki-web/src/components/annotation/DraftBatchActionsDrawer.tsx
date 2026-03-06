import React from 'react';
import {Button, Card, Drawer, Space, Tag, Typography} from 'antd';
import {useTranslation} from 'react-i18next';
import {AnnotationDraftBatchOperationType, AnnotationDraftBatchResult} from '../../types';

const OPERATION_ORDER: AnnotationDraftBatchOperationType[] = [
    'confirm_model_annotations',
    'clear_unconfirmed_model_annotations',
    'clear_drafts',
];

export interface DraftBatchActionsDrawerProps {
    open: boolean;
    onClose: () => void;
    canAnnotate: boolean;
    onConfirmSelected: () => void;
    confirmSelectedDisabled: boolean;
    onRunBatchOperation: (operation: AnnotationDraftBatchOperationType) => void;
    runningOperation?: AnnotationDraftBatchOperationType | null;
    previewResults?: Partial<Record<AnnotationDraftBatchOperationType, AnnotationDraftBatchResult>>;
}

function isDangerOperation(operation: AnnotationDraftBatchOperationType): boolean {
    return operation === 'clear_unconfirmed_model_annotations' || operation === 'clear_drafts';
}

export const DraftBatchActionsDrawer: React.FC<DraftBatchActionsDrawerProps> = ({
    open,
    onClose,
    canAnnotate,
    onConfirmSelected,
    confirmSelectedDisabled,
    onRunBatchOperation,
    runningOperation,
    previewResults,
}) => {
    const {t} = useTranslation();

    const operationMeta = (operation: AnnotationDraftBatchOperationType) => {
        if (operation === 'confirm_model_annotations') {
            return {
                title: t('annotation.workspace.batch.ops.confirmModel.title'),
                description: t('annotation.workspace.batch.ops.confirmModel.desc'),
            };
        }
        if (operation === 'clear_unconfirmed_model_annotations') {
            return {
                title: t('annotation.workspace.batch.ops.clearUnconfirmed.title'),
                description: t('annotation.workspace.batch.ops.clearUnconfirmed.desc'),
            };
        }
        return {
            title: t('annotation.workspace.batch.ops.clearDrafts.title'),
            description: t('annotation.workspace.batch.ops.clearDrafts.desc'),
        };
    };

    return (
        <Drawer
            open={open}
            onClose={onClose}
            title={t('annotation.workspace.batch.drawerTitle')}
            width={460}
            destroyOnClose
        >
            <Space direction="vertical" size={16} className="w-full">
                <Card size="small" title={t('annotation.workspace.batch.currentSampleTitle')}>
                    <Space direction="vertical" size={8} className="w-full">
                        <Typography.Text type="secondary">
                            {t('annotation.workspace.batch.currentSampleDesc')}
                        </Typography.Text>
                        <Button
                            block
                            onClick={onConfirmSelected}
                            disabled={!canAnnotate || confirmSelectedDisabled}
                        >
                            {t('annotation.workspace.confirmSelected')}
                        </Button>
                    </Space>
                </Card>

                <Card size="small" title={t('annotation.workspace.batch.filteredScopeTitle')}>
                    <Space direction="vertical" size={12} className="w-full">
                        <Typography.Text type="secondary">
                            {t('annotation.workspace.batch.filteredScopeDesc')}
                        </Typography.Text>
                        {OPERATION_ORDER.map((operation) => {
                            const meta = operationMeta(operation);
                            const preview = previewResults?.[operation];
                            return (
                                <div key={operation} className="rounded border border-github-border p-3">
                                    <Space direction="vertical" size={8} className="w-full">
                                        <Typography.Text strong>{meta.title}</Typography.Text>
                                        <Typography.Text type="secondary">{meta.description}</Typography.Text>
                                        {preview ? (
                                            <Space size={8} wrap>
                                                <Tag color="blue">
                                                    {t('annotation.workspace.batch.preview.samples', {count: preview.matchedSampleCount})}
                                                </Tag>
                                                <Tag color="gold">
                                                    {t('annotation.workspace.batch.preview.drafts', {count: preview.affectedDraftCount})}
                                                </Tag>
                                                <Tag color="purple">
                                                    {t('annotation.workspace.batch.preview.annotations', {count: preview.affectedAnnotationCount})}
                                                </Tag>
                                            </Space>
                                        ) : null}
                                        <Button
                                            block
                                            danger={isDangerOperation(operation)}
                                            loading={runningOperation === operation}
                                            disabled={!canAnnotate}
                                            onClick={() => onRunBatchOperation(operation)}
                                        >
                                            {t('annotation.workspace.batch.previewAndRun')}
                                        </Button>
                                    </Space>
                                </div>
                            );
                        })}
                    </Space>
                </Card>
            </Space>
        </Drawer>
    );
};

export default DraftBatchActionsDrawer;
