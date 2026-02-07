import React from 'react'
import {ConfigProvider, theme as antdTheme} from 'antd'

export type ThemeMode = 'light' | 'dark'

type ThemeContextValue = {
    themeMode: ThemeMode
    setThemeMode: (mode: ThemeMode) => void
    toggleTheme: () => void
}

const ThemeContext = React.createContext<ThemeContextValue | undefined>(undefined)

const getInitialTheme = (): ThemeMode => {
    if (typeof window === 'undefined') return 'light'
    const stored = window.localStorage.getItem('saki-theme')
    if (stored === 'light' || stored === 'dark') return stored
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark'
    }
    return 'light'
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({children}) => {
    const [themeMode, setThemeMode] = React.useState<ThemeMode>(getInitialTheme)

    React.useEffect(() => {
        const root = document.documentElement
        const body = document.body
        if (themeMode === 'dark') {
            root.classList.add('dark')
            body.classList.add('dark')
        } else {
            root.classList.remove('dark')
            body.classList.remove('dark')
        }
        try {
            window.localStorage.setItem('saki-theme', themeMode)
        } catch {
            // ignore storage errors
        }
    }, [themeMode])

    const toggleTheme = React.useCallback(() => {
        setThemeMode((prev) => (prev === 'dark' ? 'light' : 'dark'))
    }, [])

    const isDark = themeMode === 'dark'

    return (
        <ThemeContext.Provider value={{themeMode, setThemeMode, toggleTheme}}>
            <ConfigProvider
                theme={{
                    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
                    token: {
                        colorBgBase: isDark ? '#0d1117' : '#ffffff',
                        colorBgContainer: isDark ? '#161b22' : '#ffffff',
                        colorBgElevated: isDark ? '#161b22' : '#ffffff',
                        colorTextBase: isDark ? '#f1f6fc' : '#1F2328',
                        colorTextSecondary: isDark ? '#8b949e' : '#59636F',
                        colorBorder: isDark ? '#3d444e' : '#d0d7de',
                        colorBorderSecondary: isDark ? '#30363d' : '#eaeef2',
                        colorPrimary: isDark ? '#2f81f7' : '#0969da',
                    },
                }}
            >
                {children}
            </ConfigProvider>
        </ThemeContext.Provider>
    )
}

export const useThemeMode = () => {
    const ctx = React.useContext(ThemeContext)
    if (!ctx) {
        throw new Error('useThemeMode must be used within ThemeProvider')
    }
    return ctx
}
