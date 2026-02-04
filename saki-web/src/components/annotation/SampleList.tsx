import React from 'react';
import { List, Typography } from 'antd';
import { Sample } from '../../types';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

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
  const { t } = useTranslation();

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: '#fff',
        borderRight: '1px solid #f0f0f0',
      }}
    >
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <Text strong>{t('workspace.sampleList') || '样本列表'}</Text>
        <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
          {samples.length} {t('workspace.samples') || '个样本'}
        </div>
      </div>
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
        }}
      >
        <List
          size="small"
          dataSource={samples}
          renderItem={(sample, index) => (
            <List.Item
              style={{
                padding: '8px 16px',
                cursor: 'pointer',
                backgroundColor: index === currentIndex ? '#e6f7ff' : 'transparent',
                borderLeft: index === currentIndex ? '3px solid #1890ff' : '3px solid transparent',
              }}
              onClick={() => onSampleSelect(index)}
            >
              <div
                style={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 12,
                      color: '#666',
                      marginBottom: 4,
                    }}
                  >
                    #{index + 1}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: index === currentIndex ? 500 : 400,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
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

