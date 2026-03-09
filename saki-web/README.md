# saki-web

`saki-web` 是 Saki 的前端工作台，负责数据、标注、项目、Runtime 与系统配置的交互入口。

## 1. 模块定位

前端职责：

1. 承载业务页面与运行时可视化。
2. 通过 `ApiService` 调用后端接口。
3. 基于 `taskId` 组织运行时日志与状态展示。

## 2. 技术栈

- React 18
- Vite
- TypeScript
- Ant Design 5
- Zustand
- Axios
- i18next
- Konva / React-Konva

## 3. 目录概览

```text
saki-web/src/
├── pages/
├── components/
├── services/api/
├── store/
├── hooks/
├── types/
└── i18n/
```

## 4. 安装与运行

```bash
cd saki-web
npm install
npm run dev
```

构建：

```bash
npm run build
```

预览：

```bash
npm run preview
```

## 5. API 基地址与代理

1. API 基地址由 `VITE_API_BASE_URL` 决定。
2. 默认回退值：`http://localhost:8000/api/v1`。
3. `ApiService` 暴露 `getApiBaseUrl()` 供调试与页面显示。
4. Vite dev server 代理：
- `/api` -> `http://localhost:8000`
- `/static` -> `http://localhost:8000`

## 6. 页面域划分

- `dataset/*`：数据集管理
- `annotation/*`：标注工作台
- `project/*`：项目与版本管理
- `runtime/*`：执行器与运行时页面
- `system/*`：系统配置
- `user/*`：用户与权限

## 7. 开发建议

1. 服务接口统一走 `services/api`，避免页面直接拼 URL。
2. 共享状态统一放 `store`，避免深层透传。
3. 新增 API 字段时，同步更新 `types/` 与转换逻辑。

## 8. 常见问题

1. 开发环境请求 404
- 检查 API 是否运行。
- 检查 `VITE_API_BASE_URL` 是否对齐。

2. 登录后接口 401
- 检查 token 注入与刷新逻辑。

3. 构建体积告警
- 优先按路由拆分页面。
- 结合 `vite.config.ts` 的 `manualChunks` 调整打包策略。
