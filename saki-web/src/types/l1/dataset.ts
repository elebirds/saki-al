// ============================================================================
// Dataset - The central data repository
// Datasets are now immutable collections of samples.
// ============================================================================

export type DatasetType = 'classic' | 'fedo';

export interface Dataset {
    id: string;
    name: string;
    description?: string;
    type: DatasetType;
    allowDuplicateSampleNames?: boolean;
    isPublic: boolean;
    ownerId: string;
    createdAt: string;
    updatedAt: string;
}

export interface DatasetCreate {
    name: string;
    description?: string;
    type: DatasetType;
    allowDuplicateSampleNames?: boolean;
    isPublic?: boolean;
}

export interface DatasetUpdate {
    name?: string;
    description?: string;
    allowDuplicateSampleNames?: boolean;
    isPublic?: boolean;
}
