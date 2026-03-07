import {AuthorType} from './project';

export interface CommitRead {
    id: string;
    commitHash: string;
    projectId: string;
    message: string;
    authorType: AuthorType;
    authorId?: string | null;
    parentId?: string | null;
    stats?: Record<string, any>;
    extra?: Record<string, any>;
    createdAt: string;
    updatedAt: string;
}

export interface CommitDiff {
    fromCommitId: string;
    toCommitId: string;
    addedSamples: string[];
    removedSamples: string[];
    modifiedAnnotations: Record<string, { added: string[]; removed: string[] }>;
}
