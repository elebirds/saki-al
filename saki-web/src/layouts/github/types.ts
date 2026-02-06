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
    menuItems?: { key: string; label: string }[]
}
