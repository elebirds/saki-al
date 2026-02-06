/**
 * System Store
 *
 * Manages system-level cached data like available types.
 */

import {create} from 'zustand';
import {api} from '../services/api';
import {AvailableTypes, AvailableTypesResponse, TypeInfo} from '../types';

interface SystemState {
    availableTypes: AvailableTypes | null;
    loading: boolean;
    error: string | null;
    hasLoaded: boolean;

    loadAvailableTypes: () => Promise<void>;
    refreshAvailableTypes: () => Promise<void>;
    clearAvailableTypes: () => void;
}

function normalizeAvailableTypes(types: AvailableTypesResponse): AvailableTypes {
    const taskTypes: TypeInfo[] = types.taskTypes ?? [];
    const datasetTypes: TypeInfo[] = types.datasetTypes ?? [];

    return {
        taskTypes,
        datasetTypes,
    };
}

export const useSystemStore = create<SystemState>()((set, get) => ({
    availableTypes: null,
    loading: false,
    error: null,
    hasLoaded: false,

    loadAvailableTypes: async () => {
        const {loading, hasLoaded} = get();
        if (loading || hasLoaded) {
            return;
        }

        set({loading: true, error: null});
        try {
            const types = await api.getAvailableTypes();
            set({
                availableTypes: normalizeAvailableTypes(types),
                hasLoaded: true,
            });
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load types';
            set({error: message, hasLoaded: false});
            console.error('Failed to load available types:', err);
        } finally {
            set({loading: false});
        }
    },

    refreshAvailableTypes: async () => {
        set({loading: true, error: null});
        try {
            const types = await api.getAvailableTypes();
            set({
                availableTypes: normalizeAvailableTypes(types),
                hasLoaded: true,
            });
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load types';
            set({error: message, hasLoaded: false});
            console.error('Failed to refresh available types:', err);
        } finally {
            set({loading: false});
        }
    },

    clearAvailableTypes: () => {
        set({availableTypes: null, hasLoaded: false, error: null});
    },
}));
