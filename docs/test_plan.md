# compute-queue-allocation 系统测试计划

- 版本：1.0
- 日期：2026-10-31
- 负责人：B（测试与架构验证负责人）
- 测试对象：GPU Queue Allocation
- 测试依据：项目源码、README、`docs/测试与部署手册.md`、现有 `backend/tests/` 测试代码

## 1. 测试目标

1. 验证 FCFS 队列按提交时间顺序调度。
2. 验证 GPU 分配和释放正确，避免重复分配。
3. 验证多 GPU 任务只分配同型号 GPU，且必须一次性凑齐。
4. 验证 Dispatcher 并发场景下资源分配安全。
5. 验证任务从 QUEUED 到终态的状态流转。
6. 验证 `tasks`、`gpus`、`allocation_log` 三类数据的一致性。
7. 验证 Windows 下任务进程启动、失败、终止和进程树清理。
8. 对项目已知限制进行记录，避免将未实现功能误判为缺陷。

## 2. 测试范围

### 2.1 本轮范围内

- Dispatcher：队首选择、FCFS 顺序、单卡/多卡分配。
- GPU：IDLE、ALLOCATED、RUNNING、MAINTENANCE、FAULTY 状态及资源释放。
- ProcessManager：启动任务、退出码处理、日志文件、终止进程。
- Task API：创建、查询、取消、终止、参数校验。
- AllocationLog：ALLOCATE/RELEASE 事件记录。
- MySQL 并发分配安全。
- Windows 命令行和进程树终止行为。

### 2.2 本轮不作为通过条件

- 真实 GPU 训练吞吐量/性能基准。
- 多用户认证与完整 RBAC（当前为 MVP 占位实现）。
- WebSocket 实时推送（当前为轮询）。
- priority 优先级调度（字段存在但当前不参与排序）。
- 跨型号多 GPU 混合分配（当前明确不支持）。
- 分布式多后端节点调度。

## 3. 测试环境

| 项目 | 计划/要求 | 实际记录 |
|---|---|---|
| 操作系统 | Windows（项目目标环境） | 待测试执行人填写 |
| Python | 以 `backend/requirements.txt` 和本机安装为准 | 待填写 |
| FastAPI | `>=0.115,<0.116` | 依赖范围已从源码包确认 |
| SQLAlchemy | `>=2.0,<2.1` | 依赖范围已从源码包确认 |
| MySQL | MySQL 8.0+（并发测试要求） | 待填写 |
| SQLite | 用于常规异步单元/功能测试 | 项目 conftest 已配置 |
| GPU | NVIDIA GPU；若无设备，先完成数据库/调度逻辑测试 | 待填写 |
| CUDA | 与实际 NVIDIA 驱动兼容 | 待填写 |
| pytest | `>=8.0,<9.0` | 历史日志记录 pytest 8.4.2 |
| pytest-asyncio | `>=0.24,<1.0` | 依赖范围已从源码包确认 |

常规测试 fixture 在 `backend/tests/conftest.py` 中创建临时 SQLite 数据库；并发测试单独创建 MySQL engine。两类测试的结论必须分开报告。

## 4. 测试策略

### 4.1 测试层级

| 层级 | 主要内容 | 数据库/环境 |
|---|---|---|
| 单元/组件测试 | 模型、Dispatcher、ProcessManager、API 路由 | 临时 SQLite |
| 集成测试 | Dispatcher + ProcessManager 生命周期、数据一致性 | 临时 SQLite + 本机子进程 |
| 并发集成测试 | 多协程争抢 GPU、MySQL 行锁 | 专用隔离 MySQL 测试库 |
| 手工系统测试 | 前端操作、后端日志、Windows 进程树、真实 GPU 映射 | Windows + 实际部署环境 |

### 4.2 测试执行原则

1. 先执行 SQLite 常规测试，再执行 MySQL 并发测试。
2. 并发测试前停止正在运行的后端实例。
3. 并发测试文件当前包含 `drop_all/create_all`，且数据库连接参数硬编码；修正为专用测试库并完成库名保护前，不得对含真实数据的数据库执行。
4. SQLite 测试通过不能替代 MySQL 并发测试通过。
5. 每次执行保存命令、时间、环境、退出码、pytest 汇总和失败堆栈。
6. 测试失败时先保留日志，再定位原因；修复后重跑失败用例和相关回归用例。
7. 不在测试中使用真实训练命令或会修改用户数据的命令；子进程测试使用短时、可控的 Python 命令。

## 5. 测试用例

### 5.1 FCFS 调度

| ID | 场景/步骤 | 预期结果 | 优先级 |
|---|---|---|---|
| FCFS-01 | 创建多个提交时间不同的 QUEUED 任务，GPU 数量足够，执行 Dispatcher | 按 submitted_at ASC、id ASC 分配 | P0 |
| FCFS-02 | 两个任务 submitted_at 相同 | 按任务 ID 升序 | P1 |
| FCFS-03 | 队首任务资源不足 | 队首保持 QUEUED，后续任务不越过队首 | P0 |
| FCFS-04 | 非 QUEUED 任务排在数据库中 | Dispatcher 不重新分配 PENDING/RUNNING/终态任务 | P1 |

### 5.2 GPU 分配

| ID | 场景/步骤 | 预期结果 | 优先级 |
|---|---|---|---|
| GPU-01 | 1 个 QUEUED 单卡任务 + 1 张 IDLE GPU | Task -> PENDING；GPU -> ALLOCATED；写 1 条 ALLOCATE | P0 |
| GPU-02 | 无 IDLE GPU | 任务保持 QUEUED，不产生分配日志 | P0 |
| GPU-03 | 同一任务再次运行 Dispatcher | 不重复分配同一任务，不增加重复日志 | P0 |
| GPU-04 | 多卡任务要求 N 张同型号 GPU | 一次性分配 N 张；任务记录 GPU ID 列表 | P0 |
| GPU-05 | 同型号空闲卡不足 N 张 | 不分配任何 GPU，任务保持 QUEUED | P0 |
| GPU-06 | GPU 状态从 RUNNING 被修改为 MAINTENANCE/FAULTY | API 应拒绝该非法修改 | P1 |

### 5.3 并发调度

| ID | 场景/步骤 | 预期结果 | 优先级 |
|---|---|---|---|
| CON-01 | 1 张 IDLE GPU、50 个 QUEUED 任务、50 个并发分配调用 | 仅 1 个成功，1 条 ALLOCATE 日志 | P0 |
| CON-02 | 2 张 IDLE GPU、30 个 QUEUED 任务、30 个并发调用 | 仅 2 个成功，2 条 ALLOCATE 日志 | P0 |
| CON-03 | 1 张 GPU、100 个并发调用 | GPU 仅绑定一个任务，Task/GPU/日志一致 | P0 |

以上必须在隔离 MySQL 测试库验证。当前源码中的 `test_dispatcher_concurrency.py` 就是 MySQL 测试，但其硬编码 URL 和 drop_all 风险必须先解决。

### 5.4 多 GPU

| ID | 场景/步骤 | 预期结果 | 优先级 |
|---|---|---|---|
| MG-01 | 2 张 RTX 3090 + 1 张 A100，任务请求 2 卡 | 只分配 2 张 RTX 3090 | P0 |
| MG-02 | 指定 A100 偏好但只有 1 张 A100，任务请求 2 卡 | 不分配，保持 QUEUED | P0 |
| MG-03 | 无型号偏好且多种型号存在 | 以最早 ID 的空闲卡型号为目标，不混型号 | P1 |
| MG-04 | 队首多卡任务无法凑齐，队尾单卡任务可运行 | 按当前 FCFS 队首阻塞策略，队尾不越过队首 | P0 |
| MG-05 | 多卡任务完成/失败 | 所有 GPU 一起释放，逐卡写 RELEASE 日志 | P0 |
| MG-06 | `gpu_count` 为 0、负数或大于 64 | API 返回参数校验错误 | P1 |
| MG-07 | `gpu_count` 在 1、2、8、64 范围内 | API 接受合法值（资源是否满足由调度决定） | P1 |

### 5.5 任务生命周期

| ID | 场景/步骤 | 预期结果 | 优先级 |
|---|---|---|---|
| LIFE-01 | 创建任务 | 初始状态 QUEUED | P0 |
| LIFE-02 | Dispatcher 分配后 | 状态 PENDING，GPU ALLOCATED | P0 |
| LIFE-03 | ProcessManager 成功启动 | 状态 RUNNING，GPU RUNNING，started_at 非空 | P0 |
| LIFE-04 | 子进程退出码 0 | 状态 COMPLETED，GPU 全部释放 | P0 |
| LIFE-05 | 子进程退出码非 0 | 状态 FAILED，记录退出码，GPU 全部释放 | P0 |
| LIFE-06 | 取消 QUEUED 任务 | 状态 CANCELLED，不占用 GPU | P0 |
| LIFE-07 | 终止 RUNNING 任务 | 状态 TERMINATED，进程树结束，GPU 全部释放 | P0 |
| LIFE-08 | 启动命令不存在/启动失败 | 状态 FAILED，exit_code=-1，GPU 释放 | P1 |
| LIFE-09 | 终止已经处于终态的任务 | API 拒绝重复终止 | P1 |

### 5.6 数据一致性

| ID | 检查规则 | 预期结果 | 优先级 |
|---|---|---|---|
| CONS-01 | 每张 ALLOCATED/RUNNING GPU 的 current_task_id | 指向有效的 PENDING/RUNNING 任务 | P0 |
| CONS-02 | 一个任务的 allocated_gpu_ids | 与 current_task_id 指向该任务的 GPU 集合一致 | P0 |
| CONS-03 | 每次成功分配 | 每张被分配 GPU 对应一条 ALLOCATE 日志 | P0 |
| CONS-04 | 每次完成/失败/终止释放 | 每张释放 GPU 对应一条 RELEASE 日志 | P0 |
| CONS-05 | 终态任务 | 不应继续占用 GPU | P0 |
| CONS-06 | GPU 回到 IDLE | current_task_id 必须为 NULL | P0 |

## 6. 进入/退出标准

### 6.1 进入标准
- 后端依赖安装完成。
- SQLite 测试 fixture 可正常创建临时数据库。
- MySQL 并发测试已配置独立测试库。
- 当前项目 `.env` 和测试库连接配置已脱敏并核对。
- 测试代码能够被 pytest 收集。

### 6.2 退出标准
- 所有 P0 用例通过，或未通过项均有明确缺陷单和风险接受记录。
- MySQL 并发测试真实执行并保存证据。
- 任务生命周期和三表一致性测试通过。
- 没有未解释的失败、跳过或环境错误。
- 最终报告区分“已执行通过”“失败”“跳过”“待执行”。

## 7. Windows 测试命令

在 PowerShell 中执行：

```powershell
cd <项目目录>\backend

# 确认 Python 和 pytest
python --version
python -m pytest --version

# 常规 SQLite 测试（先不要包括 MySQL 并发测试）
$env:SKIP_MYSQL_TESTS = "1"
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tests -v --tb=short

# 单独运行多卡测试
python -m pytest tests/test_multigpu.py -v

# 并发测试：仅当测试文件已改为专用测试库且确认连接库名后才执行
Remove-Item Env:SKIP_MYSQL_TESTS -ErrorAction SilentlyContinue
python -m pytest tests/test_dispatcher_concurrency.py -v
```

注意：
- 当前 `test_dispatcher_concurrency.py` 使用硬编码 `gpu_queue` 数据库并执行 drop_all。以上并发命令是执行形式说明，不代表当前文件已安全可直接运行。
- 项目手册明确提示并发测试前停止后端服务。不要在生产/共享数据库运行。
- 若本机没有 NVIDIA GPU，可先测试调度数据库逻辑；真实 CUDA_VISIBLE_DEVICES 映射需要在有 GPU 的环境补测。

## 8. 缺陷记录模板

每个缺陷至少记录：
- 缺陷编号：
- 标题：
- 严重程度：Blocker / Critical / Major / Minor / Trivial
- 环境：
- 前置条件：
- 复现步骤：
- 预期结果：
- 实际结果：
- 日志/截图：
- 关联测试用例：
- 修复提交：
- 回归结果：

## 9. 测试结果记录

本次 ZIP 中包含历史测试日志：
- `backend/all_test3.txt`：记录 67 passed、3 warnings，耗时 52.93 秒。
- `backend/testresult.log`：记录 56 项测试中 `test_dispatcher_no_tasks` 失败，原因是测试代码调用 `GPU.where(...)`，同时日志轮转出现 Windows 文件占用错误。
- `backend/test_output.txt`：记录测试收集阶段 `ModuleNotFoundError: No module named 'app'`。

这些日志来自不同执行批次，不能视为同一次测试结果。当前交付包不会将其写成“当前测试全部通过”。新一轮执行结果应保存到 `evidence/test-logs/`。
