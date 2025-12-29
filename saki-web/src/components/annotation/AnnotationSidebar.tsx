/**
 * AnnotationSidebar Component
 * 
 * 标注工作空间的侧边栏组件
 */

import React from 'react';
import { Layout, Button, Card, Space, Typography, List, Tag } from 'antd';
import { useTranslation } from 'react-i18next';
import {
  LeftOutlined,
  RightOutlined,
  CheckOutlined,
  DeleteOutlined,
  BorderOutlined,
  RotateRightOutlined,
} from '@ant-design/icons';
import { Annotation } from '../../types';

const { Sider } = Layout;
const { Title } = Typography;

export interface AnnotationSidebarProps {
  // Annotations
  annotations: Annotation[];
  selectedId: string | null;
  onAnnotationSelect: (id: string) => void;
  onAnnotationDelete: (id: string) => void;
  
  // Navigation
  currentIndex: number;
  totalSamples: number;
  onPrev: () => void;
  onNext: () => void;
  
  // Submit
  onSubmit: () => void;
  
  // Custom render for annotation item (optional, for FEDO to show extra info)
  renderAnnotationItem?: (annotation: Annotation, index: number) => React.ReactNode;
}

export const AnnotationSidebar: React.FC<AnnotationSidebarProps> = ({
  annotations,
  selectedId,
  onAnnotationSelect,
  onAnnotationDelete,
  currentIndex,
  totalSamples,
  onPrev,
  onNext,
  onSubmit,
  renderAnnotationItem,
}) => {
  const { t } = useTranslation();

  const defaultRenderItem = (item: Annotation, index: number) => (
    <List.Item
      actions={[
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          onClick={(e: React.MouseEvent) => {
            e.stopPropagation();
            onAnnotationDelete(item.id);
          }}
        />,
      ]}
      style={{
        padding: '8px 16px',
        background: selectedId === item.id ? '#e6f7ff' : 'transparent',
        cursor: 'pointer',
        borderLeft:
          selectedId === item.id
            ? `4px solid ${item.labelColor || '#1890ff'}`
            : '4px solid transparent',
      }}
      onClick={() => onAnnotationSelect(item.id)}
    >
      <Space>
        {item.type === 'obb' ? <RotateRightOutlined /> : <BorderOutlined />}
        <Tag color={item.labelColor}>{item.labelName}</Tag>
        <span>#{index + 1}</span>
      </Space>
    </List.Item>
  );

  return (
    <Sider
      width={300}
      theme="light"
      style={{
        padding: '20px',
        borderLeft: '1px solid #f0f0f0',
        overflowY: 'auto',
      }}
    >
      <Title level={4}>{t('workspace.annotations')}</Title>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Card size="small" bodyStyle={{ padding: 0 }}>
          <List
            size="small"
            dataSource={annotations}
            renderItem={(item, index) =>
              renderAnnotationItem
                ? renderAnnotationItem(item, index)
                : defaultRenderItem(item, index)
            }
          />
          {annotations.length === 0 && (
            <div style={{ padding: 16, textAlign: 'center', color: '#999' }}>
              {t('workspace.noAnnotations')}
            </div>
          )}
        </Card>

        <div style={{ marginTop: 20 }}>
          <Space>
            <Button
              icon={<LeftOutlined />}
              onClick={onPrev}
              disabled={currentIndex === 0}
            />
            <span>
              {currentIndex + 1} / {totalSamples}
            </span>
            <Button
              icon={<RightOutlined />}
              onClick={onNext}
              disabled={currentIndex === totalSamples - 1}
            />
          </Space>
        </div>

        <Button
          type="primary"
          block
          icon={<CheckOutlined />}
          onClick={onSubmit}
          style={{ marginTop: 20 }}
        >
          {t('workspace.submitNext')}
        </Button>
      </Space>
    </Sider>
  );
};

