export const ROUND_WS_RECONNECT_DELAYS = [1000, 2000, 5000, 10000];

export interface BuildRoundEventsWsUrlOptions {
    afterCursor?: string | null;
    stages?: string[];
}

export const buildRoundEventsWsUrl = (
    roundId: string,
    token: string,
    options?: BuildRoundEventsWsUrlOptions,
): string => {
    const apiBaseUrlRaw = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
    const apiBaseUrl = apiBaseUrlRaw.endsWith('/') ? apiBaseUrlRaw.slice(0, -1) : apiBaseUrlRaw;
    const query = new URLSearchParams();
    query.set('token', token);
    if (options?.afterCursor) query.set('after_cursor', options.afterCursor);
    if (options?.stages && options.stages.length > 0) query.set('stages', options.stages.join(','));
    const suffix = `/rounds/${roundId}/events/ws?${query.toString()}`;
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl.replace(/^http/, 'ws')}${suffix}`;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`;
    return `${protocol}//${window.location.host}${path}${suffix}`;
};
