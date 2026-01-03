/**
 * AnnotationToolbar Component
 * 
 * 标注工作空间的工具栏组件
 */

import React from 'react';
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
} from '@ant-design/icons';
import { Label } from '../../types';

export interface AnnotationToolbarProps {
  // Label selection
  labels: Label[];
  selectedLabel: Label | null;
  onLabelChange: (label: Label) => void;
  
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
}) => {
  const { t } = useTranslation();

  return (
    <div style={{
      padding: '10px',
      background: '#fff',
      borderBottom: '1px solid #f0f0f0',
      display: 'flex',
      gap: '10px',
      alignItems: 'center',
    }}>
      {/* Label Selection */}
      <Space>
        <span style={{ fontWeight: 'bold' }}>{t('workspace.label')}</span>
        <Select
          value={selectedLabel?.id}
          onChange={(value) => {
            const label = labels.find(l => l.id === value);
            if (label) onLabelChange(label);
          }}
          style={{ width: 150 }}
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
            <DragOutlined /> Select
          </Tooltip>
        </Radio.Button>
        <Radio.Button value="rect">
          <Tooltip title={t('workspace.tools.rect')}>
            <BorderOutlined /> Rect
          </Tooltip>
        </Radio.Button>
        <Radio.Button value="obb">
          <Tooltip title={t('workspace.tools.obb')}>
            <RotateRightOutlined /> OBB
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
                ? 'Syncing...'
                : syncStatus.isSyncReady
                ? 'Sync Ready'
                : 'Initializing...'}
            </Tag>
          </Space>
        </>
      )}

      <div style={{ flex: 1 }} />
    </div>
  );
};

