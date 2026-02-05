# Project Overview 改造计划 v3（含路由修复 & Workspace 规划）

## Summary
- 新增 `ProjectLayout` 页面：顶部 RepoTabs，底部按 tab 路由展示页面
- Overview 使用 GitHub repo 结构（RepoHeader / RepoActionBar / FileTable / Sidebar）
- FileTable 展示关联数据集，点击切换样本卡片视图
- Sidebar 保留 GitHub 样式，内容替换为项目统计/AL Loops/Models/样本状态
- 顺手修复后端 L2 路由前缀重复问题
- 预留 AnnotationWorkspace 的项目级路由结构

---

## 1. 路由调整（前端）

### 新增 Project Layout
- `/projects/:id/*` → `ProjectLayout`（包含 RepoTabs）

### Tabs 路由
- `/projects/:id` → Overview
- `/projects/:id/samples` → Samples & Annotations
- `/projects/:id/loops` → AL Loops
- `/projects/:id/insights` → Insights
- `/projects/:id/members` → Members
- `/projects/:id/settings` → Settings

### 未来 AnnotationWorkspace 路由（规划）
- 入口：`/projects/:id/workspace`
- 具体：`/projects/:id/workspace/:datasetId`
- 支持 query：`?sampleId=...` / `?start=unlabeled`
- 入口行为：
  - 若项目只有一个 dataset → 自动进入该 dataset workspace
  - 若多个 dataset → 先选择 dataset

---

## 2. RepoTabs 移到 Project 层级
- RepoTabs 上移至 `ProjectLayout`
- Tabs 居中、带图标
- Tabs 内容：overview / samples & annotations / AL Loops / insights / members / settings
- Overview 页面下才显示 RepoHeader/ActionBar/Sidebar

---

## 3. Overview 页面改造

### RepoHeader
- 标题：项目名称
- Visibility → TaskType
- 头像保留并加 TODO
- 右侧按钮只保留 Fork

### RepoActionBar
- 分支下拉/分支数/tag 数量/搜索框保留
- 右侧不加入 dataset 操作

### FileTable Header
- 保持 GitHub 样式
- 展示 “最新 commit 的作者头像 + 全名 + commit 信息”

### FileTable 内容
- 数据集列表
- 点击 → 切换样本卡片视图
- 若只有一个 dataset → 默认进入样本卡片视图

---

## 4. Sidebar 内容替换（保留 GitHub 样式）
- About：项目描述 + 统计（datasets/labels/branches/commits/members）
- Releases → AL Loops（占位）
- Packages → Models（占位）
- Languages → Sample Status（labeled / unlabeled / skipped）

---

## 5. 可复用样本卡片视图组件
- 新增 `ProjectDatasetSamples.tsx`
- props：`datasetId`
- 使用 `PaginatedList` + `SampleAssetModal`
- 支持分页加载

---

## 6. 后端路由修复（重要）
当前 `api_v1/api.py` 中：
```
api_router.include_router(label.router, prefix="/api/v1/labels")
```
导致实际路径变成 `/api/v1/api/v1/...`

### 修复为：
```
prefix="/labels", "/commits", "/branches", "/annotations"
```

同时更新前端 API 路径调用。

---

## 7. Dataset 类型一致性策略（推荐）
默认：**同一个 project 只允许一种 dataset.type**

实现位置：
- 后端 `project.link_datasets` 时校验
- 若已有 dataset 且类型不一致，返回 400

---

## Tests & Validation
1. `/projects/:id` tabs 渲染正确
2. Overview 显示 GitHub repo 结构
3. Dataset 列表 → 可切换为样本卡片视图
4. 只有一个 dataset → 自动进入卡片视图
5. Sidebar 结构正确
6. 后端 L2 路由访问不再重复 `/api/v1`

---

## Assumptions
- Workspace 以 dataset 为入口，sampleId 使用 query
- dataset.type 混用默认禁止
- AL Loops / Models 暂占位
