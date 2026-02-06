import React, {useCallback, useEffect, useMemo, useState} from 'react'
import {Avatar, Button, Divider, Empty, Input, Spin, Tag, Tree, message} from 'antd'
import type {DataNode} from 'antd/es/tree'
import {
    BranchesOutlined,
    DiffOutlined,
    EditOutlined,
    FileOutlined,
    FolderOutlined,
    SearchOutlined,
} from '@ant-design/icons'
import {useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {api} from '../../services/api'
import {
    AnnotationRead,
    CommitDiff,
    CommitRead,
    Dataset,
    ProjectLabel,
    ResourceMember,
    Sample,
} from '../../types'

type CommitTreeNode = DataNode & {
    key: string
    nodeType: 'dataset' | 'sample' | 'annotation'
    datasetId?: string
    sampleId?: string
    annotationId?: string
    searchText?: string
    dataRef?: Dataset | Sample | AnnotationRead
}

const formatRelativeTime = (value?: string) => {
    if (!value) return '-'
    const date = new Date(value)
    const diffMs = Date.now() - date.getTime()
    const minutes = Math.floor(diffMs / 60000)
    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes} min ago`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours} hours ago`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days} days ago`
    const weeks = Math.floor(days / 7)
    if (weeks < 5) return `${weeks} weeks ago`
    const months = Math.floor(days / 30)
    return `${months} months ago`
}

const formatAbsoluteDate = (value?: string) => {
    if (!value) return '-'
    const date = new Date(value)
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    })
}

const getCommitStatValue = (stats: Record<string, any> | undefined, key: string) => {
    if (!stats) return 0
    if (stats[key] !== undefined) return stats[key]
    const snakeKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
    return stats[snakeKey] ?? 0
}

const ProjectCommitDetail: React.FC = () => {
    const {projectId, commitId} = useParams<{ projectId: string; commitId: string }>()
    const [searchParams] = useSearchParams()
    const navigate = useNavigate()

    const [loading, setLoading] = useState(true)
    const [treeLoading, setTreeLoading] = useState(true)
    const [commit, setCommit] = useState<CommitRead | null>(null)
    const [diff, setDiff] = useState<CommitDiff | null>(null)
    const [datasets, setDatasets] = useState<Dataset[]>([])
    const [labels, setLabels] = useState<ProjectLabel[]>([])
    const [members, setMembers] = useState<ResourceMember[]>([])
    const [treeData, setTreeData] = useState<CommitTreeNode[]>([])
    const [samplesByDataset, setSamplesByDataset] = useState<Record<string, Sample[]>>({})
    const [annotationsBySample, setAnnotationsBySample] = useState<Record<string, AnnotationRead[]>>({})
    const [selectedNode, setSelectedNode] = useState<CommitTreeNode | null>(null)
    const [filterText, setFilterText] = useState('')

    const labelMap = useMemo(() => new Map(labels.map((label) => [label.id, label])), [labels])
    const memberMap = useMemo(() => new Map(members.map((member) => [member.userId, member])), [members])

    const diffInfo = useMemo(() => {
        const addedSamples = new Set(diff?.addedSamples ?? [])
        const removedSamples = new Set(diff?.removedSamples ?? [])
        const modifiedAnnotations = diff?.modifiedAnnotations ?? {}
        const modifiedSamples = new Set(Object.keys(modifiedAnnotations))
        const changedSamples = new Set<string>([
            ...addedSamples,
            ...removedSamples,
            ...modifiedSamples,
        ])
        return {addedSamples, removedSamples, modifiedSamples, modifiedAnnotations, changedSamples}
    }, [diff])

    const branchName = searchParams.get('branch') || 'master'

    const buildDatasetNode = (dataset: Dataset): CommitTreeNode => ({
        key: `dataset-${dataset.id}`,
        title: dataset.name,
        icon: <FolderOutlined className="text-github-muted"/>,
        nodeType: 'dataset',
        datasetId: dataset.id,
        searchText: dataset.name.toLowerCase(),
        dataRef: dataset,
    })

    const buildSampleTitle = (sample: Sample, statusTag?: React.ReactNode, annotationCount?: number) => (
        <div className="flex items-center gap-2 min-w-0">
            <span className="truncate">{sample.name || sample.id.slice(0, 8)}</span>
            {annotationCount !== undefined ? (
                <span className="text-xs text-github-muted">{annotationCount} annotations</span>
            ) : null}
            {statusTag}
        </div>
    )

    const buildSampleNode = (sample: Sample): CommitTreeNode => {
        let statusTag: React.ReactNode | undefined
        if (diffInfo.addedSamples.has(sample.id)) {
            statusTag = <Tag color="green">Added</Tag>
        } else if (diffInfo.removedSamples.has(sample.id)) {
            statusTag = <Tag color="red">Removed</Tag>
        } else if (diffInfo.modifiedSamples.has(sample.id)) {
            statusTag = <Tag color="blue">Modified</Tag>
        }

        return {
            key: `sample-${sample.id}`,
            title: buildSampleTitle(sample, statusTag),
            icon: <FileOutlined className="text-github-muted"/>,
            nodeType: 'sample',
            sampleId: sample.id,
            datasetId: sample.datasetId,
            searchText: `${sample.name} ${sample.id}`.toLowerCase(),
            dataRef: sample,
        }
    }

    const buildAnnotationNode = (
        annotation: AnnotationRead,
        sampleId: string,
        statusOverride?: 'added' | 'removed'
    ): CommitTreeNode => {
        const label = labelMap.get(annotation.labelId)
        const labelName = label?.name || annotation.labelId.slice(0, 8)
        const labelColor = label?.color
        const diffEntry = diffInfo.modifiedAnnotations[sampleId]
        let statusTag: React.ReactNode | undefined
        if (statusOverride === 'added' || diffEntry?.added?.includes(annotation.id)) {
            statusTag = <Tag color="green">Added</Tag>
        } else if (statusOverride === 'removed' || diffEntry?.removed?.includes(annotation.id)) {
            statusTag = <Tag color="red">Removed</Tag>
        }

        return {
            key: `annotation-${annotation.id}`,
            title: (
                <div className="flex items-center gap-2 min-w-0">
                    <span className="truncate">{labelName}</span>
                    <span className="text-xs text-github-muted">{annotation.type}</span>
                    {labelColor ? (
                        <span
                            className="h-2.5 w-2.5 rounded-full border border-github-border"
                            style={{backgroundColor: labelColor}}
                        />
                    ) : null}
                    {statusTag}
                </div>
            ),
            icon: <EditOutlined className="text-github-muted"/>,
            nodeType: 'annotation',
            annotationId: annotation.id,
            sampleId,
            searchText: `${labelName} ${annotation.type} ${annotation.id}`.toLowerCase(),
            dataRef: annotation,
            isLeaf: true,
        }
    }

    const updateTreeData = useCallback((list: CommitTreeNode[], key: string, updater: (node: CommitTreeNode) => CommitTreeNode) => {
        return list.map((node) => {
            if (node.key === key) {
                return updater(node)
            }
            if (node.children) {
                return {
                    ...node,
                    children: updateTreeData(node.children as CommitTreeNode[], key, updater),
                }
            }
            return node
        })
    }, [])

    const loadBaseData = useCallback(async () => {
        if (!projectId || !commitId) return
        setLoading(true)
        setTreeLoading(true)
        try {
            const [commitData, diffData, datasetIds, labelData, memberData] = await Promise.all([
                api.getCommit(commitId),
                api.getCommitDiff(commitId),
                api.getProjectDatasets(projectId),
                api.getProjectLabels(projectId).catch(() => []),
                api.getProjectMembers(projectId).catch(() => []),
            ])

            setCommit(commitData)
            setDiff(diffData)
            setLabels(labelData || [])
            setMembers(memberData || [])

            const datasetResults = await Promise.all(
                (datasetIds || []).map((id) => api.getDataset(id).catch(() => null))
            )
            const resolvedDatasets = datasetResults.filter(Boolean) as Dataset[]
            setDatasets(resolvedDatasets)

            const addedSamples = new Set(diffData?.addedSamples ?? [])
            const removedSamples = new Set(diffData?.removedSamples ?? [])
            const modifiedSamples = new Set(Object.keys(diffData?.modifiedAnnotations ?? {}))
            const changedSamples = new Set<string>([
                ...addedSamples,
                ...removedSamples,
                ...modifiedSamples,
            ])

            if (changedSamples.size === 0) {
                setSamplesByDataset({})
                setTreeData([])
                return
            }

            const changedSamplesByDataset: Record<string, Sample[]> = {}
            const pendingSamples = new Set(changedSamples)

            for (const dataset of resolvedDatasets) {
                if (pendingSamples.size === 0) break

                const matched: Sample[] = []
                let page = 1
                let hasMore = true

                while (hasMore && pendingSamples.size > 0) {
                    const response = await api.getSamples(dataset.id, page, 200, 'createdAt', 'desc')
                    const items = response.items || []

                    items.forEach((sample) => {
                        if (pendingSamples.has(sample.id)) {
                            matched.push(sample)
                            pendingSamples.delete(sample.id)
                        }
                    })

                    hasMore = response.hasMore && items.length > 0
                    page += 1
                }

                if (matched.length > 0) {
                    changedSamplesByDataset[dataset.id] = matched
                }
            }

            setSamplesByDataset(changedSamplesByDataset)

            const nodes = resolvedDatasets
                .filter((dataset) => changedSamplesByDataset[dataset.id]?.length)
                .map((dataset) => {
                    const sampleNodes = changedSamplesByDataset[dataset.id].map(buildSampleNode)
                    return {
                        ...buildDatasetNode(dataset),
                        children: sampleNodes,
                        isLeaf: sampleNodes.length === 0,
                    }
                })
            setTreeData(nodes)
        } catch (error: any) {
            message.error(error.message || 'Failed to load commit detail')
        } finally {
            setLoading(false)
            setTreeLoading(false)
        }
    }, [projectId, commitId])

    useEffect(() => {
        loadBaseData()
    }, [loadBaseData])

    const handleLoadData = useCallback(async (node: any) => {
        const typed = node as CommitTreeNode
        if (!projectId || !commitId) return
        if (typed.children) return

        if (typed.nodeType === 'dataset' && typed.datasetId) {
            const cached = samplesByDataset[typed.datasetId]
            const sampleNodes = (cached || []).map(buildSampleNode)
            setTreeData((prev) =>
                updateTreeData(prev, typed.key, (target) => ({
                    ...target,
                    children: sampleNodes,
                    isLeaf: sampleNodes.length === 0,
                }))
            )
        }

        if (typed.nodeType === 'sample' && typed.sampleId) {
            try {
                const isAddedSample = diffInfo.addedSamples.has(typed.sampleId)
                const isRemovedSample = diffInfo.removedSamples.has(typed.sampleId)
                const diffEntry = diffInfo.modifiedAnnotations[typed.sampleId]
                const addedIds = new Set(diffEntry?.added ?? [])
                const removedIds = new Set(diffEntry?.removed ?? [])
                let mergedAnnotations: AnnotationRead[] = []
                let annotationNodes: CommitTreeNode[] = []

                if (isAddedSample) {
                    mergedAnnotations = await api.getAnnotationsAtCommit(commitId, typed.sampleId)
                    annotationNodes = mergedAnnotations.map((annotation) =>
                        buildAnnotationNode(annotation, typed.sampleId!, 'added')
                    )
                } else if (isRemovedSample) {
                    if (commit?.parentId) {
                        mergedAnnotations = await api.getAnnotationsAtCommit(commit.parentId, typed.sampleId)
                    }
                    annotationNodes = mergedAnnotations.map((annotation) =>
                        buildAnnotationNode(annotation, typed.sampleId!, 'removed')
                    )
                } else {
                    const currentAnnotations = await api.getAnnotationsAtCommit(commitId, typed.sampleId)
                    const parentAnnotations = (commit?.parentId && removedIds.size > 0)
                        ? await api.getAnnotationsAtCommit(commit.parentId, typed.sampleId)
                        : []
                    const addedAnnotations = currentAnnotations.filter((annotation) => addedIds.has(annotation.id))
                    const removedAnnotations = parentAnnotations.filter((annotation) => removedIds.has(annotation.id))
                    const mergedMap = new Map<string, AnnotationRead>()
                    addedAnnotations.forEach((annotation) => mergedMap.set(annotation.id, annotation))
                    removedAnnotations.forEach((annotation) => mergedMap.set(annotation.id, annotation))
                    mergedAnnotations = Array.from(mergedMap.values())
                    annotationNodes = mergedAnnotations.map((annotation) =>
                        buildAnnotationNode(annotation, typed.sampleId!)
                    )
                }

                setAnnotationsBySample((prev) => ({...prev, [typed.sampleId!]: mergedAnnotations}))

                const sample = typed.dataRef as Sample | undefined
                const statusTag = diffInfo.addedSamples.has(typed.sampleId)
                    ? <Tag color="green">Added</Tag>
                    : diffInfo.removedSamples.has(typed.sampleId)
                        ? <Tag color="red">Removed</Tag>
                        : diffInfo.modifiedSamples.has(typed.sampleId)
                            ? <Tag color="blue">Modified</Tag>
                            : undefined

                setTreeData((prev) =>
                    updateTreeData(prev, typed.key, (target) => ({
                        ...target,
                        title: sample ? buildSampleTitle(sample, statusTag, annotationNodes.length) : target.title,
                        children: annotationNodes,
                        isLeaf: annotationNodes.length === 0,
                    }))
                )
            } catch (error: any) {
                message.error(error.message || 'Failed to load annotations')
            }
        }
    }, [commitId, projectId, updateTreeData, diffInfo, commit, samplesByDataset])

    const filteredTreeData = useMemo(() => {
        if (!filterText.trim()) return treeData
        const keyword = filterText.toLowerCase()

        const filterNodes = (nodes: CommitTreeNode[]): CommitTreeNode[] => {
            return nodes
                .map((node) => {
                    const children = node.children ? filterNodes(node.children as CommitTreeNode[]) : []
                    const matched = node.searchText?.includes(keyword)
                    if (matched || children.length > 0) {
                        return {...node, children}
                    }
                    return null
                })
                .filter(Boolean) as CommitTreeNode[]
        }

        return filterNodes(treeData)
    }, [filterText, treeData])

    const authorName = useMemo(() => {
        if (!commit) return 'Unknown'
        if (commit.authorType === 'system') return 'System'
        if (commit.authorType === 'model') return 'Model'
        const member = commit.authorId ? memberMap.get(commit.authorId) : null
        return member?.userFullName || member?.userEmail || 'Unknown User'
    }, [commit, memberMap])

    const authorAvatar = commit?.authorId ? memberMap.get(commit.authorId)?.userAvatarUrl : undefined

    const commitStats = useMemo(() => {
        return {
            sampleCount: getCommitStatValue(commit?.stats, 'sampleCount'),
            annotationCount: getCommitStatValue(commit?.stats, 'annotationCount'),
        }
    }, [commit])

    const diffStats = useMemo(() => {
        return {
            addedSamples: diff?.addedSamples?.length || 0,
            removedSamples: diff?.removedSamples?.length || 0,
            modifiedSamples: diff?.modifiedAnnotations ? Object.keys(diff.modifiedAnnotations).length : 0,
        }
    }, [diff])

    if (!projectId || !commitId) {
        return <div className="text-github-muted">Commit not found.</div>
    }

    if (loading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spin size="large"/>
            </div>
        )
    }

    if (!commit) {
        return <div className="text-github-muted">Commit not found.</div>
    }

    return (
        <div className="flex flex-col gap-4">
            <header className="border-b border-github-border pb-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="flex flex-col gap-2">
                        <h1 className="text-2xl font-normal text-github-text">
                            Commit{' '}
                            <span className="text-mono bg-github-input border border-github-border px-2 py-1 rounded-md text-base">
                                {commit.id.slice(0, 7)}
                            </span>
                        </h1>
                        <div className="flex flex-wrap items-center gap-3 text-sm text-github-muted">
                            <Avatar size={20} src={authorAvatar}>
                                {authorName.charAt(0).toUpperCase()}
                            </Avatar>
                            <span className="text-github-text font-semibold">{authorName}</span>
                            <span>committed {formatRelativeTime(commit.createdAt)}</span>
                            <span className="text-github-muted">· {formatAbsoluteDate(commit.createdAt)}</span>
                            <span className="flex items-center gap-1">
                                <BranchesOutlined/>
                                {branchName}
                            </span>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {commit.parentId ? (
                            <Button
                                className="!bg-github-input !border-github-border !text-github-text"
                                onClick={() => navigate(`/projects/${projectId}/commits/${commit.parentId}?branch=${branchName}`)}
                            >
                                View parent
                            </Button>
                        ) : null}
                        <Button
                            className="!bg-github-input !border-github-border !text-github-text"
                            onClick={() => navigate(`/projects/${projectId}/commits?branch=${branchName}`)}
                        >
                            Back to history
                        </Button>
                    </div>
                </div>

                <div className="mt-3 rounded-md border border-github-border bg-github-panel px-4 py-3">
                    <div className="text-sm text-github-text">{commit.message || 'No commit message'}</div>
                    {commit.parentId ? (
                        <div className="mt-2 text-xs text-github-muted">
                            Parent commit:{' '}
                            <button
                                className="text-github-link"
                                onClick={() => navigate(`/projects/${projectId}/commits/${commit.parentId}?branch=${branchName}`)}
                            >
                                {commit.parentId.slice(0, 7)}
                            </button>
                        </div>
                    ) : (
                        <div className="mt-2 text-xs text-github-muted">Root commit</div>
                    )}
                </div>
            </header>

            <div className="grid grid-cols-[280px,1fr] gap-4">
                <aside className="border border-github-border rounded-md bg-github-panel p-3">
                    <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold text-github-text">File tree</div>
                        <span className="text-xs text-github-muted">{datasets.length} datasets</span>
                    </div>
                    <div className="mt-3">
                        <Input
                            size="small"
                            allowClear
                            prefix={<SearchOutlined className="text-github-muted"/>}
                            placeholder="Filter files"
                            value={filterText}
                            onChange={(event) => setFilterText(event.target.value)}
                        />
                    </div>
                    <div className="mt-3">
                        {treeLoading ? (
                            <div className="flex justify-center py-6">
                                <Spin/>
                            </div>
                        ) : filteredTreeData.length === 0 ? (
                            <Empty description="No files" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
                        ) : (
                            <Tree
                                showIcon
                                blockNode
                                treeData={filteredTreeData}
                                loadData={handleLoadData}
                                onSelect={(_, info) => setSelectedNode(info.node as CommitTreeNode)}
                            />
                        )}
                    </div>
                </aside>

                <main className="flex flex-col gap-4">
                    <section className="border border-github-border rounded-md bg-github-panel p-4">
                        <div className="flex items-center gap-2 text-sm font-semibold text-github-text">
                            <DiffOutlined/>
                            Commit summary
                        </div>
                        <Divider className="!my-3"/>
                        <div className="grid grid-cols-3 gap-4 text-sm">
                            <div>
                                <div className="text-github-muted">Samples (with annotations)</div>
                                <div className="mt-1 text-github-text font-semibold">{commitStats.sampleCount}</div>
                            </div>
                            <div>
                                <div className="text-github-muted">Annotations</div>
                                <div className="mt-1 text-github-text font-semibold">{commitStats.annotationCount}</div>
                            </div>
                            <div>
                                <div className="text-github-muted">Diff overview</div>
                                <div className="mt-1 flex flex-wrap items-center gap-2">
                                    <Tag color="green">+{diffStats.addedSamples} samples</Tag>
                                    <Tag color="red">-{diffStats.removedSamples} samples</Tag>
                                    <Tag color="blue">{diffStats.modifiedSamples} modified</Tag>
                                </div>
                            </div>
                        </div>
                    </section>

                    <section className="border border-github-border rounded-md bg-github-panel p-4">
                        <div className="text-sm font-semibold text-github-text">Selection details</div>
                        <Divider className="!my-3"/>
                        {!selectedNode ? (
                            <div className="text-sm text-github-muted">
                                Select a dataset, sample, or annotation on the left to view details.
                            </div>
                        ) : selectedNode.nodeType === 'dataset' ? (
                            <div className="space-y-2 text-sm">
                                <div className="text-github-text font-semibold">{(selectedNode.dataRef as Dataset)?.name}</div>
                                <div className="text-github-muted">Type: {(selectedNode.dataRef as Dataset)?.type}</div>
                                <div className="text-github-muted">
                                    Samples loaded:{' '}
                                    {samplesByDataset[(selectedNode.dataRef as Dataset)?.id || '']?.length || 0}
                                </div>
                            </div>
                        ) : selectedNode.nodeType === 'sample' ? (
                            <div className="space-y-3 text-sm">
                                <div className="text-github-text font-semibold">
                                    {(selectedNode.dataRef as Sample)?.name || selectedNode.sampleId}
                                </div>
                                <div className="text-github-muted">Sample ID: {selectedNode.sampleId}</div>
                                <div className="text-github-muted">
                                    Annotations loaded: {annotationsBySample[selectedNode.sampleId || '']?.length || 0}
                                </div>
                                {(selectedNode.dataRef as Sample)?.primaryAssetUrl ? (
                                    <div className="rounded-md border border-github-border bg-github-base p-2">
                                        <img
                                            src={(selectedNode.dataRef as Sample).primaryAssetUrl}
                                            alt={(selectedNode.dataRef as Sample).name}
                                            className="max-h-48 rounded"
                                        />
                                    </div>
                                ) : null}
                            </div>
                        ) : (
                            <div className="space-y-3 text-sm">
                                {(() => {
                                    const annotation = selectedNode.dataRef as AnnotationRead
                                    const label = labelMap.get(annotation.labelId)
                                    return (
                                        <>
                                            <div className="text-github-text font-semibold">
                                                {label?.name || annotation.labelId}
                                            </div>
                                            <div className="text-github-muted">Type: {annotation.type}</div>
                                            <div className="text-github-muted">View: {annotation.viewRole}</div>
                                            <div className="text-github-muted">
                                                Confidence: {annotation.confidence ?? '-'}
                                            </div>
                                            <div className="text-github-muted">Annotation ID: {annotation.id}</div>
                                            <div className="rounded-md border border-github-border bg-github-base p-2 text-xs text-github-muted">
                                                <pre className="whitespace-pre-wrap">{JSON.stringify(annotation.data, null, 2)}</pre>
                                            </div>
                                        </>
                                    )
                                })()}
                            </div>
                        )}
                    </section>
                </main>
            </div>
        </div>
    )
}

export default ProjectCommitDetail
