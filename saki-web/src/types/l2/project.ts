import {AnnotationType} from './annotation';
import {DatasetType} from '../l1/dataset';

export type TaskType = 'classification' | 'detection' | 'segmentation';
export type ProjectStatus = 'active' | 'archived';

export interface Project {
    id: string;
    name: string;
    description?: string;
    taskType: TaskType;
    datasetType: DatasetType;
    enabledAnnotationTypes: AnnotationType[];
    status: ProjectStatus;
    config?: Record<string, any>;
    createdAt: string;
    updatedAt: string;
    datasetCount: number;
    labelCount: number;
    branchCount: number;
    commitCount: number;
    annotationCount: number;
    forkCount: number;
}

export interface ProjectCreate {
    name: string;
    description?: string;
    taskType?: TaskType;
    datasetType?: DatasetType;
    enabledAnnotationTypes: AnnotationType[];
    datasetIds?: string[];
    config?: Record<string, any>;
}

export interface ProjectForkCreate {
    name: string;
    description?: string;
    config?: Record<string, any>;
}

export interface ProjectReadMinimal {
    id: string;
    name: string;
    taskType: TaskType;
    datasetType: DatasetType;
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
    commitHash: string;
    message: string;
    authorType: AuthorType;
    authorId?: string | null;
    parentId?: string | null;
    createdAt: string;
    stats?: Record<string, any>;
}
