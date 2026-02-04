import React from 'react'
import { Drawer, Menu } from 'antd'
import type { MenuProps } from 'antd'
import type { NavItem } from './types'

export type SideDrawerMenuProps = {
  open: boolean
  onClose: () => void
  items: NavItem[]
  activeKey: string
  onItemClick: (path: string) => void
}

export const SideDrawerMenu: React.FC<SideDrawerMenuProps> = ({
  open,
  onClose,
  items,
  activeKey,
  onItemClick,
}) => {
  const menuItems: MenuProps['items'] = items.map((item) => ({
    key: item.key,
    icon: item.icon,
    label: item.label,
  }))

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="left"
      width={260}
      styles={{ body: { padding: 0 } }}
      title="Menu"
    >
      <Menu
        mode="inline"
        selectedKeys={[activeKey]}
        items={menuItems}
        onClick={(info) => {
          const target = items.find((item) => item.key === info.key)
          if (target) {
            onItemClick(target.path)
            onClose()
          }
        }}
      />
    </Drawer>
  )
}
