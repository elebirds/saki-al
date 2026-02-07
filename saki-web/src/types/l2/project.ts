export type TaskType = 'classification' | 'detection' | 'segmentation';
export type ProjectStatus = 'active' | 'archived';

export interface Project {
    id: string;
    name: string;
    description?: string;
    taskType: TaskType;
    status: ProjectStatus;
    config?: Record<string, any>;
    createdAt: string;
    updatedAt: string;
    datasetCount: number;
    labelCount: number;
    branchCount: number;
    commitCount: number;
}

export interface ProjectCreate {
    name: string;
    description?: string;
    taskType?: TaskType;
    datasetIds?: string[];
    config?: Record<string, any>;
}

export interface ProjectReadMinimal {
    id: string;
    name: string;
    taskType: TaskType;
    status: ProjectStatus;
}

export interface ProjectBranch {
    id: string;
    name: string;
    headCommitId: string;
    headCommitMessage?: string | null;
    description?: string | null;
    isProtected: boolean;
    createdAt?: string;
    updatedAt?: string;
}

export type AuthorType = 'user' | 'model' | 'system';

export interface CommitHistoryItem {
    id: string;
    message: string;
    authorType: AuthorType;
    authorId?: string | null;
    parentId?: string | null;
    createdAt: string;
    stats?: Record<string, any>;
}
