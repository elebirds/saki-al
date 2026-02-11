import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Pagination, PaginationProps, Spin} from 'antd';
import {usePagination} from '../../hooks';
import {PaginationResponse} from '../../types/pagination';

type PaginationMeta = {
    total: number;
    limit: number;
    offset: number;
    size: number;
};

export type AdaptivePageSizeMode = 'grid' | 'list' | 'table';

export interface AdaptivePageSizeConfig {
    enabled?: boolean;
    mode: AdaptivePageSizeMode;
    itemHeight: number;
    itemMinWidth?: number;
    rowGap?: number;
    colGap?: number;
    reservedHeight?: number;
    minPageSize?: number;
    maxPageSize?: number;
}

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
    /** Auto-compute pageSize from container and item size. */
    adaptivePageSize?: AdaptivePageSizeConfig;
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
        adaptivePageSize,
    } = props;

    const {page, pageSize, total, setPage, setPageSize, setTotal, updateFromMeta} = usePagination(initialPageSize);
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(false);
    const [manualPageSizeLocked, setManualPageSizeLocked] = useState(false);
    const [containerSize, setContainerSize] = useState({width: 0, height: 0});
    const [paginationHeight, setPaginationHeight] = useState(0);

    const rootRef = useRef<HTMLDivElement>(null);
    const paginationRef = useRef<HTMLDivElement>(null);

    const onErrorRef = useRef(onError);
    const fetchDataRef = useRef(fetchData);
    const onItemsChangeRef = useRef(onItemsChange);
    const onMetaChangeRef = useRef(onMetaChange);
    const onPageChangeRef = useRef(onPageChange);
    const isControlled = controlledPage !== undefined && controlledPageSize !== undefined;
    const activePage = isControlled ? Math.max(1, controlledPage) : page;
    const activePageSize = isControlled ? Math.max(1, controlledPageSize) : pageSize;

    const numericPageSizeOptions = useMemo(() => {
        return (pageSizeOptions || [])
            .map((value) => Number(value))
            .filter((value) => Number.isFinite(value) && value > 0)
            .sort((a, b) => a - b);
    }, [pageSizeOptions]);

    useEffect(() => {
        onErrorRef.current = onError;
    }, [onError]);

    useEffect(() => {
        fetchDataRef.current = fetchData;
    }, [fetchData]);

    useEffect(() => {
        onItemsChangeRef.current = onItemsChange;
    }, [onItemsChange]);

    useEffect(() => {
        onMetaChangeRef.current = onMetaChange;
    }, [onMetaChange]);

    useEffect(() => {
        onPageChangeRef.current = onPageChange;
    }, [onPageChange]);

    useEffect(() => {
        const measure = () => {
            const rootRect = rootRef.current?.getBoundingClientRect();
            const pagerRect = paginationRef.current?.getBoundingClientRect();
            const nextWidth = Math.max(0, Math.floor(rootRect?.width || 0));
            const nextHeight = Math.max(0, Math.floor(rootRect?.height || 0));
            const nextPaginationHeight = Math.max(0, Math.ceil(pagerRect?.height || 0));

            setContainerSize((prev) => {
                if (prev.width === nextWidth && prev.height === nextHeight) return prev;
                return {width: nextWidth, height: nextHeight};
            });
            setPaginationHeight((prev) => (prev === nextPaginationHeight ? prev : nextPaginationHeight));
        };

        measure();

        const rootEl = rootRef.current;
        const pagerEl = paginationRef.current;
        const supportsResizeObserver = typeof ResizeObserver !== 'undefined';
        const observer = supportsResizeObserver ? new ResizeObserver(() => measure()) : null;
        if (observer && rootEl) observer.observe(rootEl);
        if (observer && pagerEl) observer.observe(pagerEl);

        window.addEventListener('resize', measure);
        return () => {
            window.removeEventListener('resize', measure);
            observer?.disconnect();
        };
    }, []);

    useEffect(() => {
        if (resetPageOnRefresh) {
            if (isControlled) {
                onPageChangeRef.current?.(1, activePageSize);
            } else {
                setPage(1);
            }
        }
    }, [refreshKey, resetPageOnRefresh, setPage, isControlled, activePageSize]);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            setLoading(true);
            try {
                const data = await fetchDataRef.current(activePage, activePageSize);
                if (cancelled) return;
                setItems(data.items);
                onItemsChangeRef.current?.(data.items);
                if (isControlled) {
                    setTotal(data.total);
                } else {
                    updateFromMeta({
                        total: data.total,
                        limit: data.limit,
                        offset: data.offset,
                        size: data.size,
                    });
                }
                onMetaChangeRef.current?.({
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
    }, [activePage, activePageSize, updateFromMeta, refreshKey, enabled, isControlled, setTotal]);

    useEffect(() => {
        if (!adaptivePageSize?.enabled) return;
        if (manualPageSizeLocked) return;

        const rowGap = Math.max(0, Number(adaptivePageSize.rowGap ?? 16));
        const colGap = Math.max(0, Number(adaptivePageSize.colGap ?? 16));
        const reservedHeight = Math.max(0, Number(adaptivePageSize.reservedHeight ?? 0));
        const availableWidth = Math.max(0, containerSize.width);
        const availableHeight = Math.max(0, containerSize.height - paginationHeight - reservedHeight);

        if (availableWidth <= 0 || availableHeight <= 0) return;

        let rawSize = 0;
        if (adaptivePageSize.mode === 'grid') {
            const itemMinWidth = Math.max(1, Number(adaptivePageSize.itemMinWidth ?? 0));
            if (itemMinWidth <= 0) return;
            const cols = Math.max(1, Math.floor((availableWidth + colGap) / (itemMinWidth + colGap)));
            const rows = Math.max(1, Math.floor((availableHeight + rowGap) / (Math.max(1, adaptivePageSize.itemHeight) + rowGap)));
            rawSize = cols * rows;
        } else {
            const rows = Math.max(1, Math.floor((availableHeight + rowGap) / (Math.max(1, adaptivePageSize.itemHeight) + rowGap)));
            rawSize = rows;
        }

        if (!Number.isFinite(rawSize) || rawSize <= 0) return;

        const minPageSize = Math.max(1, Number(adaptivePageSize.minPageSize ?? 1));
        const maxPageSize = Math.max(minPageSize, Number(adaptivePageSize.maxPageSize ?? Number.MAX_SAFE_INTEGER));
        let normalized = Math.min(maxPageSize, Math.max(minPageSize, rawSize));

        if (numericPageSizeOptions.length > 0) {
            const lowerOrEqual = numericPageSizeOptions.filter((opt) => opt <= normalized);
            normalized = lowerOrEqual.length > 0 ? lowerOrEqual[lowerOrEqual.length - 1] : numericPageSizeOptions[0];
        }

        if (!Number.isFinite(normalized) || normalized <= 0) return;
        if (normalized === activePageSize) return;

        if (isControlled) {
            onPageChangeRef.current?.(1, normalized);
            return;
        }
        setPageSize(normalized);
        setPage(1);
    }, [
        adaptivePageSize,
        manualPageSizeLocked,
        containerSize.width,
        containerSize.height,
        paginationHeight,
        numericPageSizeOptions,
        activePageSize,
        isControlled,
        setPage,
        setPageSize,
    ]);

    const handlePageChange = (nextPage: number, nextSize?: number) => {
        const resolvedPageSize = nextSize ?? activePageSize;
        if (nextSize && nextSize !== activePageSize) {
            setManualPageSizeLocked(true);
        }
        if (isControlled) {
            onPageChangeRef.current?.(nextPage, resolvedPageSize);
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
        <div ref={rootRef} className="flex h-full min-h-0 flex-col">
            <div className="min-h-0 flex-1">
                <Spin spinning={loading}>
                    {hasData ? renderItems(items, loading) : (!loading && emptyFallback ? emptyFallback : renderItems(items, loading))}
                </Spin>
            </div>
            <div ref={paginationRef} className="shrink-0">{wrappedPagination}</div>
        </div>
    );
}
