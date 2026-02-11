import type {ReactNode} from 'react'

export type NavItem = {
    key: string
    label: string
    path: string
    icon?: ReactNode
}

export type RepoStat = {
    label: string
    count: number
    icon?: ReactNode
    iconKey?: string
    onClick?: () => void
    disabled?: boolean
    hideDropdown?: boolean
    menuItems?: { key: string; label: string }[]
}
