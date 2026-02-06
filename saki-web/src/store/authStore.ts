import {create} from 'zustand';
import {persist} from 'zustand/middleware';
import {User} from '../types';

interface AuthState {
    token: string | null;
    refreshToken: string | null;
    user: User | null;
    isAuthenticated: boolean;
    setTokens: (accessToken: string, refreshToken: string) => void;
    setToken: (token: string) => void;
    setUser: (user: User) => void;
    logout: () => void;
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            token: null,
            refreshToken: null,
            user: null,
            isAuthenticated: false,
            setTokens: (accessToken, refreshToken) =>
                set({token: accessToken, refreshToken, isAuthenticated: !!accessToken}),
            setToken: (token) => set({token, isAuthenticated: !!token}),
            setUser: (user) => set({user}),
            logout: () => set({token: null, refreshToken: null, user: null, isAuthenticated: false}),
        }),
        {
            name: 'auth-storage',
        }
    )
);
