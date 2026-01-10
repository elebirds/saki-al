# RBAC 权限系统核心函数解析

本文档详细解析权限系统中重要函数的设计、参数作用、逻辑流程以及为什么需要它们。

## 目录

1. [架构概览](#架构概览)
2. [核心数据结构](#核心数据结构)
3. [PermissionChecker 类](#permissionchecker-类)
4. [require_permission 依赖注入](#require_permission-依赖注入)
5. [在 Endpoints 中的使用示例](#在-endpoints-中的使用示例)

---

## 架构概览

权限系统采用基于角色（RBAC）的设计，分为两个层级：

- **系统级角色（System Roles）**：全局权限，如 `super_admin`、`admin`、`creator`、`user`
- **资源级角色（Resource Roles）**：在特定资源（如数据集）上的权限，如 `dataset_owner`、`dataset_manager`、`dataset_annotator`

权限字符串格式：`资源:操作:范围`，例如：
- `dataset:read:all` - 全局读取数据集
- `dataset:read:owned` - 读取自己拥有的数据集
- `dataset:read:assigned` - 读取被分配的数据集
- `annotation:modify:self` - 只能修改自己的标注

范围层级（从高到低）：`all` > `owned` > `assigned` > `self`

---

## 核心数据结构

### PermissionContext（权限上下文）

```python
@dataclass
class PermissionContext:
    user_id: str                                    # 要检查权限的用户ID
    resource_type: Optional[Union[ResourceType, str]] = None  # 资源类型（如 "dataset"）
    resource_id: Optional[str] = None               # 资源ID（如数据集ID）
    resource_owner_id: Optional[str] = None         # 资源拥有者ID（用于 owned 范围判断）
```

**为什么需要这个数据结构？**

1. **统一权限检查接口**：将所有权限检查所需的信息封装在一个对象中，避免函数参数过多
2. **支持多种场景**：
   - 系统级权限检查（不需要 resource_type/resource_id）
   - 资源级权限检查（需要 resource_type 和 resource_id）
   - 拥有者范围检查（需要 resource_owner_id）
3. **便于扩展**：未来如果需要添加新的上下文信息（如时间限制、地理位置等），只需修改这个类

---

## PermissionChecker 类

这是权限系统的核心类，负责所有权限检查逻辑。

### 1. `__init__(session: Session)`

**作用**：初始化权限检查器，建立数据库会话和缓存

**参数**：
- `session`: SQLAlchemy 数据库会话，用于查询角色和权限

**为什么需要缓存？**
- 在一个请求中，可能多次检查同一用户的权限
- 角色权限关系相对稳定，适合缓存
- 减少数据库查询，提升性能

```python
def __init__(self, session: Session):
    self.session = session
    self._role_cache: dict[str, Role] = {}              # 角色缓存
    self._permission_cache: dict[str, Set[str]] = {}    # 权限缓存
```

---

### 2. `get_role_permissions(role_id: str) -> Set[str]`

**作用**：获取角色的所有权限，包括从父角色继承的权限

**参数**：
- `role_id`: 角色ID

**返回值**：
- `Set[str]`: 权限字符串集合，如 `{"dataset:read:all", "sample:create:assigned"}`

**逻辑流程**：
1. 检查缓存，如果已缓存直接返回
2. 查询角色的直接权限（`RolePermission` 表）
3. 如果角色有父角色（`parent_id`），递归获取父角色权限
4. 合并直接权限和继承权限，存入缓存并返回

**为什么需要权限继承？**
- **减少重复配置**：子角色可以继承父角色的权限，只需定义差异部分
- **便于角色管理**：修改父角色权限时，所有子角色自动更新
- **支持角色层级**：例如 `dataset_manager` 可以继承 `dataset_viewer` 的所有权限，再加管理权限

**示例**：
```python
# 假设角色层级：dataset_manager 继承 dataset_viewer
# dataset_viewer 权限：{"dataset:read:assigned", "sample:read:assigned"}
# dataset_manager 额外权限：{"dataset:update:assigned"}

permissions = checker.get_role_permissions("dataset_manager")
# 返回：{"dataset:read:assigned", "sample:read:assigned", "dataset:update:assigned"}
```

---

### 3. `get_user_system_permissions(user_id: str) -> Set[str]`

**作用**：获取用户的所有系统级权限（合并用户所有系统角色）

**参数**：
- `user_id`: 用户ID

**返回值**：
- `Set[str]`: 所有系统级权限的并集

**逻辑流程**：
1. 查询用户的系统角色（`UserSystemRole` 表），过滤掉过期的
2. 对每个角色，调用 `get_role_permissions` 获取权限
3. 合并所有权限并返回

**为什么需要合并多个角色？**
- 一个用户可以有多个系统角色（如既是 `admin` 又是 `creator`）
- 所有角色的权限都需要生效（取并集）
- 支持细粒度权限组合

**示例**：
```python
# 用户同时拥有 admin 和 creator 角色
# admin 权限：{"dataset:read:all", "user:read:all"}
# creator 权限：{"dataset:create:all", "dataset:read:owned"}

perms = checker.get_user_system_permissions(user_id)
# 返回：{"dataset:read:all", "user:read:all", "dataset:create:all", "dataset:read:owned"}
```

---

### 4. `get_user_resource_permissions(user_id, resource_type, resource_id) -> Set[str]`

**作用**：获取用户在特定资源上的权限

**参数**：
- `user_id`: 用户ID
- `resource_type`: 资源类型（如 `ResourceType.DATASET`）
- `resource_id`: 资源ID（如数据集ID）

**返回值**：
- `Set[str]`: 该资源上的权限集合

**逻辑流程**：
1. 查询 `ResourceMember` 表，找到用户在该资源上的成员关系
2. 获取成员的角色ID
3. 通过 `get_role_permissions` 获取该角色的权限

**为什么需要资源级权限？**
- **细粒度控制**：不同用户在同一个数据集上可能有不同的权限
- **灵活授权**：管理员可以为不同数据集分配不同的角色
- **支持协作**：同一用户可以同时是多个数据集的成员，每个数据集权限不同

**示例**：
```python
# 用户在数据集 A 上是 dataset_owner（完全控制）
# 在数据集 B 上是 dataset_viewer（只读）

perms_a = checker.get_user_resource_permissions(user_id, "dataset", "dataset_a")
# 返回：{"dataset:read:assigned", "dataset:update:assigned", "sample:create:assigned", ...}

perms_b = checker.get_user_resource_permissions(user_id, "dataset", "dataset_b")
# 返回：{"dataset:read:assigned", "sample:read:assigned"}
```

---

### 5. `check(user_id, permission, resource_type, resource_id, resource_owner_id) -> bool`

**作用**：检查用户是否有指定权限（最核心的权限检查函数）

**参数**：
- `user_id`: 用户ID
- `permission`: 需要的权限字符串（如 `"dataset:read"` 或 `"annotation:modify:self"`）
- `resource_type`: 资源类型（可选，资源级权限需要）
- `resource_id`: 资源ID（可选，资源级权限需要）
- `resource_owner_id`: 资源拥有者ID（可选，用于 `owned` 范围判断）

**返回值**：
- `bool`: True 表示有权限，False 表示无权限

**逻辑流程**：

```
1. 构建 PermissionContext
   ↓
2. 调用 _get_effective_permissions 获取用户的所有有效权限
   - 合并系统权限和资源权限
   ↓
3. 检查是否有超级管理员权限 (*:*:all)
   - 如果有，直接返回 True
   ↓
4. 解析需要的权限字符串
   - 格式：resource:action:scope（默认 scope = "assigned"）
   ↓
5. 遍历用户的所有权限，查找匹配项
   对每个权限：
     a. 检查资源是否匹配（resource）
     b. 检查操作是否匹配（action 或 "*"）
     c. 检查范围是否覆盖（调用 _scope_covers）
       - 如果匹配，返回 True
   ↓
6. 没有找到匹配权限，返回 False
```

**为什么需要这个函数？**
- **统一入口**：所有权限检查都通过这个函数，保证逻辑一致
- **支持多层级权限**：自动合并系统权限和资源权限
- **支持范围判断**：通过 `_scope_covers` 实现范围层级（all > owned > assigned > self）

**示例**：
```python
# 场景1：系统级权限检查
has_permission = checker.check(
    user_id="user1",
    permission="dataset:create"
)
# 检查用户是否有创建数据集的系统级权限

# 场景2：资源级权限检查
has_permission = checker.check(
    user_id="user1",
    permission="dataset:read",
    resource_type="dataset",
    resource_id="dataset123"
)
# 检查用户在数据集 dataset123 上是否有读取权限

# 场景3：拥有者范围检查
has_permission = checker.check(
    user_id="user1",
    permission="dataset:update:owned",
    resource_type="dataset",
    resource_id="dataset123",
    resource_owner_id="user1"  # 假设 user1 是该数据集的拥有者
)
# 检查用户是否可以更新自己拥有的数据集
```

---

### 6. `_scope_covers(perm_scope, req_scope, ctx) -> bool`

**作用**：判断权限范围是否覆盖所需范围

**参数**：
- `perm_scope`: 用户拥有的权限范围（`"all"`, `"owned"`, `"assigned"`, `"self"`）
- `req_scope`: 需要的权限范围
- `ctx`: `PermissionContext` 对象

**返回值**：
- `bool`: 是否覆盖

**范围层级关系**：

```
all（最高）
  ↓ 覆盖
owned
  ↓ 覆盖（如果用户是拥有者）
assigned
  ↓ 覆盖
self（最低）
```

**逻辑规则**：

| 拥有的范围 | 可以覆盖的范围 | 额外条件 |
|-----------|--------------|---------|
| `all` | 所有范围 | 无 |
| `owned` | `owned`, `assigned`, `self` | 用户必须是资源拥有者（`ctx.user_id == ctx.resource_owner_id`） |
| `assigned` | `assigned`, `self` | 无 |
| `self` | `self` | 无 |

**为什么需要范围层级？**
- **灵活的权限模型**：
  - `all`: 管理员可以访问所有资源
  - `owned`: 创建者可以管理自己创建的资源
  - `assigned`: 成员可以访问被分配的资源
  - `self`: 标注员只能访问自己创建的标注
- **避免重复定义**：高范围权限自动覆盖低范围权限
- **支持复杂场景**：同一操作在不同范围有不同的含义

**示例**：
```python
# 用户拥有 dataset:read:all 权限
# 需要 dataset:read:assigned 权限
# 结果：True（all 覆盖 assigned）

# 用户拥有 annotation:modify:assigned 权限
# 需要 annotation:modify:self 权限
# 结果：True（assigned 覆盖 self）

# 用户拥有 dataset:update:owned 权限
# 需要 dataset:update:owned 权限
# 资源拥有者是 user1，当前用户也是 user1
# 结果：True（owned 覆盖 owned，且满足拥有者条件）

# 用户拥有 dataset:update:owned 权限
# 需要 dataset:update:owned 权限
# 资源拥有者是 user2，当前用户是 user1
# 结果：False（虽然是 owned，但用户不是拥有者）
```

---

### 7. `filter_accessible_resources(user_id, resource_type, required_permission, base_query, get_owner_id_column, resource_model)`

**作用**：过滤查询，只返回用户有权访问的资源（用于列表接口）

**参数**：
- `user_id`: 用户ID
- `resource_type`: 资源类型
- `required_permission`: 需要的权限（如 `"dataset:read"`）
- `base_query`: 原始 SQLAlchemy 查询对象
- `get_owner_id_column`: 函数，返回资源表的 `owner_id` 列（用于 owned 范围判断）
- `resource_model`: 资源模型类（如 `Dataset`），用于查询和过滤

**返回值**：
- 修改后的查询对象，添加了权限过滤条件

**逻辑流程**：

```
1. 检查是否是超级管理员或拥有 all 范围权限
   - 如果是，直接返回原始查询（不过滤）
   ↓
2. 收集可访问的资源ID
   a. 如果有 owned 范围权限：
      - 使用 get_owner_id_column() 获取 owner_id 列
      - 查询 owner_id = user_id 的资源（使用 resource_model）
   b. 查询 ResourceMember 表：
      - 找到用户在哪些资源上是成员
   ↓
3. 如果没有任何可访问资源：
   - 返回查询条件为 False 的查询（空结果）
   ↓
4. 如果有关键资源：
   - 使用 resource_model.id 修改查询，添加 id IN (accessible_ids) 条件
```

**为什么需要这个函数？**
- **性能优化**：在数据库层面过滤，而不是在应用层过滤
- **自动权限控制**：列表接口自动应用权限，减少代码重复
- **支持多范围权限**：自动处理 `all`、`owned`、`assigned` 范围

**示例**：
```python
# 在 datasets.py 的 list_datasets 中使用
query = select(Dataset)

filtered_query = checker.filter_accessible_resources(
    user_id=current_user.id,
    resource_type=ResourceType.DATASET,
    required_permission="dataset:read",
    base_query=query,
    get_owner_id_column=lambda: Dataset.owner_id,
    resource_model=Dataset,
)

# 如果是 admin（有 dataset:read:all）：
#   → 返回原始查询，显示所有数据集

# 如果是普通用户（有 dataset:read:assigned）：
#   → 返回 Dataset.id IN (用户是成员的数据集ID列表)

# 如果是 creator（有 dataset:read:owned）：
#   → 返回 Dataset.id IN (用户拥有的数据集ID + 用户是成员的数据集ID)
```

---

## require_permission 依赖注入

这是 FastAPI 依赖注入函数，用于在路由中自动进行权限检查。

### `require_permission(permission, resource_type, resource_id_param, get_resource_owner, get_parent_resource_id)`

**作用**：创建权限检查依赖，在请求处理前自动检查权限

**参数详解**：

1. **`permission: str`**（必需）
   - 需要的权限字符串，如 `"dataset:read"`、`"annotation:modify:self"`
   - **为什么需要？**：明确声明该接口需要的权限级别

2. **`resource_type: Optional[str]`**（可选）
   - 资源类型，如 `"dataset"`
   - **为什么需要？**：资源级权限需要知道是哪种资源类型

3. **`resource_id_param: Optional[str]`**（可选）
   - URL 路径参数名，用于获取资源ID
   - 例如：如果路由是 `GET /datasets/{dataset_id}`，则传入 `"dataset_id"`
   - **为什么需要？**：自动从 URL 中提取资源ID，无需手动传递

4. **`get_resource_owner: Optional[Callable[[Session, str], Optional[str]]]`**（可选）
   - 函数：接收 session 和资源ID，返回拥有者ID
   - 例如：`get_dataset_owner(session, dataset_id) -> owner_id`
   - **为什么需要？**：用于 `owned` 范围判断，需要知道资源拥有者

5. **`get_parent_resource_id: Optional[Callable[[Session, str], Optional[str]]]`**（可选）
   - 函数：接收 session 和子资源ID，返回父资源ID
   - 例如：`get_label_dataset_id(session, label_id) -> dataset_id`
   - **为什么需要？**：子资源（如 label、annotation）的权限继承自父资源（dataset）

**工作流程**：

```
1. FastAPI 调用依赖时自动执行
   ↓
2. 从 URL 路径参数中提取资源ID（如果提供了 resource_id_param）
   ↓
3. 如果是子资源（提供了 get_parent_resource_id）：
   - 调用 get_parent_resource_id 获取父资源ID
   ↓
4. 如果需要检查 owned 范围（提供了 get_resource_owner）：
   - 调用 get_resource_owner 获取资源拥有者ID
   ↓
5. 调用 PermissionChecker.check 检查权限
   ↓
6. 如果通过：
   - 返回 current_user（注入到路由处理函数）
   如果失败：
   - 抛出 403 Forbidden 异常
```

**为什么需要依赖注入？**
- **声明式权限控制**：在路由定义时声明权限，代码清晰
- **自动检查**：无需在每个路由函数中手动写权限检查代码
- **统一错误处理**：权限被拒绝时自动返回标准错误响应
- **类型安全**：返回 `User` 对象，IDE 可以自动补全

---

## 在 Endpoints 中的使用示例

### 示例1：系统级权限（创建数据集）

```python
@router.post("/", response_model=DatasetRead)
def create_dataset(
        dataset: DatasetCreate,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(Permissions.DATASET_CREATE)),
        # ↑ 只需要权限字符串，系统级权限
):
    """创建新数据集"""
    # current_user 自动注入，且已通过权限检查
    db_dataset = Dataset(**dataset.model_dump(), owner_id=current_user.id)
    # ...
```

**解析**：
- `Permissions.DATASET_CREATE = "dataset:create:all"`
- 系统级权限，不需要 `resource_type` 和 `resource_id`
- 只有拥有 `dataset:create:all` 权限的用户才能创建数据集

---

### 示例2：资源级权限（读取数据集）

```python
@router.get("/{dataset_id}", response_model=DatasetRead)
def get_dataset(
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permissions.DATASET_READ,           # 权限：dataset:read:assigned
            ResourceType.DATASET,               # 资源类型：dataset
            "dataset_id",                       # URL 参数名：从路径中提取 dataset_id
            get_dataset_owner                   # 获取拥有者ID的函数
        ))
):
    """获取数据集详情"""
    dataset = session.get(Dataset, dataset_id)
    # ...
```

**解析**：
- `Permissions.DATASET_READ = "dataset:read:assigned"`
- 资源级权限，需要 `resource_type` 和 `resource_id`
- `"dataset_id"` 告诉依赖从 URL 路径中提取 `dataset_id`
- `get_dataset_owner` 用于检查 `owned` 范围（虽然这里用的是 `assigned`，但框架仍会获取拥有者信息）

**权限检查流程**：
1. 提取 `dataset_id` 从 URL：`dataset_id = "dataset123"`
2. 调用 `get_dataset_owner(session, "dataset123")` 获取拥有者ID
3. 检查用户在数据集 `dataset123` 上的权限：
   - 系统权限：是否有 `dataset:read:all` 或 `dataset:read:owned`？
   - 资源权限：用户在数据集 `dataset123` 上的角色是否有 `dataset:read:assigned`？
4. 如果通过，注入 `current_user`；否则抛出 403

---

### 示例3：子资源权限（读取标签）

```python
@router.get("/labels/{label_id}", response_model=LabelRead)
def get_label(
        label_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permissions.LABEL_READ,                    # 权限：label:read:assigned
            ResourceType.DATASET,                      # 父资源类型：dataset（标签属于数据集）
            "label_id",                                # URL 参数名：label_id
            get_label_dataset_owner,                   # 获取数据集拥有者ID
            get_label_dataset_id                       # 获取标签所属的数据集ID
        ))
):
    """获取标签详情"""
    label = session.get(Label, label_id)
    # ...
```

**解析**：
- 标签（Label）是数据集的子资源
- 标签的权限继承自数据集，所以 `resource_type` 是 `DATASET` 而不是 `LABEL`
- `get_label_dataset_id`：通过 `label_id` 获取父资源（数据集）ID
- `get_label_dataset_owner`：通过 `label_id` → 数据集ID → 拥有者ID

**权限检查流程**：
1. 提取 `label_id` 从 URL：`label_id = "label456"`
2. 调用 `get_label_dataset_id(session, "label456")` → `dataset_id = "dataset123"`
3. 调用 `get_label_dataset_owner(session, "label456")` → `owner_id = "user1"`
4. 检查用户在数据集 `dataset123` 上的权限（不是标签的权限！）
5. 如果通过，说明用户可以读取该数据集，因此也可以读取数据集下的标签

---

### 示例4：列表接口（自动过滤）

```python
@router.get("/", response_model=List[DatasetRead])
def list_datasets(
        skip: int = 0,
        limit: int = 100,
        session: Session = Depends(get_session),
        current_user: User = Depends(get_current_user),  # 只需认证，不需要特定权限
        checker: PermissionChecker = Depends(get_permission_checker),
):
    """列出数据集"""
    query = select(Dataset)
    
    # 自动过滤：只返回用户有权访问的数据集
    filtered_query = checker.filter_accessible_resources(
        user_id=current_user.id,
        resource_type=ResourceType.DATASET,
        required_permission="dataset:read",
        base_query=query,
        get_owner_id_column=lambda: Dataset.owner_id,
    )
    
    datasets = session.exec(filtered_query.offset(skip).limit(limit)).all()
    # ...
```

**解析**：
- 列表接口通常只需要用户登录，不需要特定权限检查（由 `filter_accessible_resources` 处理）
- `filter_accessible_resources` 自动在数据库层面过滤：
  - Admin：显示所有数据集
  - Creator：显示拥有的 + 成员的数据集
  - User：只显示成员的数据集

---

### 示例5：标注读取（self 范围的业务逻辑检查）

这是权限检查与业务逻辑分离的最佳实践示例。

```python
@router.get("/{sample_id}", response_model=SampleAnnotationsResponse)
def get_sample_annotations(
        sample_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user),  # 只需登录，不需要特定权限
):
    """获取样本的所有标注"""
    # 1. 获取用户的访问范围（权限检查）
    read_scope = _get_annotation_access_scope(
        session, current_user, dataset_id, dataset.owner_id, "read"
    )
    if read_scope == "none":
        raise HTTPException(403, "Permission denied")
    
    # 2. 查询所有标注
    annotations = session.exec(
        select(Annotation).where(Annotation.sample_id == sample_id)
    ).all()
    
    # 3. 根据范围过滤标注（业务逻辑检查）
    items = []
    for ann in annotations:
        if _can_access_annotation(ann, current_user, read_scope):
            items.append(_to_item(ann, label))
    
    return SampleAnnotationsResponse(annotations=items, read_scope=read_scope)
```

**辅助函数：获取访问范围**

```python
def _get_annotation_access_scope(session, user, dataset_id, dataset_owner_id, action):
    """获取用户的标注访问范围"""
    checker = PermissionChecker(session)
    
    if action == "read":
        # 从高到低检查范围
        if checker.check(user.id, "annotation:read:all", "dataset", dataset_id, dataset_owner_id):
            return "all"
        if checker.check(user.id, "annotation:read:assigned", "dataset", dataset_id, dataset_owner_id):
            return "assigned"
        if checker.check(user.id, "annotation:read:self", "dataset", dataset_id, dataset_owner_id):
            return "self"
    # ... modify 同理
    
    return "none"
```

**辅助函数：业务逻辑检查**

```python
def _can_access_annotation(annotation, user, scope):
    """检查用户是否可以访问特定标注（基于范围）"""
    if scope in ("all", "assigned"):
        return True  # 可以访问所有标注
    if scope == "self":
        # 只能访问自己创建的标注，或自动生成的标注（annotator_id 为 None）
        return annotation.annotator_id is None or annotation.annotator_id == user.id
    return False
```

**解析**：
1. **权限检查阶段**（`_get_annotation_access_scope`）：
   - 检查用户在数据集上的权限范围（`all`、`assigned` 或 `self`）
   - 这是权限层面的检查：用户是否有某种范围的权限？

2. **业务逻辑检查阶段**（`_can_access_annotation`）：
   - 基于已确定的权限范围，检查特定标注是否可以被访问
   - 这是业务层面的检查：用户是否可以访问这个具体的标注？

**为什么需要分离？**
- **权限检查**（`check` 函数）只能判断用户是否有某个范围的权限
- **业务逻辑检查**需要判断具体对象是否满足范围条件（如 `self` 范围需要检查 `annotator_id`）
- 分离后，权限系统保持通用性，业务逻辑可以根据不同资源类型灵活实现

**实际流程**：
```
用户请求获取标注
  ↓
1. 权限检查：用户在数据集上的权限范围是什么？
   - dataset_owner → "all"（可以看到所有标注）
   - dataset_annotator → "self"（只能看到自己的标注）
  ↓
2. 业务逻辑检查：基于范围，过滤标注列表
   - "all" → 返回所有标注
   - "self" → 只返回 annotator_id == user.id 的标注
```

---

## 总结

### 核心设计理念

1. **分层权限模型**：
   - 系统级权限（全局）
   - 资源级权限（特定资源）
   - 范围层级（all > owned > assigned > self）

2. **声明式权限控制**：
   - 在路由定义时声明需要的权限
   - 依赖注入自动检查，减少重复代码

3. **性能优化**：
   - 权限缓存（避免重复查询）
   - 数据库层面过滤（列表接口）

4. **灵活的权限组合**：
   - 用户可以有多个系统角色
   - 同一用户在不同资源上可以有不同的资源角色
   - 权限继承（子角色继承父角色）

### 关键函数的作用

| 函数 | 作用 | 使用场景 |
|-----|------|---------|
| `get_role_permissions` | 获取角色权限（含继承） | 内部使用，构建权限集合 |
| `get_user_system_permissions` | 获取用户系统权限 | 内部使用 |
| `get_user_resource_permissions` | 获取用户资源权限 | 内部使用 |
| `check` | 检查单个权限 | 内部使用，由依赖注入调用 |
| `filter_accessible_resources` | 过滤资源列表 | 列表接口 |
| `require_permission` | 创建权限检查依赖 | 路由定义 |

### 为什么需要这个抽象层级？

1. **代码复用**：权限检查逻辑集中在 `PermissionChecker`，避免在每个 endpoint 重复
2. **一致性**：所有权限检查使用相同的逻辑，保证行为一致
3. **可测试性**：权限逻辑独立于 HTTP 层，易于单元测试
4. **可维护性**：修改权限逻辑只需修改 `PermissionChecker`，无需改动每个 endpoint
5. **扩展性**：新增权限类型或范围只需修改核心类，不影响现有代码

---

## 常见问题

### Q1: 为什么权限检查在依赖注入中进行，而不是在业务逻辑中？

**A**: 
- 依赖注入在请求处理前执行，可以提前拒绝无权限请求，避免不必要的数据库查询
- 将权限逻辑与业务逻辑分离，代码更清晰
- 统一错误处理（自动返回 403）

### Q2: 为什么子资源（label、annotation）的权限检查要用父资源（dataset）的权限？

**A**:
- 简化权限模型：子资源权限继承自父资源
- 避免重复配置：不需要为每个标签/标注单独配置权限
- 符合业务逻辑：如果能访问数据集，就能访问数据集下的所有内容（具体操作由范围控制）

### Q3: `owned` 范围和资源角色 `dataset_owner` 有什么区别？

**A**:
- `owned` 范围：系统级角色的权限，通过 `resource_owner_id` 判断用户是否是资源拥有者
- `dataset_owner` 角色：资源级角色，明确分配给用户的数据集角色
- 两者功能相似，但来源不同：
  - `owned`：来自系统角色（如 `creator`）+ 资源拥有关系
  - `dataset_owner`：来自资源成员表（`ResourceMember`）

### Q4: 什么时候使用 `filter_accessible_resources`，什么时候使用 `require_permission`？

**A**:
- `require_permission`：单个资源操作（GET/PUT/DELETE），检查是否有权限访问特定资源
- `filter_accessible_resources`：列表操作（GET /list），自动过滤返回结果

两者可以结合使用：列表接口先用 `filter_accessible_resources` 过滤，然后对结果进行权限检查。
