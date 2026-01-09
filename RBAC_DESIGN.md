# RBAC 权限系统设计方案

## 一、设计理念

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| **最小权限原则** | 用户默认无权限，必须显式授权 |
| **职责分离** | 系统角色与资源角色完全分离 |
| **权限继承** | 支持角色继承，减少重复配置 |
| **声明式授权** | 后端 decorator、前端组件，声明即生效 |
| **审计可追溯** | 所有权限变更留有记录 |

### 1.2 权限格式

采用 `resource:action:scope` 三段式格式：

```
permission = "dataset:read:owned"
             ^^^^^^^^ ^^^^ ^^^^^
             资源     操作  作用域
```

### 1.3 作用域定义

| Scope | 说明 | 适用场景 |
|-------|------|---------|
| `all` | 所有该类型资源 | 管理员级别 |
| `owned` | 自己创建的顶级资源 | 数据集创建者 |
| `assigned` | 被分配的资源范围内所有 | 资源成员 |
| `self` | 仅自己创建的子资源 | 标注员只能操作自己的标注 |

**覆盖关系：** `all > owned > assigned > self`

---

## 二、数据模型

### 2.1 核心表结构

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│     User     │────<│ UserSystemRole│>────│     Role     │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  │ has permissions
                                                  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Resource   │────<│ResourceMember│>────│RolePermission│
│  (Dataset)   │     └──────────────┘     └──────────────┘
└──────────────┘
```

### 2.2 Role（角色表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | string | 角色标识符（唯一） |
| display_name | string | 显示名称 |
| description | string | 描述 |
| type | enum | system（系统角色）/ resource（资源角色） |
| parent_id | UUID | 父角色ID（继承） |
| is_system | bool | 是否系统预设（不可删除） |
| is_default | bool | 是否默认角色 |

### 2.3 RolePermission（角色权限表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| role_id | UUID | 角色ID |
| permission | string | 权限标识（resource:action:scope） |
| conditions | JSON | 条件（ABAC 扩展，可选） |

### 2.4 UserSystemRole（用户系统角色）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | UUID | 用户ID |
| role_id | UUID | 角色ID |
| assigned_at | datetime | 分配时间 |
| assigned_by | UUID | 分配人 |
| expires_at | datetime | 过期时间（可选） |

### 2.5 ResourceMember（资源成员表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| resource_type | enum | 资源类型（dataset, project...） |
| resource_id | UUID | 资源ID |
| user_id | UUID | 用户ID |
| role_id | UUID | 资源角色ID |
| created_at | datetime | 创建时间 |
| created_by | UUID | 创建人 |

---

## 三、预设角色

### 3.1 系统角色

| 角色 | 说明 | 核心权限 |
|------|------|---------|
| super_admin | 超级管理员 | `*:*:all`（所有权限） |
| admin | 管理员 | 用户管理、角色管理、所有数据集 |
| user | 普通用户 | 创建数据集、管理自己的数据集 |

### 3.2 资源角色（数据集级别）

| 角色 | 说明 | annotation 权限 |
|------|------|----------------|
| dataset_owner | 所有者 | `*:assigned` |
| dataset_manager | 管理员 | `*:assigned` |
| dataset_reviewer | 审核员 | `read:assigned`, `review:assigned` |
| dataset_annotator | 标注员 | `read:self`, `create:assigned`, `update:self`, `delete:self` |
| dataset_viewer | 查看者 | `read:assigned` |

---

## 四、权限检查流程

### 4.1 检查顺序

```
1. 是否超级管理员？ → 通过
2. 检查系统角色权限
   - 有 all scope？ → 通过
   - 有 owned scope？ → 检查是否资源所有者
3. 检查资源角色权限（如果有资源上下文）
   - 有 assigned scope？ → 通过
   - 有 self scope？ → 检查是否目标资源创建者
4. 无匹配权限 → 拒绝
```

### 4.2 列表过滤

对于列表查询，自动过滤用户可见的资源：

- `all` scope → 返回所有
- `owned` scope → 返回自己创建的
- `assigned` scope → 返回作为成员的
- 合并去重后返回

---

## 五、API 设计

### 5.1 权限相关

```
GET    /api/v1/auth/permissions          # 获取当前用户权限
GET    /api/v1/roles                      # 获取角色列表
POST   /api/v1/roles                      # 创建自定义角色
PUT    /api/v1/roles/{id}                 # 更新角色
DELETE /api/v1/roles/{id}                 # 删除角色（仅自定义）
```

### 5.2 用户角色

```
GET    /api/v1/users/{id}/roles           # 获取用户的系统角色
POST   /api/v1/users/{id}/roles           # 分配系统角色
DELETE /api/v1/users/{id}/roles/{roleId}  # 移除系统角色
```

### 5.3 资源成员

```
GET    /api/v1/datasets/{id}/members      # 获取成员列表
POST   /api/v1/datasets/{id}/members      # 添加成员
PUT    /api/v1/datasets/{id}/members/{userId}  # 更新成员角色
DELETE /api/v1/datasets/{id}/members/{userId}  # 移除成员
```

---

## 六、前端设计

### 6.1 状态管理

```typescript
// permissionStore
{
  userPermissions: {
    userId: string;
    systemRoles: RoleInfo[];
    permissions: string[];
    isSuperAdmin: boolean;
  };
  resourcePermissions: Map<string, ResourcePermissions>;
}
```

### 6.2 核心组件

| 组件 | 用途 |
|------|------|
| `<Authorized>` | 权限控制渲染 |
| `<HasRole>` | 角色检查渲染 |
| `<SuperAdminOnly>` | 仅超级管理员 |
| `<ProtectedRoute>` | 路由权限保护 |

### 6.3 Hooks

| Hook | 用途 |
|------|------|
| `usePermission()` | 基础权限检查 |
| `useResourcePermission()` | 资源级权限检查 |
| `useInitPermissions()` | 初始化权限 |

---

## 七、功能需求验证

| 需求 | 实现方式 |
|------|---------|
| 标注者只能看/改/删自己的标注 | `annotation:*:self` scope |
| 非管理员只看有权限的数据集 | `filter_accessible_resources()` 自动过滤 |
| 角色可自定义权限 | Role + RolePermission 动态存储 |

---

## 八、扩展性

### 8.1 新增资源类型

1. 在 `ResourceType` 枚举添加新类型
2. 在预设角色添加对应资源角色
3. 无需修改核心权限检查逻辑

### 8.2 新增权限

1. 定义新的 `resource:action` 组合
2. 在角色配置中添加
3. 在相应 API 添加权限检查

### 8.3 条件权限（ABAC）

`RolePermission.conditions` 字段预留，可扩展：
- 时间限制
- IP 限制
- 数据量限制
- 等等
