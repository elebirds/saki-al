/**
 * EmptyState Component
 * 
 * 通用的空状态组件
 */

import React from 'react';
import { Empty } from 'antd';

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
      <div className="flex h-full items-center justify-center">
        {content}
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center">
      {content}
    </div>
  );
};
