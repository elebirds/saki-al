/**
 * AnnotationToolbar Component
 * 
 * 标注工作空间的工具栏组件
 */

import React, { ReactNode } from 'react';
import { Space, Button, Radio, Tooltip, Select, Tag, Spin, Divider } from 'antd';
import { useTranslation } from 'react-i18next';
import {
  UndoOutlined,
  RedoOutlined,
  DragOutlined,
  BorderOutlined,
  RotateRightOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  ExpandOutlined,
  SyncOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import { ProjectLabel } from '../../types';

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
  currentTool: 'select' | 'rect' | 'obb';
  onToolChange: (tool: 'select' | 'rect' | 'obb') => void;
  
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
  onZoomIn,
  onZoomOut,
  onResetView,
  syncStatus,
  hasAnyEditPermission = true,
  onBack,
  backLabel,
  extraActions,
}) => {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-2.5 border-b border-[#f0f0f0] bg-white p-2.5">
      {/* Back Button */}
      {onBack ? (
        <>
          <Tooltip title={t('workspace.backToDataset')}>
            <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
              {backLabel || t('workspace.back')}
            </Button>
          </Tooltip>
          <Divider type="vertical" />
        </>
      ) : null}

      {/* Label Selection */}
      <Space>
        <span className="font-semibold">{t('workspace.label')}</span>
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
      </Space>

      <Divider type="vertical" />

      {/* Undo/Redo */}
      <Space>
        <Tooltip title="Undo (Ctrl+Z)">
          <Button
            icon={<UndoOutlined />}
            onClick={onUndo}
            disabled={historyIndex === 0}
          />
        </Tooltip>
        <Tooltip title="Redo (Ctrl+Shift+Z)">
          <Button
            icon={<RedoOutlined />}
            onClick={onRedo}
            disabled={historyIndex === historyLength - 1}
          />
        </Tooltip>
      </Space>

      <Divider type="vertical" />

      {/* Tool Selection */}
      <Radio.Group
        value={currentTool}
        onChange={(e) => onToolChange(e.target.value)}
        buttonStyle="solid"
      >
        <Radio.Button value="select">
          <Tooltip title={t('workspace.tools.select')}>
            <DragOutlined /> {t('workspace.tools.select').split(' (')[0]}
          </Tooltip>
        </Radio.Button>
        <Radio.Button value="rect" disabled={!hasAnyEditPermission}>
          <Tooltip title={hasAnyEditPermission ? t('workspace.tools.rect') : t('workspace.noEditPermission')}>
            <BorderOutlined /> {t('workspace.tools.rect').split(' (')[0]}
          </Tooltip>
        </Radio.Button>
        <Radio.Button value="obb" disabled={!hasAnyEditPermission}>
          <Tooltip title={hasAnyEditPermission ? t('workspace.tools.obb') : t('workspace.noEditPermission')}>
            <RotateRightOutlined /> {t('workspace.tools.obb').split(' (')[0]}
          </Tooltip>
        </Radio.Button>
      </Radio.Group>

      <Divider type="vertical" />

      {/* Zoom Controls */}
      {onZoomIn && onZoomOut && onResetView && (
        <Space>
          <Tooltip title={t('workspace.tools.zoomIn')}>
            <Button icon={<ZoomInOutlined />} onClick={onZoomIn} />
          </Tooltip>
          <Tooltip title={t('workspace.tools.zoomOut')}>
            <Button icon={<ZoomOutOutlined />} onClick={onZoomOut} />
          </Tooltip>
          <Tooltip title={t('workspace.tools.resetView')}>
            <Button icon={<ExpandOutlined />} onClick={onResetView} />
          </Tooltip>
        </Space>
      )}

      {/* Sync Status (for FEDO) */}
      {syncStatus && (
        <>
          <Divider type="vertical" />
          <Space>
            {syncStatus.isSyncing && <Spin size="small" />}
            <Tag
              color={syncStatus.isSyncReady ? 'green' : 'orange'}
              icon={<SyncOutlined spin={syncStatus.isSyncing} />}
            >
              {syncStatus.isSyncing
                ? t('workspace.sync.syncing')
                : syncStatus.isSyncReady
                ? t('workspace.sync.ready')
                : t('workspace.sync.initializing')}
            </Tag>
          </Space>
        </>
      )}

      <div className="flex-1" />
      {extraActions ? <div className="flex items-center gap-2">{extraActions}</div> : null}
    </div>
  );
};
