import React, {useCallback, useState} from 'react'
import {Button, Card, List, Tag, Tooltip, Typography} from 'antd'
import {FileTextOutlined, UploadOutlined} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'
import {Sample} from '../../types'
import {api} from '../../services/api'
import {PaginatedList} from '../../components/common/PaginatedList'
import SampleAssetModal from '../../components/dataset/SampleAssetModal'

const {Title} = Typography

export interface ProjectDatasetSamplesProps {
    datasetId: string
    datasetName?: string
    onBack?: () => void
}

const ProjectDatasetSamples: React.FC<ProjectDatasetSamplesProps> = ({
                                                                         datasetId,
                                                                         datasetName,
                                                                         onBack,
                                                                     }) => {
    const {t} = useTranslation()
    const [selectedSample, setSelectedSample] = useState<Sample | null>(null)
    const [assetModalOpen, setAssetModalOpen] = useState(false)
    const [sampleMeta, setSampleMeta] = useState({total: 0, limit: 8, offset: 0, size: 0})

    const fetchSamples = useCallback(
        (page: number, pageSize: number) => api.getSamples(datasetId, page, pageSize),
        [datasetId]
    )

    const renderSampleItem = (item: Sample) => {
        return (
            <Card
                hoverable
                onClick={() => {
                    setSelectedSample(item)
                    setAssetModalOpen(true)
                }}
                className="cursor-pointer"
                cover={
                    <img
                        alt={t('common.sample')}
                        src={item.primaryAssetUrl}
                        className="h-[150px] w-full object-cover"
                        onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                            e.currentTarget.style.display = 'none'
                        }}
                    />
                }
                size="small"
            >
                <Card.Meta
                    title={<span className="block truncate">{item.name}</span>}
                    description={item.remark && <span className="text-xs text-gray-500">{item.remark}</span>}
                />
            </Card>
        )
    }

    const totalSamplePages = Math.max(1, Math.ceil(sampleMeta.total / (sampleMeta.limit || 1)))

    return (
        <div className="flex h-full flex-col">
            <div className="mb-4 flex flex-wrap items-center gap-3">
                {onBack ? (
                    <Button type="link" onClick={onBack} className="!p-0">
                        ← {t('project.datasetSamples.backToDatasets')}
                    </Button>
                ) : null}
                <Title level={5} className="!m-0">
                    {datasetName || t('project.datasetSamples.datasetFallback')}
                    <Tag className="ml-2">{t('project.datasetSamples.samples')}</Tag>
                </Title>
            </div>

            <div className="flex-1 min-h-0 pr-2.5">
                <PaginatedList<Sample>
                    fetchData={fetchSamples}
                    initialPageSize={8}
                    pageSizeOptions={['8', '12', '20', '32', '50']}
                    adaptivePageSize={{
                        enabled: true,
                        mode: 'grid',
                        itemMinWidth: 260,
                        itemHeight: 250,
                        rowGap: 16,
                        colGap: 16,
                    }}
                    refreshKey={datasetId}
                    resetPageOnRefresh
                    onMetaChange={(meta) => setSampleMeta(meta)}
                    renderItems={(items) =>
                        items.length === 0 ? (
                            <Card>
                                <div className="p-10 text-center">
                                    <FileTextOutlined className="mb-4 text-[48px] text-gray-300"/>
                                    <Title level={5} className="!text-gray-500">{t('project.datasetSamples.emptyTitle')}</Title>
                                    <Tooltip title={t('project.datasetSamples.emptyHint')}>
                                        <Button type="primary" icon={<UploadOutlined/>} disabled>
                                            {t('project.datasetSamples.upload')}
                                        </Button>
                                    </Tooltip>
                                </div>
                            </Card>
                        ) : (
                            <List
                                grid={{
                                    gutter: 16,
                                    xs: 1,
                                    sm: 2,
                                    md: 2,
                                    lg: 3,
                                    xl: 4,
                                    xxl: 4,
                                }}
                                dataSource={items}
                                renderItem={(item) => <List.Item>{renderSampleItem(item)}</List.Item>}
                            />
                        )
                    }
                    renderPaginationWrapper={(node) => (
                        <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-gray-600">
                {t('project.datasetSamples.pagination', {
                    page: Math.floor(sampleMeta.offset / (sampleMeta.limit || 1)) + 1,
                    totalPages: totalSamplePages,
                    totalItems: sampleMeta.total,
                })}
              </span>
                            {node}
                        </div>
                    )}
                    paginationProps={{
                        showTotal: (tot, range) =>
                            range
                                ? t('common.pagination.range', {start: range[0], end: range[1], total: tot})
                                : t('common.pagination.total', {total: tot}),
                    }}
                />
            </div>

            <SampleAssetModal
                open={assetModalOpen}
                sample={selectedSample}
                onClose={() => {
                    setAssetModalOpen(false)
                    setSelectedSample(null)
                }}
            />
        </div>
    )
}

export default ProjectDatasetSamples
