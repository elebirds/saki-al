import React from 'react'
import type {MenuProps} from 'antd'
import {Avatar, Button, Dropdown, Switch} from 'antd'
import {
    DownOutlined,
    GlobalOutlined,
    MoonOutlined,
    PlusOutlined,
    SunOutlined,
} from '@ant-design/icons'
import type {NavItem} from './types'
import {useTranslation} from 'react-i18next'
import sakiLogo from '../../assets/saki-logo.png'

export type TopHeaderProps = {
    appTitle: string
    repoOwner: string
    repoName: string
    menuItems?: NavItem[]
    activeMenuKey?: string
    onMenuItemClick?: (path: string) => void
    showHorizontalMenu?: boolean
    showBorder?: boolean
    containerClassName?: string
    themeMode: 'light' | 'dark'
    onThemeModeChange: (mode: 'light' | 'dark') => void
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
}

export const TopHeader: React.FC<TopHeaderProps> = ({
                                                        appTitle,
                                                        repoOwner,
                                                        repoName,
                                                        menuItems = [],
                                                        activeMenuKey,
                                                        onMenuItemClick,
                                                        showHorizontalMenu = false,
                                                        showBorder = true,
                                                        containerClassName = 'max-w-[1280px] mx-auto px-6',
                                                        themeMode,
                                                        onThemeModeChange,
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
                                                    }) => {
    const {t} = useTranslation()
    const languageMenuItems: MenuProps['items'] = languageOptions.map((option) => ({
        key: option.value,
        label: option.label,
    }))
    const plusMenuItems: MenuProps['items'] = [
        {key: 'new-project', label: t('layout.header.newProject')},
        {key: 'new-dataset', label: t('layout.header.newDataset')},
    ]
    const resolvedUserName = userName || t('layout.header.user')
    const userInitial = resolvedUserName.trim().charAt(0).toUpperCase() || '?'

    return (
        <header className={`bg-[var(--github-header)] ${showBorder ? 'border-b border-github-border' : ''}`}>
            <div className={`${containerClassName} py-4`}>
                <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
                    <div className="flex items-center gap-4 justify-self-start">
                        <div className="flex items-center gap-3">
                            <img
                                src={sakiLogo}
                                alt={`${repoOwner}/${repoName} logo`}
                                className="h-8 w-8 rounded-sm object-cover [image-rendering:pixelated]"
                            />
                            <div className="flex items-center gap-1 text-sm">
                                <span
                                    className={`text-github-text ${onRepoOwnerClick ? 'hover:underline cursor-pointer' : ''}`}
                                    onClick={onRepoOwnerClick}
                                >
                                    {repoOwner}
                                </span>
                                <span className="text-github-muted">/</span>
                                <span
                                    className={`text-github-text font-semibold ${onRepoNameClick ? 'hover:underline cursor-pointer' : ''}`}
                                    onClick={onRepoNameClick}
                                >
                                    {repoName}
                                </span>
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
                        <div/>
                    )}

                    <div className="flex items-center justify-self-end gap-2">
                        <Switch
                            size="small"
                            checked={themeMode === 'dark'}
                            onChange={(checked) => onThemeModeChange(checked ? 'dark' : 'light')}
                            checkedChildren={<MoonOutlined/>}
                            unCheckedChildren={<SunOutlined/>}
                        />
                        <Dropdown
                            trigger={['hover']}
                            menu={{
                                items: languageMenuItems,
                                selectable: true,
                                selectedKeys: [language],
                                onClick: (info) => onLanguageChange(String(info.key)),
                            }}
                        >
                            <Button type="text" icon={<GlobalOutlined/>} className="!text-github-muted"/>
                        </Dropdown>
                        <Dropdown
                            menu={{
                                items: plusMenuItems,
                                onClick: (info) => onQuickActionClick?.(info.key as 'new-project' | 'new-dataset'),
                            }}
                            placement="bottomRight"
                        >
                            <Button type="text" icon={<PlusOutlined/>} className="!text-github-muted" disabled={!onQuickActionClick}/>
                        </Dropdown>
                        <Dropdown menu={{items: userMenuItems, onClick: onUserMenuClick}} placement="bottomRight">
                            <Button type="text" className="!text-github-muted">
                                <div className="flex items-center gap-2">
                                    <Avatar
                                        size={28}
                                        src={userAvatarUrl || undefined}
                                        className={userAvatarUrl ? undefined : '!bg-gradient-to-br !from-green-400 !to-blue-500'}
                                    >
                                        {userInitial}
                                    </Avatar>
                                    <span className="hidden lg:inline text-github-text">{resolvedUserName}</span>
                                    <DownOutlined className="text-github-muted"/>
                                </div>
                            </Button>
                        </Dropdown>
                    </div>
                </div>
            </div>
        </header>
    )
}
