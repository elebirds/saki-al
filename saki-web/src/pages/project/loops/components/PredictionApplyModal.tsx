import React, {useEffect, useMemo, useState} from 'react';
import {Alert, Modal, Select, Typography} from 'antd';
import {useTranslation} from 'react-i18next';
import {api} from '../../../../services/api';
import type {PredictionRead, ProjectBranch} from '../../../../types';
import {resolvePredictionApplyBranchId} from '../predictionApplyBranch';

interface PredictionApplyModalProps {
    open: boolean;
    projectId?: string;
    prediction: Pick<PredictionRead, 'id' | 'targetBranchId' | 'targetBranchName'> | null;
    confirmLoading?: boolean;
    onCancel: () => void;
    onConfirm: (branchId: string, branchName: string) => void | Promise<void>;
}

const PredictionApplyModal: React.FC<PredictionApplyModalProps> = ({
    open,
    projectId,
    prediction,
    confirmLoading = false,
    onCancel,
    onConfirm,
}) => {
    const {t} = useTranslation();
    const [branches, setBranches] = useState<ProjectBranch[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedBranchId, setSelectedBranchId] = useState('');

    useEffect(() => {
        if (!open || !projectId) return;
        let active = true;
        setLoading(true);
        void api.getProjectBranches(projectId)
            .then((rows) => {
                if (!active) return;
                const nextBranches = Array.isArray(rows) ? rows : [];
                setBranches(nextBranches);
                setSelectedBranchId(resolvePredictionApplyBranchId(prediction, nextBranches));
            })
            .catch(() => {
                if (!active) return;
                setBranches([]);
                setSelectedBranchId('');
            })
            .finally(() => {
                if (active) {
                    setLoading(false);
                }
            });
        return () => {
            active = false;
        };
    }, [open, projectId, prediction]);

    const selectedBranch = useMemo(
        () => branches.find((item) => item.id === selectedBranchId) || null,
        [branches, selectedBranchId],
    );

    return (
        <Modal
            title={t('project.predictionTasks.applyModal.title')}
            open={open}
            onCancel={onCancel}
            okText={t('project.predictionTasks.applyModal.okText')}
            confirmLoading={confirmLoading}
            okButtonProps={{disabled: !selectedBranchId}}
            onOk={() => {
                if (!selectedBranch) return;
                void onConfirm(selectedBranch.id, selectedBranch.name);
            }}
        >
            <div className="space-y-3">
                <Typography.Paragraph type="secondary" className="!mb-0">
                    {t('project.predictionTasks.applyModal.description')}
                </Typography.Paragraph>
                <Alert
                    type="info"
                    showIcon
                    message={t('project.predictionTasks.applyModal.hint')}
                />
                <div>
                    <div className="mb-2 font-medium">{t('project.predictionTasks.form.targetBranch')}</div>
                    <Select
                        className="w-full"
                        loading={loading}
                        value={selectedBranchId || undefined}
                        onChange={(value) => setSelectedBranchId(String(value || ''))}
                        options={branches.map((item) => ({
                            value: item.id,
                            label: item.name,
                        }))}
                        placeholder={t('project.predictionTasks.applyModal.branchPlaceholder')}
                    />
                </div>
                <Typography.Text type="secondary">
                    {t('project.predictionTasks.applyModal.defaultTarget', {
                        branch: String(prediction?.targetBranchName || '').trim() || '-',
                    })}
                </Typography.Text>
            </div>
        </Modal>
    );
};

export default PredictionApplyModal;
