<!-- bmad:context -->
<!-- 2026-11-25 核对源码提交 092db91。由 bmad-project-context 管理。以下规则均待团队评审。 -->

## GPU 算力队列分配系统

本项目在单台物理机上调度 GPU 任务。Vue 页面通过 FastAPI 操作任务和 GPU，调度与执行状态保存在 MySQL。需求、架构和验收计划见 `_bmad-output/planning-artifacts/`。

## 入口

- 修改分配或回收时，联查 `backend/app/core/dispatcher.py`、`backend/app/core/process_manager.py` 和相关 API 路由。修改接口时，联查 `frontend/src/App.vue` 与 `backend/tests/`。

## 运行与验证

1. 从 `backend/` 使用含 `aiosqlite` 的项目 Python 环境运行常规回归。PowerShell 中先设 `$env:SKIP_MYSQL_TESTS = "1"`，再运行 `python -m pytest tests`。
2. 用独立、可丢弃的 MySQL 库验证行锁。运行并发测试前，核对 fixture 的实际连接目标和库名保护，并停止连接同一库的后端。fixture 会删表，应用的 `DATABASE_URL` 不会覆盖它的连接设置。分别报告 SQLite 功能回归和 MySQL 并发结果。
3. 以单个后端工作进程验收调度。Windows 上验证任务启动时去掉 `--reload`。启动验收同时检查 `/health`、数据库读写和一个受控任务的实际运行。

## 项目约定

4. 调度器只从 `QUEUED` 中按 `submitted_at`、`id` 升序取队首。相同提交时间按 ID 决定次序。队首资源不足时保持排队，后续任务不得越过队首。
5. 只分配 `IDLE` 卡。单卡选择 ID 最小的空闲卡。多卡按指定型号筛选，未指定时以 ID 最小的空闲卡的型号为准。只有凑齐请求数量才写入绑定和分配日志。
6. 在同一 MySQL 事务中锁定队首任务和待分配 GPU，一次提交任务 `PENDING`、GPU `ALLOCATED`、`current_task_id` 和每卡一条 `ALLOCATE`。并发争用核对单卡只有一个任务绑定和一条分配记录，提交前异常核对无部分写入。
7. 子进程成功启动后才将任务及绑定 GPU 更新为 `RUNNING`。退出码为 0 时记为 `COMPLETED`，非 0 或启动失败时记为 `FAILED`。回归覆盖成功、非零退出和启动失败。
8. 回收时用 `GPU.current_task_id` 查找任务绑定的全部卡，逐卡恢复 `IDLE`、清除绑定并写入一条 `RELEASE`。双卡任务验收核对两张卡。终止运行任务时同时检查实际进程是否退出。
9. `POST /tasks` 受理后返回 HTTP 201，任务初始为 `QUEUED`。`gpu_count` 缺省为 1，输入范围为 1–64，越界返回 422。分别验证参数边界与实际可分配容量。
10. 接口排队位置按提交时间和 ID 计算，计入 `QUEUED`、`PENDING`、`RUNNING`，终态返回空值。以不同状态和相同提交时间的任务验证序号。
11. 按现有接口边界，仅 `QUEUED` 可取消，仅 `PENDING` 和 `RUNNING` 可终止。对其他状态调用相应操作时应返回 400，并保留原状态。
12. GPU 管理接口应拒绝把 `RUNNING` 卡直接标为 `MAINTENANCE` 或 `FAULTY`。两种修改分别验收为 HTTP 400，并核对原状态和任务绑定。
13. 改动任务或 GPU 接口时，同步回归前端实际使用的 `/tasks`、`/tasks/admin`、`/gpus`，以及列表的 `items` 和错误响应的 `detail`。接口路径或响应结构有变更时，同步更新消费者和契约用例。

<!-- /bmad:context -->
