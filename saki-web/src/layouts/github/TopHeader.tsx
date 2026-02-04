import React from 'react'
import { Avatar, Button, Dropdown, Select, Switch } from 'antd'
import type { MenuProps } from 'antd'
import {
  BellOutlined,
  DownOutlined,
  GithubOutlined,
  MenuOutlined,
  MoonOutlined,
  PlusOutlined,
  SunOutlined,
  UserOutlined,
} from '@ant-design/icons'
import type { NavItem } from './types'

export type TopHeaderProps = {
  appTitle: string
  repoOwner: string
  repoName: string
  menuItems?: NavItem[]
  activeMenuKey?: string
  onMenuItemClick?: (path: string) => void
  showHorizontalMenu?: boolean
  containerClassName?: string
  themeMode: 'light' | 'dark'
  onThemeModeChange: (mode: 'light' | 'dark') => void
  language: string
  languageOptions: { value: string; label: string }[]
  onLanguageChange: (lng: string) => void
  showMenuButton?: boolean
  onMenuButtonClick?: () => void
  userName?: string
  userMenuItems: MenuProps['items']
  onUserMenuClick: MenuProps['onClick']
}

const plusMenuItems: MenuProps['items'] = [
  { key: 'new-project', label: 'New project' },
  { key: 'new-dataset', label: 'New dataset' },
]

export const TopHeader: React.FC<TopHeaderProps> = ({
  appTitle,
  repoOwner,
  repoName,
  menuItems = [],
  activeMenuKey,
  onMenuItemClick,
  showHorizontalMenu = false,
  containerClassName = 'max-w-[1280px] mx-auto px-6',
  themeMode,
  onThemeModeChange,
  language,
  languageOptions,
  onLanguageChange,
  showMenuButton = false,
  onMenuButtonClick,
  userName,
  userMenuItems,
  onUserMenuClick,
}) => {
  return (
    <header className="border-b border-github-border bg-[var(--github-header)]">
      <div className={`${containerClassName} py-4`}>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
          <div className="flex items-center gap-4 justify-self-start">
            {showMenuButton ? (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={onMenuButtonClick}
                className="!text-github-text"
              />
            ) : null}
            <div className="flex items-center gap-3">
              <GithubOutlined className="text-github-text text-2xl" />
              <div className="flex items-center gap-1 text-sm">
                <span className="text-github-text hover:underline cursor-pointer">{repoOwner}</span>
                <span className="text-github-muted">/</span>
                <span className="text-github-text font-semibold hover:underline cursor-pointer">{repoName}</span>
              </div>
            </div>
            <span className="ml-2 text-xs text-github-muted">{appTitle}</span>
          </div>

          {showHorizontalMenu && menuItems.length > 0 ? (
            <div className="min-w-0 px-2 flex justify-center">
              <div className="flex items-center gap-2 text-sm overflow-x-auto">
                {menuItems.map((item) => {
                  const isActive = item.key === activeMenuKey
                  return (
                    <Button
                      key={item.key}
                      type="text"
                      icon={item.icon}
                      onClick={() => onMenuItemClick?.(item.path)}
                      className={`!flex !items-center !gap-2 !px-2 !py-1 !rounded-none !border-b-2 !whitespace-nowrap !transition-colors ${
                        isActive
                          ? '!border-github-accent !text-github-text'
                          : '!border-transparent !text-github-muted hover:!text-github-text'
                      }`}
                    >
                      {item.label}
                    </Button>
                  )
                })}
              </div>
            </div>
          ) : (
            <div />
          )}

          <div className="flex items-center justify-self-end gap-2">
            <Switch
              size="small"
              checked={themeMode === 'dark'}
              onChange={(checked) => onThemeModeChange(checked ? 'dark' : 'light')}
              checkedChildren={<MoonOutlined />}
              unCheckedChildren={<SunOutlined />}
            />
            <Select
              value={language}
              onChange={onLanguageChange}
              options={languageOptions}
              size="small"
              className="min-w-[120px]"
            />
            <Dropdown menu={{ items: plusMenuItems }} placement="bottomRight">
              <Button type="text" icon={<PlusOutlined />} className="!text-github-muted" />
            </Dropdown>
            <Button type="text" icon={<BellOutlined />} className="!text-github-muted" />
            <Dropdown menu={{ items: userMenuItems, onClick: onUserMenuClick }} placement="bottomRight">
              <Button type="text" className="!text-github-muted">
                <div className="flex items-center gap-2">
                  <Avatar
                    size={28}
                    icon={<UserOutlined />}
                    className="bg-gradient-to-br from-orange-400 to-pink-500"
                  />
                  <span className="hidden lg:inline text-github-text">{userName || 'User'}</span>
                  <DownOutlined className="text-github-muted" />
                </div>
              </Button>
            </Dropdown>
          </div>
        </div>
      </div>
    </header>
  )
}
