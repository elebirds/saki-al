import React from 'react'
import {Button} from 'antd'
import {
    EyeOutlined,
    FileTextOutlined,
    FireOutlined,
    ForkOutlined,
    SettingOutlined,
    StarOutlined
} from '@ant-design/icons'
import {useTranslation} from 'react-i18next'

export type LanguageStat = {
    name: string
    percent: number
    color: string
}

export type SidebarProps = {
    aboutTitle?: string
    aboutText?: string
    languages?: LanguageStat[]
}

const defaultLanguages: LanguageStat[] = [
    {name: 'TypeScript', percent: 62, color: '#3178c6'},
    {name: 'Python', percent: 34, color: '#3572A5'},
    {name: 'Shell', percent: 4, color: '#89e051'},
]

export const Sidebar: React.FC<SidebarProps> = ({
                                                    aboutTitle,
                                                    aboutText,
                                                    languages,
                                                }) => {
    const {t} = useTranslation()
    const resolvedLanguages = languages || defaultLanguages
    const resolvedAboutTitle = aboutTitle || t('layout.sidebar.about')
    const resolvedAboutText = aboutText || t('layout.sidebar.aboutText')

    return (
        <aside className="w-[296px] shrink-0 hidden lg:block">
            <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold text-github-text">{resolvedAboutTitle}</h3>
                    <SettingOutlined className="text-github-muted"/>
                </div>
                <p className="text-sm mb-4 text-github-text">{resolvedAboutText}</p>
                <div className="space-y-2 text-sm">
                    <Button type="text" className="!text-github-muted hover:!text-github-link">
                        <FileTextOutlined className="mr-2"/> {t('layout.sidebar.readme')}
                    </Button>
                    <Button type="text" className="!text-github-muted hover:!text-github-link">
                        <FireOutlined className="mr-2"/> {t('layout.sidebar.activity')}
                    </Button>
                    <div className="flex items-center gap-2 text-github-muted">
                        <StarOutlined/>
                        <span className="font-semibold text-github-text">0</span> {t('layout.sidebar.stars')}
                    </div>
                    <div className="flex items-center gap-2 text-github-muted">
                        <EyeOutlined/>
                        <span className="font-semibold text-github-text">0</span> {t('layout.sidebar.watching')}
                    </div>
                    <div className="flex items-center gap-2 text-github-muted">
                        <ForkOutlined/>
                        <span className="font-semibold text-github-text">0</span> {t('layout.sidebar.forks')}
                    </div>
                </div>
            </div>

            <div className="border-t border-github-border pt-4 mb-4">
                <h3 className="font-semibold text-github-text mb-2">{t('layout.sidebar.releases')}</h3>
                <p className="text-sm text-github-muted mb-1">{t('layout.sidebar.noReleases')}</p>
                <Button type="link" className="!text-github-link !p-0">{t('layout.sidebar.createRelease')}</Button>
            </div>

            <div className="border-t border-github-border pt-4 mb-4">
                <h3 className="font-semibold text-github-text mb-2">{t('layout.sidebar.packages')}</h3>
                <p className="text-sm text-github-muted mb-1">{t('layout.sidebar.noPackages')}</p>
                <Button type="link" className="!text-github-link !p-0">{t('layout.sidebar.publishPackage')}</Button>
            </div>

            <div className="border-t border-github-border pt-4">
                <h3 className="font-semibold text-github-text mb-3">{t('layout.sidebar.languages')}</h3>
                <div className="flex h-2 rounded-full overflow-hidden mb-3">
                    {resolvedLanguages.map((lang) => (
                        <div
                            key={lang.name}
                            className="h-full"
                            style={{width: `${lang.percent}%`, backgroundColor: lang.color}}
                        />
                    ))}
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {resolvedLanguages.map((lang) => (
                        <div key={lang.name} className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: lang.color}}/>
                            <span className="font-semibold text-github-text">{lang.name}</span>
                            <span className="text-github-muted">{lang.percent}%</span>
                        </div>
                    ))}
                </div>
            </div>
        </aside>
    )
}
