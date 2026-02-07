import {useCallback, useMemo, useState} from 'react';

interface PaginationMeta {
    total: number;
    limit: number;
    offset: number;
    size: number;
}

export function usePagination(initialPageSize: number = 20) {
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(initialPageSize);
    const [total, setTotal] = useState(0);

    const updateFromMeta = useCallback((meta: PaginationMeta) => {
        setTotal(meta.total);
        setPageSize(meta.limit);
        const derivedPage = Math.floor(meta.offset / meta.limit) + 1;
        setPage(derivedPage);
    }, []);

    const hasPrev = useMemo(() => page > 1, [page]);
    const hasNext = useMemo(() => page * pageSize < total, [page, pageSize, total]);

    const goToPage = useCallback((target: number) => {
        setPage(Math.max(1, target));
    }, []);

    const nextPage = useCallback(() => {
        if (hasNext) {
            setPage((p) => p + 1);
        }
    }, [hasNext]);

    const prevPage = useCallback(() => {
        if (hasPrev) {
            setPage((p) => Math.max(1, p - 1));
        }
    }, [hasPrev]);

    return {
        page,
        pageSize,
        total,
        hasPrev,
        hasNext,
        setPage: goToPage,
        setPageSize,
        setTotal,
        nextPage,
        prevPage,
        updateFromMeta,
    };
}
