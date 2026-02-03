import React, { useEffect, useState } from 'react';
import { Modal, Table, Button, Tag, Spin, message, Empty, Tooltip, Space } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { Sample } from '../../types';

interface SampleAssetModalProps {
  open: boolean;
  sample: Sample | null;
  onClose: () => void;
}

interface AssetInfo {
  role: string;
  assetId: string;
  displayName: string;
}

const SampleAssetModal: React.FC<SampleAssetModalProps> = ({ open, sample, onClose }) => {
  const { t } = useTranslation();
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && sample) {
      loadAssets();
    }
  }, [open, sample]);

  const loadAssets = async () => {
    if (!sample) return;

    setLoading(true);
    try {
      const assetList: AssetInfo[] = [];

      // Map asset_group to displayable assets
      if (sample.assetGroup) {
        for (const [role, assetId] of Object.entries(sample.assetGroup)) {
          // Format role name for display (snake_case -> readable)
          const displayName = role
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');

          assetList.push({
            role,
            assetId: assetId as string,
            displayName,
          });
        }
      }

      setAssets(assetList);
    } catch (error) {
      message.error(t('sampleAssetModal.loadError'));
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadAsset = async (assetId: string, displayName: string) => {
    try {
      const response = await fetch(`/api/v1/assets/${assetId}/download-url`, {
        method: 'GET',
      });

      if (!response.ok) {
        throw new Error('Download failed');
      }

      const data = await response.json();
      const downloadUrl = data.download_url as string | undefined;
      const filename = (data.filename as string | undefined) ?? `${sample?.name}_${displayName}`;

      if (!downloadUrl) {
        throw new Error('Download URL missing');
      }

      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = filename;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.click();
      message.success(t('common.downloadSuccess'));
    } catch (error) {
      message.error(t('common.downloadError'));
    }
  };

  const columns = [
    {
      title: t('sampleAssetModal.assets'),
      dataIndex: 'displayName',
      key: 'displayName',
      render: (_: string, asset: AssetInfo) => {
        const isPrimaryAsset = asset.assetId === sample?.primaryAssetId;
        return (
          <Space>
            <span>{asset.displayName}</span>
            {isPrimaryAsset && <Tag color="blue">{t('sampleAssetModal.primary')}</Tag>}
          </Space>
        );
      },
    },
    {
      title: 'Asset ID',
      dataIndex: 'assetId',
      key: 'assetId',
      render: (value: string) => (
        <span style={{ fontSize: 12, color: '#666', wordBreak: 'break-all' }}>{value}</span>
      ),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      render: (_: string, asset: AssetInfo) => (
        <Space>
          <Tooltip title={t('common.download')}>
            <Button
              type="text"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownloadAsset(asset.assetId, asset.displayName)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title={
        sample
          ? t('sampleAssetModal.title', { name: sample.name })
          : t('sampleAssetModal.assets')
      }
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="close" onClick={onClose}>
          {t('common.close')}
        </Button>,
      ]}
      width={600}
    >
      <Spin spinning={loading}>
        {assets.length === 0 ? (
          <Empty
            description={t('sampleAssetModal.noAssets')}
            style={{ marginTop: 20 }}
          />
        ) : (
          <Table
            rowKey="assetId"
            columns={columns}
            dataSource={assets}
            pagination={false}
            size="small"
          />
        )}
      </Spin>
    </Modal>
  );
};

export default SampleAssetModal;
