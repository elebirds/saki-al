import React, {useMemo} from 'react';

import {RoundArtifactTableRow} from './types';
import TaskArtifactTableCard, {TaskArtifactTableRow} from '../components/TaskArtifactTableCard';

interface ArtifactTableCardProps {
    roundArtifactRows: RoundArtifactTableRow[];
    artifactUrls: Record<string, string>;
    resolveArtifactUrl: (row: TaskArtifactTableRow) => Promise<string | null>;
}

const ArtifactTableCard: React.FC<ArtifactTableCardProps> = ({roundArtifactRows, artifactUrls, resolveArtifactUrl}) => {
    const rows = useMemo<TaskArtifactTableRow[]>(
        () => roundArtifactRows.map((item) => ({
            key: item.key,
            taskId: item.taskId,
            name: item.name,
            kind: item.kind,
            size: item.size,
            createdAt: item.createdAt,
            sourceLabel: item.stageLabel,
            sourceClassLabel: item.artifactClassLabel,
            sequenceLabel: `#${item.stepIndex}`,
        })),
        [roundArtifactRows],
    );

    return (
        <TaskArtifactTableCard
            title="制品"
            emptyDescription="当前 Round 暂无制品"
            rows={rows}
            artifactUrls={artifactUrls}
            resolveArtifactUrl={resolveArtifactUrl}
            showSource
            showSourceClass
            showSequence
        />
    );
};

export default ArtifactTableCard;
