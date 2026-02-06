// ============================================================================
// Label - Annotation label belonging to a Dataset
// ============================================================================

export interface Label {
    id: string;
    datasetId: string;
    name: string;
    color: string;
    description?: string;
    sortOrder: number;
    annotationCount: number;
    createdAt: string;
    updatedAt?: string;
}

export interface LabelCreate {
    name: string;
    color?: string;
    description?: string;
    sortOrder?: number;
}

export interface LabelUpdate {
    name?: string;
    color?: string;
    description?: string;
    sortOrder?: number;
}

// Legacy type for backward compatibility with Project labels
export interface LabelConfig {
    name: string;
    color: string;
}