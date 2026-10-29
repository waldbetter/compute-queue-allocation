---
name: GPU Queue Allocation System — MVP
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: layered + async event loop
scope: 单机 GPU 排队与分配系统（用户提交 → 自动 FCFS 分配 → subprocess 执行 → 状态推送 → GPU 管理）
status: draft
created: 2026-10-26
updated: 2026-10-26
binds: [CAP-1, CAP-2, CAP-3, CAP-4, CAP-5, CAP-6]
sources: [../../specs/spec-gpu-queue-allocation/SPEC.md]
companions:
  - ../../specs/spec-gpu-queue-allocation/database-schema.md
  - ../../specs/spec-gpu-queue-allocation/state-machines.md
  - ../../specs/spec-gpu-queue-allocation/api-contracts.md
---

# Architecture Spine — GPU Queue Allocation System

## Design Paradigm

分层 + asyncio 事件循环：

```
┌───────────────────────────────────────────────────────────────┐
│  Presentation     Vue 3 + Vite 前端 + WebSocket 客户端         │
├───────────────────────────────────────────────────────────────┤
│  Application      FastAPI 路由层、WebSocket 端点、依赖注入      │
├───────────────────────────────────────────────────────────────┤
│  Domain           QueueService、Dispatcher、ProcessManager      │
├───────────────────────────────────────────────────────────────┤
│  Infrastructure   MySQL Repository、asyncio subprocess、日志   │
└───────────────────────────────────────────────────────────────┘
```

后端使用 Python `asyncio`；Dispatcher 和 ProcessManager 作为后台 asyncio Task 持续运行。

## Invariants & Rules

### AD-1 — GPU 分配必须在数据库悲观锁事务内完成

- **Binds:** CAP-2（自动分配）、CAP-6（并发安全）
- **Prevents:** 两个并发请求同时读到同一张 IDLE GPU 并各自 UPDATE → 重复分配
- **Rule:** 分配 GPU 时必须执行：
  ```
  BEGIN TRANSACTION;
  SELECT id FROM gpus WHERE status='IDLE' ORDER BY id ASC LIMIT 1 FOR UPDATE;
  SELECT id FROM tasks WHERE status IN ('QUEUED','PENDING') ORDER BY submitted_at, id LIMIT 1 FOR UPDATE;
  UPDATE gpus SET status='ALLOCATED', current_task_id=? WHERE id=?;
  UPDATE tasks SET status='PENDING', allocated_gpu_id=? WHERE id=?;
  INSERT INTO allocation_log (task_id, gpu_id, action, actor_user_id, notes) VALUES (?, ?, 'ALLOCATE', ?, 'dispatcher');
  COMMIT;
  ```
  事务隔离级别 `REPEATABLE READ`；任何在 `FOR UPDATE` 之后发生的异常必须 `ROLLBACK`。

### AD-2 — FCFS 队列只有一个真值来源

- **Binds:** CAP-2、Constraint "FCFS 排队"
- **Prevents:** 前端各自独立排序导致前后端不一致；调度器缓存陈旧队列
- **Rule:** 排队顺序**不**在应用层缓存，由数据库查询 `SELECT * FROM tasks WHERE status IN ('QUEUED','PENDING') ORDER BY submitted_at ASC, id ASC` 即时计算。调度器取队头、前端展示位置、queue_position 计算全部走这个查询。

### AD-3 — Dispatcher 是 asyncio 单例后台 Task

- **Binds:** CAP-2、Constraint "Python subprocess 执行引擎"
- **Prevents:** 多个调度器实例并发抢占同一张 GPU（即使 AD-1 已防护，多实例也会产生无谓的锁等待和 1205 错误）
- **Rule:** 后端 lifespan startup 时 `asyncio.create_task(run_dispatcher())` 启动**一个**实例；主循环 ≤ 500ms 一轮：查 IDLE GPU → 对每张 GPU 执行 AD-1 的事务分配 → 启动 subprocess → 监听完成 → 释放 GPU。lifespan shutdown 时 `await dispatcher_task.cancel()`。

### AD-4 — 领域层依赖抽象接口

- **Binds:** all
- **Prevents:** Domain 逻辑直接耦合 SQLAlchemy / PyMySQL → 单元测试必须连真实 DB
- **Rule:** `domain/repositories/interfaces.py` 定义 `TaskRepository` / `GpuRepository` / `AllocationLogRepository` 抽象接口；`infrastructure/mysql/repositories.py` 提供 MySQL 实现；FastAPI Depends 注入 MySQL 实例；单元测试注入 mock 实现。

### AD-5 — 状态变更统一通过 WebSocket 广播

- **Binds:** CAP-3
- **Prevents:** 前端轮询导致不同客户端刷新间隔不一致；后端事务已提交但前端看不到新状态
- **Rule:** 后端维护 `set[WebSocket]` 连接集合；Dispatcher / ProcessManager 每一处状态变更点在事务 COMMIT 之后调用 `websocket_manager.broadcast(event, payload)`；消息格式统一 `{event, timestamp_ms, payload}`。客户端断线自动重连（指数退避），重连后立即收到 snapshot。

### AD-6 — 依赖方向图（谁可以 import 谁）

```mermaid
graph LR
    subgraph "Presentation (frontend/)"
        V[Vue Components]
    end
    subgraph "Application (backend/app/api/)"
        R[FastAPI Routes]
    end
    subgraph "Domain (backend/app/domain/)"
        Q[QueueService]
        D[Dispatcher]
        PM[ProcessManager]
        I[Repository Interfaces]
    end
    subgraph "Infrastructure (backend/app/infrastructure/)"
        IR[MySQL Repositories]
        SP[asyncio subprocess]
        NS[nvidia-smi]
    end

    V --> R
    R --> Q
    R --> I
    D --> Q
    D --> I
    D --> PM
    D --> NS
    PM --> SP
    PM --> I
    IR -.implements.-> I

    style I fill:#fff3e0,stroke:#ff9800
    style IR fill:#e3f2fd,stroke:#2196f3
    style SP fill:#e8f5e9,stroke:#4caf50
```

- **Rule:** 依赖方向只能向右；箭头不可反向；Domain 层**禁止** import 任何 Infrastructure 实现。

### AD-7 — 错误响应三档分级

- **Binds:** all
- **Prevents:** 错误被吞没或泄露内部堆栈到生产用户
- **Rule:** L1 用户输入错误 → 4xx + 可读中文消息（不记 ERROR 日志）；L2 业务冲突 → 409 Conflict + 明确描述；L3 系统错误 → 500 + 通用消息，后端记录 ERROR 日志到 `logs/app.log`（含完整 traceback）。自定义异常继承 `AppError(http_status, message)`。

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| 数据库 ID | `BIGINT UNSIGNED AUTO_INCREMENT`；外键 `ON DELETE CASCADE`（allocation_log.task_id）或 `ON DELETE SET NULL`（tasks.allocated_gpu_id, gpus.current_task_id） |
| 时间戳 | `DATETIME(3)`（毫秒精度）；应用层写 UTC；前端展示转本地时区 |
| 枚举 | 数据库 `VARCHAR` ENUM；后端用 Python `Enum`；禁止裸字符串比较 |
| API 响应 | 成功 `{code:0, data:...}`；失败 `{code:非0, data:null, message:"..."}` |
| WebSocket 消息 | `{event:"...", timestamp:1735296000000, payload:{...}}` |
| 日志 | Python `logging`；格式 `%(asctime)s [%(levelname)s] %(name)s: %(message)s`；写入 `logs/app.log` |
| 配置 | `pydantic-settings`；环境变量 `DATABASE_URL`（格式 `mysql+aiomysql://user:pass@host:port/db`）/ `LOG_LEVEL` / `HOST` / `PORT`；**不使用 Testcontainers**，开发和测试都连接本机 MySQL |

## Stack（Seed — 启动时固定，代码拥有后自由演进）

| Name | 版本 |
| --- | --- |
| Python | 3.11+ |
| FastAPI | 0.115.x |
| uvicorn | 0.32.x |
| SQLAlchemy | 2.0.x |
| aiomysql | 0.2.x |
| MySQL | 8.0+ |
| Vue 3 | 3.5.x |
| Vite | 5.x |
| Pinia | 2.x |
| Vue Router | 4.x |
| Element Plus | 2.x |
| pydantic | 2.x |

## Structural Seed

```text
compute-queue-allocation/
├── backend/
│   ├── .venv/                (已有)
│   ├── app/
│   │   ├── main.py           FastAPI 入口 + lifespan
│   │   ├── config.py         pydantic-settings
│   │   ├── domain/
│   │   │   ├── entities.py   dataclass/ORM 映射类
│   │   │   ├── queue_service.py  FCFS 查询封装
│   │   │   ├── dispatcher.py     asyncio 调度器循环
│   │   │   ├── process_manager.py subprocess 生命周期
│   │   │   └── repositories/
│   │   │       └── interfaces.py  抽象接口（AD-4）
│   │   ├── infrastructure/
│   │   │   ├── mysql/
│   │   │   │   ├── database.py     engine + session
│   │   │   │   ├── models.py       ORM 模型
│   │   │   │   └── repositories.py 接口实现
│   │   │   └── nvidia_smi.py       可选心跳
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── tasks.py
│   │   │   │   ├── gpus.py
│   │   │   │   ├── users.py
│   │   │   │   └── ws.py
│   │   │   └── deps.py          DB session, current user
│   │   └── utils/
│   │       ├── errors.py          AppError + handler
│   │       └── websocket_manager.py
│   ├── logs/
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_dispatcher_concurrency.py
│   │   └── e2e/
│   ├── requirements.txt
│   └── README.md
├── frontend/
│   ├── src/
│   │   ├── main.js / App.vue
│   │   ├── router/ stores/ api/ ws/
│   │   ├── views/ (TaskList, TaskSubmit, GpuDashboard, Login)
│   │   └── components/
│   ├── package.json / vite.config.js / index.html
│   └── README.md
└── docs/
```

## Capability → Architecture Map

| Capability | Lives in | Governed by |
| --- | --- | --- |
| CAP-1 提交任务 | `api/routes/tasks.py` → `queue_service.py` | AD-6（依赖方向）|
| CAP-2 FCFS 自动分配 | `dispatcher.py` + `process_manager.py` | AD-1（事务锁）、AD-2（单一真值）、AD-3（单例）|
| CAP-3 状态可视化 | `api/routes/ws.py` + 前端 Pinia store | AD-5（WebSocket 广播）|
| CAP-4 取消/终止 | `api/routes/tasks.py` → `process_manager.terminate_task()` | AD-7（错误分级）|
| CAP-5 GPU 管理 | `api/routes/gpus.py` | 数据库 schema |
| CAP-6 并发安全 | `infrastructure/mysql/repositories.py` 的 `try_allocate()` | AD-1（FOR UPDATE + 事务）|

## Deferred（明确推迟的设计决策）

| Item | Reason it can wait | 重访条件 |
| --- | --- | --- |
| 乐观锁（UPDATE ... WHERE status='IDLE'）替代悲观锁 | 悲观锁 MVP 可靠但吞吐略低；乐观锁需要处理冲突重试 | 并发量 > 100 req/s |
| Testcontainers MySQL 用于测试隔离 | 开发和测试都直连本机 MySQL，零外部依赖 | 多人并行开发需要数据库隔离 |
| 公平份额调度 | FCFS 是争议最小的基线 | 用户投诉资源被滥用 |
| Docker 容器化执行 | subprocess 启动简单 | 需要环境隔离或资源限制 |
| nvidia-smi 心跳自动检测故障 GPU | MVP 手动标记 MAINTENANCE/FAULTY 足够 | 真实 GPU 故障频发 |
| 自动超时终止僵尸任务 | 管理员手动 terminate 足够 | 长时间僵尸任务积累 |
| 多节点调度 | 单物理机是 MVP 前提 | 组内 GPU 总数 > 8 张 |
| 多卡任务（同型号组队） | MVP 每任务单卡 | ✅ 已实现 2026-10-29（见 ADR-8）：gpu_count 1-N，同型号一次性分配 |
| priority 字段参与排序 | FCFS 公平优先 | 导师要求插队时 |
| 完整用户认证 | 简化 session 标识 MVP 足够 | 需要外网访问 |

## ADR-8：多卡同型号分配（2026-10-29）

**状态**：已实现（Post-MVP 增强，story 3-9）

**背景**：MVP 约束"每任务限 1 张 GPU"，无法支撑 DDP/多卡并行训练任务。成员提出开放 `gpu_count`。

**决策**：
1. `gpu_count` 放开为 1-N（上限 64），多卡任务**限同型号组队**，不做跨型号混搭（4090+6000 会导致 DDP straggler，性能由最慢卡决定）。
2. 分配策略：目标型号 = `gpu_model_preference`（若填）否则 = 最早空闲卡的型号；一次性 `SELECT ... FOR UPDATE` 锁 N 张同型号 IDLE 卡。
3. **凑不齐 N 张时队首阻塞、保持排队**（保严格 FCFS，不插队、不降级为单卡）——已知代价：队首多卡任务可能阻塞后续单卡短任务，后续可加"超时降级"演进。
4. 数据模型取最简：`tasks.allocated_gpu_ids VARCHAR` 存逗号串记录，不引入 `task_gpus` 关联表；GPU 占用关系复用 `gpus.current_task_id`（多行指向同一任务），释放统一按 `current_task_id` 批量查询。
5. `CUDA_VISIBLE_DEVICES` 注入逗号分隔串，顺序与 GPU id 升序一致。

**影响**：dispatcher 分配逻辑、ProcessManager 注入与释放路径、前端 GPU Count 上限（= 已登记 GPU 数）、TaskResponse 新增 `allocated_gpu_ids`。回滚方式：`gpu_count` 校验收回为 1 即可。