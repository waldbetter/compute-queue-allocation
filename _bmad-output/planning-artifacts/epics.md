# Epics — GPU Queue Allocation System MVP

---

## Epic 1：项目脚手架与基础后端

**目标**：搭建可运行的前后端骨架，MySQL 连通，数据库表创建，FastAPI 基础路由和 CORS，Vue 基础项目结构。为后续所有 Epic 提供基础设施。

| ID | Story | 验收标准 |
|----|-------|---------|
| 1-1 | 后端项目初始化与数据库连接 | Python 3.11 + FastAPI + SQLAlchemy async + aiomysql；启动时连接 MySQL；DDL 可一键创建 4 张表；pytest-asyncio 可跑通一个假 DB session 获取测试 |
| 1-2 | ORM 模型与 Repository 接口 | 四个 ORM 模型字段与 database-schema.md DDL 完全一致；domain 层定义抽象接口，infrastructure 层实现；依赖方向符合 AD-6 |
| 1-3 | FastAPI 入口与 Lifespan | lifespan startup 初始化 DB pool + spawn dispatcher Task + init ProcessManager；shutdown cancel dispatcher + 释放资源；`uvicorn app.main:app` 启动无报错 |
| 1-4 | 全局异常处理与 CORS | AppError 基类 + FastAPI exception_handler；CORS 允许 localhost:5173；未知异常记 ERROR 日志并返回 500 |
| 1-5 | 前端 Vue 项目初始化 | Vue 3 + Vite + Pinia + Vue Router + Element Plus；`npm run dev` 启动；路由 /login /tasks /gpus /tasks/submit；axios + ws client 骨架 |
| 1-6 | AGENTS.md 与项目 README | 项目根目录 AGENTS.md 含已知命令、约定、避免事项；docs/README.md 快速启动指南 |

---

## Epic 2：用户与 GPU 资源管理

**目标**：实现 MVP 简化的用户标识、GPU 资源 CRUD 和状态管理。

| ID | Story | 验收标准 |
|----|-------|---------|
| 2-1 | 用户创建与当前用户识别 | POST /users 创建测试用户；GET /users/me 返回当前用户；MVP session cookie 简化标识，跳过密码 |
| 2-2 | 权限中间件 | FastAPI Depends 区分 member / admin；非 admin 访问 admin 路由返回 403 |
| 2-3 | GPU 登记与 CRUD | POST/GET/PATCH /gpus 全部实现；admin 写操作校验 role；创建后默认 IDLE；name 有 UNIQUE 约束 |
| 2-4 | GPU 状态转换校验 | RUNNING GPU 标记 MAINTENANCE → 400 "需先终止运行中的任务"；IDLE→MAINTENANCE、MAINTENANCE→IDLE、FAULTY→IDLE 合法 |
| 2-5 | GPU 管理面板 Vue 页面 | /gpus Element Plus 表格；name/model/status/current_task_id 列；status Tag 着色；admin 行有维护操作按钮；点击后调用 PATCH API 刷新 |
| 2-6 | 测试数据初始化脚本 | backend/seed.py 一键创建 1 admin + 2 member + 3 GPU (2×RTX 3090, 1×A100)，方便手动演示 |

---

## Epic 3：任务排队与自动分配（核心 Epic）

**目标**：实现任务提交、FCFS 队列、调度器、subprocess 执行，完成 MVP 核心价值闭环。

| ID | Story | 验收标准 |
|----|-------|---------|
| 3-1 | 任务提交 API 与校验 | POST /tasks；gpu_count == 1 校验（否则 422）；QUEUED 状态；queue_position 即时查询；有空闲 GPU 时直接 PENDING |
| 3-2 | 任务列表与详情 | GET /tasks（当前用户）/tasks/admin（全部）；GET /tasks/{id} 含 queue_position（由查询即时计算，不读冗余字段） |
| 3-3 | FCFS 调度器 asyncio Task | dispatcher.py run_dispatcher() 实现 AD-1 的完整事务 SQL；FOR UPDATE 必须真正执行；subprocess 启动；主循环 ≤ 500ms；lifespan 注册 |
| 3-4 | 并发分配安全单元测试 | 真实 MySQL（Testcontainers）；1 张 IDLE GPU + N=50 并发调度请求；验证仅 1 条 ALLOCATE 日志 + GPU status=ALLOCATED + 其余 N-1 收到 1205 后后端返回 409；N=100 同样覆盖 |
| 3-5 | subprocess 执行与监控 | ProcessManager 用 asyncio.create_subprocess_exec；注入 CUDA_VISIBLE_DEVICES=分配到的 GPU id；stdout/stderr 写 logs/{task_id}.log；exit 0→COMPLETED，exit≠0→FAILED；释放 GPU 回 IDLE + 写 allocation_log(RELEASE) |
| 3-6 | 任务取消与终止 | POST /tasks/{id}/cancel：仅 owner 且 QUEUED/PENDING；GPU 已分配则释放；POST /tasks/{id}/terminate：admin-only；subprocess 发送 SIGTERM（Windows 用 taskkill）；进程结束后 TERMINATED |
| 3-7 | 任务提交 Vue 页面 | /tasks/submit Element Plus 表单；name(command/gpu_count=1 disabled/model_preference 下拉/estimated_duration 数字)；提交后跳转任务列表 |
| 3-8 | 任务列表 Vue 页面 + WS | /tasks Element Plus 表格；列含 status(tag)/queue_position/exit_code；"取消" 按钮按条件显示；连接 WS → 事件触发 Pinia action → 自动重渲染 |
| 3-9 | 多卡同型号分配（Post-MVP） | gpu_count 1-N（同型号组队）；dispatcher 按型号偏好或最早空闲卡型号一次性锁 N 张同型号 IDLE 卡（FOR UPDATE），凑不齐队首阻塞；CUDA_VISIBLE_DEVICES 注入逗号串；释放按 current_task_id 批量；tasks.allocated_gpu_ids 记录逗号串（不建关联表） |

---

## Epic 4：WebSocket 实时推送

**目标**：完成 CAP-3 所需的实时推送基础设施。Epic 3 最后一个 Story (3-8) 依赖 Epic 4 的基础设施。

| ID | Story | 验收标准 |
|----|-------|---------|
| 4-1 | ConnectionManager 基础设施 | utils/websocket_manager.py 单例；connect/disconnect/broadcast/send_task 方法；FastAPI /ws/events 端点；lifespan startup 初始化 |
| 4-2 | 状态变更自动推送 | Dispatcher + ProcessManager 的所有状态变更点 broadcast(event, data)；至少覆盖 8 个触发点（QUEUED/PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/TERMINATED/GPU status） |
| 4-3 | Snapshot 与重连恢复 | 连接后立即 snapshot（当前所有 tasks + gpus）；前端断线指数退避重连；重连后重新 snapshot 补全状态 |
| 4-4 | 前端 WS 封装与 Store 联动 | frontend/src/ws/client.js 封装 connect/on/disconnect；Pinia tasks store 监听 WS 事件自动更新；mock 测试通过 |

---

## Epic 5：整合测试与 MVP 收尾

| ID | Story | 验收标准 |
|----|-------|---------|
| 5-1 | 端到端冒烟测试 | pytest 脚本：创建 GPU → 提交 3 任务 → 验证排队顺序 → 等待第一个 RUNNING → 验证 COMPLETED + GPU 释放 → 第二个自动分配；全流程 PASS |
| 5-2 | 并发安全集成测试 | 1 张 GPU + 提交 50 任务 → 最终 1 RUNNING / 49 QUEUED → allocation_log 恰好 1 条 ALLOCATE |
| 5-3 | 手动演示 Checklist | docs/DEMO.md：10 分钟演示脚本 + seed 数据初始化 + 操作步骤 + 预期观察 |
| 5-4 | 部署文档 | docs/DEPLOYMENT.md：环境要求、端口、systemd 或 Windows 服务注册、日志轮转、常见错误排查 |

---

## 并行开发建议

```
批次 1（可同时开工）：
  后端 1-1 / 前端 1-5

批次 2（1-1 完成后）：
  1-2 → 1-3 → 1-4 / 并行 2-1, 2-2, 2-3

批次 3（2-3 完成后）：
  3-1, 3-2 / 并行 4-1

批次 4（3-3 spec_checkpoint 确认后）：
  3-3 → 3-4 → 3-5 → 3-6

批次 5（4-2 完成后）：
  3-8, 4-4

批次 6（全部 Epic 完成后）：
  5-1, 5-2, 5-3, 5-4
```