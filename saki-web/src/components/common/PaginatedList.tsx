import React, {useEffect, useRef, useState} from 'react';
import {Pagination, PaginationProps, Spin} from 'antd';
import {usePagination} from '../../hooks';
import {PaginationResponse} from '../../types/pagination';

type PaginationMeta = {
    total: number;
    limit: number;
    offset: number;
    size: number;
};

export interface PaginatedListProps<T> {
    /** Fetch data for the given page/pageSize and return a pagination response. */
    fetchData: (page: number, pageSize: number) => Promise<PaginationResponse<T>>;
    /** Render list content using fetched items. Receive current loading state for skeletons. */
    renderItems: (items: T[], loading: boolean) => React.ReactNode;
    /** Fallback when there is no data (and not loading). */
    emptyFallback?: React.ReactNode;
    /** Optional error handler. */
    onError?: (error: unknown) => void;
    /** Initial page size. */
    initialPageSize?: number;
    /** Page size options for Pagination. */
    pageSizeOptions?: string[];
    /** Extra props to pass down to Ant Pagination. */
    paginationProps?: Partial<PaginationProps>;
    /** Changing this key will trigger a refetch while keeping the current pagination state. */
    refreshKey?: React.Key;
    /** Wrap Pagination with custom layout (e.g., align left/right). */
    renderPaginationWrapper?: (pagination: React.ReactNode) => React.ReactNode;
    /** When refreshKey changes, reset to page 1 before refetching. */
    resetPageOnRefresh?: boolean;
    /** Callback when items are loaded (after state update). */
    onItemsChange?: (items: T[]) => void;
    /** Callback when pagination meta updates. */
    onMetaChange?: (meta: PaginationMeta) => void;
    /** Whether to run the fetch effect (useful to wait for permission checks). Defaults to true. */
    enabled?: boolean;
    /** Controlled pagination current page (1-based). */
    controlledPage?: number;
    /** Controlled pagination page size. */
    controlledPageSize?: number;
    /** Controlled pagination change callback. */
    onPageChange?: (page: number, pageSize: number) => void;
}

/**
 * Generic paginated list wrapper that handles data fetching and Ant Pagination wiring.
 * You provide the fetcher and how to render items; the component handles paging state and loading.
 */
export function PaginatedList<T>(props: PaginatedListProps<T>) {
    const {
        fetchData,
        renderItems,
        emptyFallback,
        onError,
        initialPageSize = 20,
        pageSizeOptions = ['10', '20', '50', '100'],
        paginationProps,
        refreshKey,
        renderPaginationWrapper,
        resetPageOnRefresh = false,
        onItemsChange,
        onMetaChange,
        enabled = true,
        controlledPage,
        controlledPageSize,
        onPageChange,
    } = props;

    const {page, pageSize, total, setPage, setPageSize, setTotal, updateFromMeta} = usePagination(initialPageSize);
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(false);
    const onErrorRef = useRef(onError);
    const fetchDataRef = useRef(fetchData);
    const isControlled = controlledPage !== undefined && controlledPageSize !== undefined;
    const activePage = isControlled ? Math.max(1, controlledPage) : page;
    const activePageSize = isControlled ? Math.max(1, controlledPageSize) : pageSize;

    useEffect(() => {
        onErrorRef.current = onError;
    }, [onError]);

    useEffect(() => {
        fetchDataRef.current = fetchData;
    }, [fetchData]);

    useEffect(() => {
        if (resetPageOnRefresh) {
            if (isControlled) {
                onPageChange?.(1, activePageSize);
            } else {
                setPage(1);
            }
        }
    }, [refreshKey, resetPageOnRefresh, setPage, isControlled, onPageChange, activePageSize]);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            setLoading(true);
            try {
                const data = await fetchDataRef.current(activePage, activePageSize);
                if (cancelled) return;
                setItems(data.items);
                onItemsChange?.(data.items);
                setTotal(data.total);
                if (!isControlled) {
                    updateFromMeta({
                        total: data.total,
                        limit: data.limit,
                        offset: data.offset,
                        size: data.size,
                    });
                }
                onMetaChange?.({
                    total: data.total,
                    limit: data.limit,
                    offset: data.offset,
                    size: data.size,
                });
            } catch (error) {
                if (!cancelled) {
                    onErrorRef.current?.(error);
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        if (enabled) {
            load();
        }

        return () => {
            cancelled = true;
        };
    }, [activePage, activePageSize, updateFromMeta, refreshKey, enabled, isControlled, setTotal, onMetaChange, onItemsChange]);

    const handlePageChange = (nextPage: number, nextSize?: number) => {
        const resolvedPageSize = nextSize ?? activePageSize;
        if (isControlled) {
            onPageChange?.(nextPage, resolvedPageSize);
            return;
        }
        const sizeChanged = nextSize && nextSize !== pageSize;
        if (sizeChanged) {
            setPageSize(nextSize);
            setPage(1);
        } else {
            setPage(nextPage);
        }
    };

    const paginationNode = (
        <Pagination
            size="small"
            current={activePage}
            pageSize={activePageSize}
            total={total}
            showSizeChanger
            showQuickJumper
            pageSizeOptions={pageSizeOptions}
            onChange={handlePageChange}
            showTotal={(tot, range) =>
                range ? `${range[0]}-${range[1]} of ${tot}` : `${tot}`
            }
            {...paginationProps}
        />
    );

    const wrappedPagination = renderPaginationWrapper
        ? renderPaginationWrapper(paginationNode)
        : <div className="mt-4 flex justify-end">{paginationNode}</div>;

    const hasData = items.length > 0;

    return (
        <div className="flex h-full flex-col">
            <Spin spinning={loading}>
                {hasData ? renderItems(items, loading) : (!loading && emptyFallback ? emptyFallback : renderItems(items, loading))}
            </Spin>
            {wrappedPagination}
        </div>
    );
}
