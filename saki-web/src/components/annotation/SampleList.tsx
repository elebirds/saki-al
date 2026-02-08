import React from 'react';
import {List, Typography} from 'antd';
import {Sample} from '../../types';
import {useTranslation} from 'react-i18next';

const {Text} = Typography;

export interface SampleListProps {
    samples: Sample[];
    currentIndex: number;
    onSampleSelect: (index: number) => void;
}

export const SampleList: React.FC<SampleListProps> = ({
                                                          samples,
                                                          currentIndex,
                                                          onSampleSelect,
                                                      }) => {
    const {t} = useTranslation();

    return (
        <div
            className="flex h-full flex-col border-r border-github-border bg-github-panel text-github-text"
        >
            <div
                className="border-b border-github-border bg-github-base p-4"
            >
                <Text strong>{t('annotation.workspace.sampleList')}</Text>
                <div className="mt-2 text-xs text-github-muted">
                    {samples.length} {t('annotation.workspace.samples')}
                </div>
            </div>
            <div
                className="flex-1 overflow-y-auto"
            >
                <List
                    size="small"
                    dataSource={samples}
                    renderItem={(sample, index) => (
                        <List.Item
                            className={`cursor-pointer border-l-[3px] px-4 py-2 ${
                                index === currentIndex
                                    ? 'border-[#1890ff] bg-[var(--github-selected-bg)]'
                                    : 'border-transparent bg-transparent'
                            }`}
                            onClick={() => onSampleSelect(index)}
                        >
                            <div
                                className="flex w-full items-center justify-between"
                            >
                                <div className="min-w-0 flex-1">
                                    <div
                                        className="mb-1 text-xs text-github-muted"
                                    >
                                        #{index + 1}
                                    </div>
                                    <div
                                        className={`truncate text-[13px] ${
                                            index === currentIndex ? 'font-medium' : 'font-normal'
                                        }`}
                                        title={sample.name}
                                    >
                                        {sample.name}
                                    </div>
                                </div>
                            </div>
                        </List.Item>
                    )}
                />
            </div>
        </div>
    );
};
