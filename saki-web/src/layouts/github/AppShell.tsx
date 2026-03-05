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
    onQuickActionClick?: (action: 'new-project' | 'new-dataset') => void
    onRepoOwnerClick?: () => void
    onRepoNameClick?: () => void
    userName?: string
    userAvatarUrl?: string
    userMenuItems: MenuProps['items']
    onUserMenuClick: MenuProps['onClick']
    footerText?: string
    showHeader?: boolean
    showHeaderBorder?: boolean
    headerSubnav?: React.ReactNode
    contentClassName?: string
    headerContainerClassName?: string
    contentCardClassName?: string
    layoutMode?: 'flow' | 'fill'
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
                                                      onQuickActionClick,
                                                      onRepoOwnerClick,
                                                      onRepoNameClick,
                                                      userName,
                                                      userAvatarUrl,
                                                      userMenuItems,
                                                      onUserMenuClick,
                                                      footerText,
                                                      showHeader = true,
                                                      showHeaderBorder = true,
                                                      headerSubnav,
                                                      contentClassName = 'max-w-[1280px] mx-auto px-6 py-6 min-h-full flex flex-col',
                                                      headerContainerClassName = 'w-full px-6',
                                                      contentCardClassName = 'bg-github-panel rounded-md p-6 min-h-full flex flex-col shadow-[0_2px_8px_rgba(27,31,36,0.12)]',
                                                      layoutMode = 'flow',
                                                      children,
                                                  }) => {
    const {themeMode, setThemeMode} = useThemeMode()
    const isFillMode = layoutMode === 'fill'

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
                    onQuickActionClick={onQuickActionClick}
                    onRepoOwnerClick={onRepoOwnerClick}
                    onRepoNameClick={onRepoNameClick}
                    userName={userName}
                    userAvatarUrl={userAvatarUrl}
                    userMenuItems={userMenuItems}
                    onUserMenuClick={onUserMenuClick}
                />
            ) : null}
            {headerSubnav ? (
                <div className="border-b border-github-border bg-[var(--github-header)]">
                    <div className={headerContainerClassName}>{headerSubnav}</div>
                </div>
            ) : null}

            <main className="flex-1 overflow-auto">
                <div className={isFillMode ? 'flex h-full flex-col' : 'flex min-h-full flex-col'}>
                    <div className={isFillMode ? `w-full flex-1 ${contentClassName}` : `w-full ${contentClassName}`}>
                        <div className={contentCardClassName}>{children}</div>
                    </div>
                    {footerText ? (
                        <div className={`${isFillMode ? '' : 'mt-auto '}border-t border-github-border py-4 text-center text-xs text-github-muted`}>
                            {footerText}
                        </div>
                    ) : null}
                </div>
            </main>
        </div>
    )
}
