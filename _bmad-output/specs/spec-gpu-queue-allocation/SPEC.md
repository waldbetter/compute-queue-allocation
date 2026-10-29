---
id: SPEC-gpu-queue-allocation
companions:
  - database-schema.md
  - state-machines.md
  - api-contracts.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate.

# 组内算力排队与分配系统 — MVP

## Why

实验室或课题组拥有数量有限的 GPU 算力卡（通常 1-8 张），成员提交深度学习训练/推理任务时需要排队等待可用卡。当前缺乏统一管理手段：任务提交后不知道前面排了多少人、什么时候能拿到卡；多人同时抢同一张刚释放的卡时可能出现冲突；管理员无法全局监控资源占用和任务状态。组内迫切需要一个轻量级的排队与分配系统来解决这些问题。

## Capabilities

- **CAP-1 — 用户可提交 GPU 任务**
  - intent: 团队成员可以通过 Web UI 提交一个需要 GPU 的计算任务，包含任务名称、执行命令、所需 GPU 数量（1-N 张，多卡限同型号），提交后任务进入排队系统。
  - success: 提交后 200ms 内后端返回确认，任务出现在个人任务列表中，状态为 QUEUED 或 RUNNING（如有空闲卡）。

- **CAP-2 — 系统按 FCFS 自动分配空闲 GPU**
  - intent: 当有 GPU 空闲时，系统严格按照提交时间 + 唯一 ID 排序的队列头部取出任务，分配一张或多张同型号空闲卡并自动启动任务脚本（多卡任务一次性凑齐 N 张同型号卡，否则队首阻塞等待）。
  - success: 空闲 GPU 释放后 1 秒内被分配给下一个排队任务，任务状态变为 RUNNING，GPU 状态变为 ALLOCATED/RUNNING。

- **CAP-3 — 任务生命周期全流程可视化**
  - intent: 用户可以实时查看自己任务的状态、排队位置、开始/结束时间和退出码。
  - success: 任务状态变更后（QUEUED→RUNNING→COMPLETED/FAILED/CANCELLED/TERMINATED），500ms 内所有相关用户的前端界面通过 WebSocket 推送更新。

- **CAP-4 — 用户取消 / 管理员终止任务**
  - intent: 用户可以取消自己尚未开始运行的任务；管理员可以终止任意状态的任务（包括正在运行的），释放 GPU 资源。
  - success: 取消操作 100ms 内生效；运行中任务被终止后 GPU 立即可用于下一个排队任务。

- **CAP-5 — GPU 资源管理面板（管理员）**
  - intent: 管理员可以登记、查看、维护 GPU 资源，标记维护/故障状态，查看每张卡的实时状态和当前运行任务。
  - success: 管理员进入 GPU 管理面板可看到每张卡的型号、显存、状态、关联任务；可标记 MAINTENANCE 阻止该卡参与分配；RUNNING 中的卡禁止标记维护。

- **CAP-6 — 并发安全：防止同一张卡被重复分配**
  - intent: 当多个任务同时争用同一张空闲 GPU 时，系统必须保证只有一个任务能成功分配，其余收到明确的冲突错误。
  - success: 压测 100 个并发请求争用 1 张 IDLE GPU，分配日志中仅有 1 条 ALLOCATE 记录，99 个失败请求收到 409 Conflict。

## Constraints

- **单物理机、单机调度**：MVP 不考虑多节点集群，所有 GPU 必须在同一台物理机上，后端与 GPU 调度器也运行在该机器上。
- **每任务 1-N 张 GPU（多卡限同型号）**：`gpu_count` 支持 1-N（上限 64）。多卡任务必须一次性凑齐 N 张**同型号**空闲卡才分配；凑不齐则队首阻塞、保持排队（保 FCFS 语义），不允许 4090+6000 跨型号混搭。任务填入 `gpu_model_preference` 时以该型号为目标，否则以最早空闲卡的型号为基准。
- **Python subprocess 执行引擎**：任务通过后端进程的 Python `subprocess.Popen` / `asyncio.create_subprocess_exec` 启动，不通过 Docker、Kubernetes 或 Slurm。
- **FCFS 排队，不启用优先级 / 公平份额**：队列严格按 `submitted_at ASC, id ASC` 排序；数据库和代码中可保留 priority 字段但 MVP 阶段排序逻辑不使用它。
- **数据库悲观锁保证分配原子性**：GPU 分配操作必须在 `START TRANSACTION` 内执行 `SELECT ... FOR UPDATE` 锁定目标行，在同一事务内完成两张表的状态更新 + 写 allocation_log，然后 `COMMIT`。任何异常必须触发 `ROLLBACK`。隔离级别 `REPEATABLE READ`。
- **前端 Web UI 为唯一交互入口**：MVP 不提供 CLI `sbatch` 风格的脚本提交接口，所有任务提交/取消通过 Vue 前端完成。
- **本机直接运行部署**：MVP 用 `uvicorn app.main:app` 启动后端、`npm run dev` 或 `npm run build && npm run serve` 启动前端，不使用 Docker Compose 或 Kubernetes。
- **subprocess 启动时自动注入 `CUDA_VISIBLE_DEVICES`**：ProcessManager 在 `asyncio.create_subprocess_exec` 时，必须将环境变量 `CUDA_VISIBLE_DEVICES=<gpu_logical_id>` 加入 env dict。逻辑 id 从 0 开始（与 `nvidia-smi` 的 GPU 索引一致），映射到数据库 gpus 表中 id 为 N 的卡时，其 logical id 为 `N-1`（因数据库 id 从 1 自增）。单卡任务注入单个值；多卡任务注入逗号分隔串（如 `1,2`），顺序与数据库 id 升序一致。
- **Windows 开发 / Linux 生产**：开发环境为 Windows（Trae IDE），目标部署环境为 Linux 物理机；代码需保证跨平台（特别是 subprocess 调用、CUDA_VISIBLE_DEVICES 设置、进程终止信号）。

## Non-goals

- 多节点 GPU 集群调度（Ray、K8s GPU operator、Slurm/PBS）
- 跨型号多卡任务（4090+6000 混搭；DDP/ZeRO 等并行训练仅限同型号组队，跨型号不支持）
- Docker 容器化任务隔离
- 任务依赖链（B 等 A 完成后自动启动）
- GPU 资源预约 / 占位（提前锁定未来时间窗口）
- 按 GPU 型号隔离独立队列（A100 队列 vs RTX 3090 队列）
- 公平份额调度、优先级插队（priority 字段保留但不生效）
- 完整用户认证系统（用户名密码散列、JWT、LDAP/OAuth、CSRF 防护）—— MVP 用简化用户标识
- 邮件 / Webhook / 钉钉等外部通知
- 任务日志完整实时 streaming（MVP 只记录退出码 + 基础时间戳，完整日志查看为可选）
- API 限流、配额、付费层级
- 多语言国际化（i18n）
- GPU 硬件指标监控面板（温度、利用率、显存曲线）

## Success signal

组内成员完成以下全流程的时间 ≤ 5 分钟：登录 → 提交一个 Python 训练脚本 → 看到任务从 QUEUED 变为 RUNNING 再到 COMPLETED → 查看退出码。管理员实时看到所有 GPU 状态；多人同时提交时 FCFS 顺序正确且排队位置实时更新。压测 100 个并发抢 1 张卡，无重复分配。

## Assumptions

- 单台物理机 GPU 数量 ≤ 8 张；同时排队任务 ≤ 20 个（规模可控，FCFS 足够）。
- `nvidia-smi` 可检测到 GPU 被 subprocess 启动的进程正确关联到设备句柄。
- 运行后端进程的 OS 用户具有操作所有 GPU 的权限（Linux 下属 video + render 组）。
- MVP 阶段安全要求不高，简化用户标识（session/cookie）足够。
- MySQL 8.0 在目标物理机和开发机上都直接运行，连接串通过环境变量 `DATABASE_URL` 配置（格式 `mysql+aiomysql://user:password@host:port/dbname`）。**不使用 Testcontainers**。

## Resolved Decisions（2026-10-26 组内确认）

- **Q1 ✅ — 后端自动注入 `CUDA_VISIBLE_DEVICES`**：调度器分配到 GPU #N 后，ProcessManager 启动 subprocess 时自动注入环境变量 `CUDA_VISIBLE_DEVICES=N`（如分配到第三张卡就设 `CUDA_VISIBLE_DEVICES=2`，物理机从 0 开始编号）。任务 command 不需要用户自己管理 GPU 设备号。MVP 每任务限单卡，故只注入一个设备号。
- **Q2 ✅ — MySQL 连接方案**：使用环境变量 `DATABASE_URL` 配置连接串（格式 `mysql+aiomysql://user:password@host:port/dbname`）。开发阶段直接使用本机 MySQL 实例，**不引入 Testcontainers**。测试环境同样连接本机 MySQL。
- **Q3 ✅ — 前端 UI 框架**：确定使用 **Vue 3 + Vite + Element Plus**，搭配 Pinia 状态管理和 Vue Router。MVP 阶段不考虑 Tailwind。
- **Q4（原）— 任务命令是否支持挂载数据集路径**：**MVP 暂不支持**，command 字段就是 shell 原生命令字符串，工作目录和环境变量（除 CUDA_VISIBLE_DEVICES）由用户自行在 command 内处理。
- **Q5（原）— 任务超时自动终止**：**MVP 暂不设自动超时**。长时间僵尸任务由管理员手动 terminate。
- **Q6 ✅ — 多卡同型号分配（2026-10-29 新增）**：`gpu_count` 放开为 1-N（上限 64）。分配策略：任务填了 `gpu_model_preference` 以该型号为目标，否则以最早空闲卡的型号为基准；一次性 `SELECT ... FOR UPDATE` 锁 N 张同型号 IDLE 卡，凑不齐则队首阻塞保持排队（保 FCFS，不引入插队/降级逻辑）。`CUDA_VISIBLE_DEVICES` 注入逗号串；`GPU.current_task_id` 多行指向同一任务，完成/终止/启动失败均按 `current_task_id` 批量释放。最简实现：`tasks.allocated_gpu_ids` 存逗号串，不引入 task_gpus 关联表。