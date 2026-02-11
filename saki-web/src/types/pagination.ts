export interface PaginationResponse<T> {
    items: T[];
    total: number;
    offset: number;
    limit: number;
    size: number;
    hasMore: boolean;
}

export function createEmptyPaginationResponse<T>(
    pageSize: number,
    page: number = 1,
): PaginationResponse<T> {
    const normalizedPageSize = Math.max(1, Number(pageSize) || 1);
    const normalizedPage = Math.max(1, Number(page) || 1);
    return {
        items: [],
        total: 0,
        offset: (normalizedPage - 1) * normalizedPageSize,
        limit: normalizedPageSize,
        size: 0,
        hasMore: false,
    };
}
