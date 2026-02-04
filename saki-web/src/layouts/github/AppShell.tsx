import React from 'react'
import type { MenuProps } from 'antd'
import { useThemeMode } from '../../components/ThemeProvider'
import { SideDrawerMenu } from './SideDrawerMenu'
import { TopHeader } from './TopHeader'
import type { NavItem } from './types'

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
  headerVariant?: 'menu' | 'project'
  showMenuButton?: boolean
  projectTabs?: React.ReactNode
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
  headerVariant = 'menu',
  showMenuButton = false,
  projectTabs,
  contentClassName = 'max-w-[1280px] mx-auto px-6 py-6 h-full flex flex-col',
  headerContainerClassName = 'w-full px-6',
  contentCardClassName = 'bg-github-panel rounded-md p-6 h-full flex flex-col shadow-[0_2px_8px_rgba(27,31,36,0.12)]',
  children,
}) => {
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const { themeMode, setThemeMode } = useThemeMode()

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
          showHorizontalMenu={headerVariant === 'menu'}
          containerClassName={headerContainerClassName}
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
          language={language}
          languageOptions={languageOptions}
          onLanguageChange={onLanguageChange}
          showMenuButton={showMenuButton}
          onMenuButtonClick={() => setDrawerOpen(true)}
          userName={userName}
          userMenuItems={userMenuItems}
          onUserMenuClick={onUserMenuClick}
        />
      ) : null}

      {showMenuButton ? (
        <SideDrawerMenu
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          items={navItems}
          activeKey={activeNavKey}
          onItemClick={onNavItemClick}
        />
      ) : null}

      {projectTabs ? (
        <div className="bg-github-base">
          <div className="w-full px-6">
            {projectTabs}
          </div>
        </div>
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
