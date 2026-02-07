export interface PaginationResponse<T> {
    items: T[];
    total: number;
    offset: number;
    limit: number;
    size: number;
    hasMore: boolean;
}
