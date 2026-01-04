/**
 * EmptyState Component
 * 
 * 通用的空状态组件
 */

import React from 'react';
import { Layout, Empty } from 'antd';

const { Content } = Layout;

export interface EmptyStateProps {
  /** 描述文本 */
  description?: string;
  /** 是否使用布局容器 */
  useLayout?: boolean;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  description,
  useLayout = true,
}) => {
  const content = <Empty description={description} />;

  if (useLayout) {
    return (
      <Layout
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Content>{content}</Content>
      </Layout>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100%',
      }}
    >
      {content}
    </div>
  );
};

