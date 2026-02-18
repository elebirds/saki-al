/**
 * AnnotationToolbar Component
 *
 * 标注工作空间的工具栏组件
 */

import React, {ReactNode} from 'react';
import {Button, Divider, Radio, Select, Spin, Tag, Tooltip} from 'antd';
import {useTranslation} from 'react-i18next';
import {
    ArrowLeftOutlined,
    BorderOutlined,
    DragOutlined,
    ExpandOutlined,
    RedoOutlined,
    RotateRightOutlined,
    SyncOutlined,
    UndoOutlined,
    ZoomInOutlined,
    ZoomOutOutlined,
} from '@ant-design/icons';
import {
    ANNOTATION_TYPE_OBB,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TOOL_SELECT,
    AnnotationToolType,
    DEFAULT_DETECTION_ANNOTATION_TYPES,
    DetectionAnnotationType,
    ProjectLabel,
} from '../../types';

export interface AnnotationToolbarProps {
    // Label selection
    labels: ProjectLabel[];
    selectedLabel: ProjectLabel | null;
    onLabelChange: (label: ProjectLabel) => void;

    // History
    historyIndex: number;
    historyLength: number;
    onUndo: () => void;
    onRedo: () => void;

    // Tools
    currentTool: AnnotationToolType;
    onToolChange: (tool: AnnotationToolType) => void;
    enabledTools?: DetectionAnnotationType[];

    // Zoom controls
    onZoomIn?: () => void;
    onZoomOut?: () => void;
    onResetView?: () => void;

    // Sync status (optional, for FEDO)
    syncStatus?: {
        isSyncing: boolean;
        isSyncReady: boolean;
    };

    // Permission control
    hasAnyEditPermission?: boolean;

    // Back navigation
    onBack?: () => void;
    backLabel?: string;

    // Extra actions (right side)
    extraActions?: ReactNode;
}

export const AnnotationToolbar: React.FC<AnnotationToolbarProps> = ({
                                                                        labels,
                                                                        selectedLabel,
                                                                        onLabelChange,
                                                                        historyIndex,
                                                                        historyLength,
                                                                        onUndo,
                                                                        onRedo,
                                                                        currentTool,
                                                                        onToolChange,
                                                                        enabledTools = DEFAULT_DETECTION_ANNOTATION_TYPES,
                                                                        onZoomIn,
                                                                        onZoomOut,
                                                                        onResetView,
                                                                        syncStatus,
                                                                        hasAnyEditPermission = true,
                                                                        onBack,
                                                                        backLabel,
                                                                        extraActions,
                                                                    }) => {
    const {t} = useTranslation();

    return (
        <div className="flex items-center gap-2.5 border-b border-github-border bg-github-panel p-2.5 text-github-text">
            {/* Back Button */}
            {onBack ? (
                <>
                    <Tooltip title={t('annotation.workspace.backToDataset')}>
                        <Button icon={<ArrowLeftOutlined/>} onClick={onBack}>
                            {backLabel || t('annotation.workspace.back')}
                        </Button>
                    </Tooltip>
                    <Divider type="vertical"/>
                </>
            ) : null}

            {/* Label Selection */}
            <div className="flex items-center gap-2">
                <span className="font-semibold">{t('annotation.workspace.label')}</span>
                <Select
                    value={selectedLabel?.id}
                    onChange={(value) => {
                        const label = labels.find(l => l.id === value);
                        if (label) onLabelChange(label);
                    }}
                    className="w-[150px]"
                >
                    {labels.map(label => (
                        <Select.Option key={label.id} value={label.id}>
                            <Tag color={label.color}>{label.name}</Tag>
                        </Select.Option>
                    ))}
                </Select>
            </div>

            <Divider type="vertical"/>

            {/* Undo/Redo */}
            <div className="flex items-center gap-2">
                <Tooltip title={t('annotation.toolbar.undoShortcut')}>
                    <Button
                        icon={<UndoOutlined/>}
                        onClick={onUndo}
                        disabled={historyIndex === 0}
                    />
                </Tooltip>
                <Tooltip title={t('annotation.toolbar.redoShortcut')}>
                    <Button
                        icon={<RedoOutlined/>}
                        onClick={onRedo}
                        disabled={historyIndex === historyLength - 1}
                    />
                </Tooltip>
            </div>

            <Divider type="vertical"/>

            {/* Tool Selection */}
            <Radio.Group
                value={currentTool}
                onChange={(e) => onToolChange(e.target.value as AnnotationToolType)}
                buttonStyle="solid"
            >
                <Radio.Button value={ANNOTATION_TOOL_SELECT}>
                    <Tooltip title={t('annotation.workspace.tools.select')}>
                        <DragOutlined/> {t('annotation.workspace.tools.select').split('(')[0]}
                    </Tooltip>
                </Radio.Button>
                {enabledTools.includes(ANNOTATION_TYPE_RECT) ? (
                    <Radio.Button value={ANNOTATION_TYPE_RECT} disabled={!hasAnyEditPermission}>
                        <Tooltip title={hasAnyEditPermission ? t('annotation.workspace.tools.rect') : t('annotation.workspace.noEditPermission')}>
                            <BorderOutlined/> {t('annotation.workspace.tools.rect').split('(')[0]}
                        </Tooltip>
                    </Radio.Button>
                ) : null}
                {enabledTools.includes(ANNOTATION_TYPE_OBB) ? (
                    <Radio.Button value={ANNOTATION_TYPE_OBB} disabled={!hasAnyEditPermission}>
                        <Tooltip title={hasAnyEditPermission ? t('annotation.workspace.tools.obb') : t('annotation.workspace.noEditPermission')}>
                            <RotateRightOutlined/> {t('annotation.workspace.tools.obb').split('(')[0]}
                        </Tooltip>
                    </Radio.Button>
                ) : null}
            </Radio.Group>

            <Divider type="vertical"/>

            {/* Zoom Controls */}
            {onZoomIn && onZoomOut && onResetView && (
                <div className="flex items-center gap-2">
                    <Tooltip title={t('annotation.workspace.tools.zoomIn')}>
                        <Button icon={<ZoomInOutlined/>} onClick={onZoomIn}/>
                    </Tooltip>
                    <Tooltip title={t('annotation.workspace.tools.zoomOut')}>
                        <Button icon={<ZoomOutOutlined/>} onClick={onZoomOut}/>
                    </Tooltip>
                    <Tooltip title={t('annotation.workspace.tools.resetView')}>
                        <Button icon={<ExpandOutlined/>} onClick={onResetView}/>
                    </Tooltip>
                </div>
            )}

            {/* Sync Status (for FEDO) */}
            {syncStatus && (
                <>
                    <Divider type="vertical"/>
                    <div className="flex items-center gap-2">
                        {syncStatus.isSyncing && <Spin size="small"/>}
                        <Tag
                            color={syncStatus.isSyncReady ? 'green' : 'orange'}
                            icon={<SyncOutlined spin={syncStatus.isSyncing}/>}
                        >
                            {syncStatus.isSyncing
                                ? t('annotation.workspace.sync.syncing')
                                : syncStatus.isSyncReady
                                    ? t('annotation.workspace.sync.ready')
                                    : t('annotation.workspace.sync.initializing')}
                        </Tag>
                    </div>
                </>
            )}

            <div className="flex-1"/>
            {extraActions ? <div className="flex items-center gap-2">{extraActions}</div> : null}
        </div>
    );
};
