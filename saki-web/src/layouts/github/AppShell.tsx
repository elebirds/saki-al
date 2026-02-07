import React from 'react'
import type {MenuProps} from 'antd'
import {useThemeMode} from '../../components/ThemeProvider'
import {TopHeader} from './TopHeader'
import type {NavItem} from './types'

export type AppShellProps = {
    appTitle: string
    repoOwner: string
    repoName: string
    navItems: NavItem[]
    activeNavKey: string
    onNavItemClick: (path: string) => void
    language: string
    languageOptions: { value: string; label: string }[]
    onLanguageChange: (lng: string) => void
    userName?: string
    userMenuItems: MenuProps['items']
    onUserMenuClick: MenuProps['onClick']
    footerText?: string
    showHeader?: boolean
    showHeaderBorder?: boolean
    contentClassName?: string
    headerContainerClassName?: string
    contentCardClassName?: string
    children: React.ReactNode
}

export const AppShell: React.FC<AppShellProps> = ({
                                                      appTitle,
                                                      repoOwner,
                                                      repoName,
                                                      navItems,
                                                      activeNavKey,
                                                      onNavItemClick,
                                                      language,
                                                      languageOptions,
                                                      onLanguageChange,
                                                      userName,
                                                      userMenuItems,
                                                      onUserMenuClick,
                                                      footerText,
                                                      showHeader = true,
                                                      showHeaderBorder = true,
                                                      contentClassName = 'max-w-[1280px] mx-auto px-6 py-6 h-full flex flex-col',
                                                      headerContainerClassName = 'w-full px-6',
                                                      contentCardClassName = 'bg-github-panel rounded-md p-6 h-full flex flex-col shadow-[0_2px_8px_rgba(27,31,36,0.12)]',
                                                      children,
                                                  }) => {
    const {themeMode, setThemeMode} = useThemeMode()

    return (
        <div className="flex h-screen flex-col bg-github-base text-github-text">
            {showHeader ? (
                <TopHeader
                    appTitle={appTitle}
                    repoOwner={repoOwner}
                    repoName={repoName}
                    menuItems={navItems}
                    activeMenuKey={activeNavKey}
                    onMenuItemClick={onNavItemClick}
                    showHorizontalMenu
                    showBorder={showHeaderBorder}
                    containerClassName={headerContainerClassName}
                    themeMode={themeMode}
                    onThemeModeChange={setThemeMode}
                    language={language}
                    languageOptions={languageOptions}
                    onLanguageChange={onLanguageChange}
                    userName={userName}
                    userMenuItems={userMenuItems}
                    onUserMenuClick={onUserMenuClick}
                />
            ) : null}

            <main className="flex-1 overflow-auto">
                <div className={contentClassName}>
                    <div className={contentCardClassName}>{children}</div>
                </div>
            </main>

            {footerText ? (
                <div className="border-t border-github-border py-4 text-center text-xs text-github-muted">
                    {footerText}
                </div>
            ) : null}
        </div>
    )
}
