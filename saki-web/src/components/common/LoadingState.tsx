/**
 * LoadingState Component
 *
 * 通用的加载状态组件
 */

import React from 'react';
import {Spin} from 'antd';

export interface LoadingStateProps {
    /** 自定义提示文本 */
    tip?: string;
    /** 最小高度 */
    minHeight?: number;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
                                                              tip,
                                                              minHeight = 200,
                                                          }) => {
    return (
        <div className="flex h-full items-center justify-center">
            <Spin size="large" tip={tip}>
                <div style={{minHeight}}/>
            </Spin>
        </div>
    );
};
