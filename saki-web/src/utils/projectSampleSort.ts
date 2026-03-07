export type ProjectSampleSortBy = 'name' | 'createdAt' | 'updatedAt';
export type ProjectSampleSortOrder = 'asc' | 'desc';

export interface ParsedProjectSampleSort {
    sortBy: ProjectSampleSortBy;
    sortOrder: ProjectSampleSortOrder;
    sortValue: `${ProjectSampleSortBy}:${ProjectSampleSortOrder}`;
}

const DEFAULT_SORT_BY: ProjectSampleSortBy = 'createdAt';
const DEFAULT_SORT_ORDER: ProjectSampleSortOrder = 'desc';

const VALID_SORT_BY = new Set<ProjectSampleSortBy>(['name', 'createdAt', 'updatedAt']);
const VALID_SORT_ORDER = new Set<ProjectSampleSortOrder>(['asc', 'desc']);

export function parseProjectSampleSort(input?: string | null): ParsedProjectSampleSort {
    const raw = String(input || '').trim();
    const [rawSortBy, rawSortOrder] = raw.split(':');

    const sortBy = VALID_SORT_BY.has(rawSortBy as ProjectSampleSortBy)
        ? (rawSortBy as ProjectSampleSortBy)
        : DEFAULT_SORT_BY;
    const sortOrder = VALID_SORT_ORDER.has(rawSortOrder as ProjectSampleSortOrder)
        ? (rawSortOrder as ProjectSampleSortOrder)
        : DEFAULT_SORT_ORDER;

    return {
        sortBy,
        sortOrder,
        sortValue: `${sortBy}:${sortOrder}`,
    };
}

