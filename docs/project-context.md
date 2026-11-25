# GPU 算力队列分配系统项目规则

课程交付材料 · 2026-11-25 · 静态核对源码提交 `092db91`

[AGENTS.md](../AGENTS.md) 是规则正文的来源。本文件按根目录规则的 1–13 顺序映射 `RULE-001` 至 `RULE-013`，逐条附上理由、证据和检查方式。项目规则已获准写入，团队评审状态均为**待团队评审**。本次只静态核对源码、架构和已有用例。检查步骤的描述与历史测试记录均不代表本次执行结果。 [PRD](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md) · [Epic 与验收追溯](../_bmad-output/planning-artifacts/epics.md) · [历史测试摘要](../evidence/screenshots/test-logs/historical-results.md)

## RULE-001 隔离 SQLite 功能回归

**规则**。从 `backend/` 使用含 `aiosqlite` 的项目 Python 环境运行常规回归。PowerShell 中先设 `$env:SKIP_MYSQL_TESTS = "1"`，再运行 `python -m pytest tests`。

- **制定理由**。常规测试通过异步 fixture 创建临时 SQLite 库。显式跳过 MySQL 并发测试可避免常规回归连接其他数据库。
- **依据**。[SQLite fixture](../backend/tests/conftest.py#L9) · [pytest 配置](../backend/pytest.ini#L1) · [测试计划 §7](test_plan.md#L164)
- **检查方式**。在 PowerShell 切换到 `backend/` 并确认项目 Python 能导入 `aiosqlite`。设置规则中的开关，执行 `python -m pytest tests`，记录通过、失败及跳过项，核对 MySQL 用例标记为跳过。
- **当前验证状态**。已静态核对命令和 fixture。本次未运行常规回归。
- **团队评审状态**。待团队评审。

## RULE-002 在专用 MySQL 上验证并发

**规则**。用独立、可丢弃的 MySQL 库验证行锁。运行并发测试前，核对 fixture 的实际连接目标和库名保护，并停止连接同一库的后端。fixture 会删表，应用的 `DATABASE_URL` 不会覆盖它的连接设置。分别报告 SQLite 功能回归和 MySQL 并发结果。

- **制定理由**。并发 fixture 自行创建连接，并在用例前后删表，因此应用配置与测试实际连接目标需要分别检查。
- **依据**。[并发 fixture](../backend/tests/test_dispatcher_concurrency.py#L39) · [测试执行原则](test_plan.md#L69) · [风险 R-02](risk_lisk.md#L40)
- **检查方式**。检查 fixture 能否明确绑定可丢弃专用库，验证错库会拒绝执行，并确认同库后端已停止。前置条件满足后，在 `backend/` 清除 `SKIP_MYSQL_TESTS`，单独运行 `python -m pytest tests/test_dispatcher_concurrency.py -v`。
- **当前验证状态**。已静态核对固定连接和删表行为。专用库配置、库名保护及 MySQL 执行结果待验证。
- **团队评审状态**。待团队评审。

## RULE-003 验收单进程部署

**规则**。以单个后端工作进程验收调度。Windows 上验证任务启动时去掉 `--reload`。启动验收同时检查 `/health`、数据库读写和一个受控任务的实际运行。

- **制定理由**。后端在每个应用进程的 lifespan 启动调度器和进程管理器。健康接口返回静态状态，数据库与子进程需要额外验证。
- **依据**。[应用生命周期](../backend/app/main.py#L18) · [健康接口](../backend/app/api/routes/health.py#L6) · [架构 AD-3](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L63) · [部署手册 §5.1](测试与部署手册.md#L100)
- **检查方式**。按手册在目标环境以单工作进程启动，Windows 启动参数中省略 `--reload`。检查启动日志中的后台实例、`GET /health` 的 200，执行一次数据库读写并用受控任务观察调度、运行和退出。
- **当前验证状态**。已静态核对服务入口和手册。本次未启动后端或执行部署验收。
- **团队评审状态**。待团队评审。

## RULE-004 保持严格 FCFS

**规则**。调度器只从 `QUEUED` 中按 `submitted_at`、`id` 升序取队首。相同提交时间按 ID 决定次序。队首资源不足时保持排队，后续任务不得越过队首。

- **制定理由**。队首阻塞是当前业务行为。稳定的同时间排序使并发提交结果可复核。
- **依据**。[调度器队首查询](../backend/app/core/dispatcher.py#L48) · [FCFS-01～04](test_plan.md#L81) · [调度器测试](../backend/tests/test_dispatcher.py#L124)
- **检查方式**。准备提交时间不同及相同的排队任务，核对分配记录按时间、ID 升序。再令队首的资源不足，后续任务所需卡可用，确认整个队列保持原先顺序且没有新分配。
- **当前验证状态**。已静态核对排序和阻塞路径。现有 FCFS 用例可复用，同时间排序和阻塞场景待复验。
- **团队评审状态**。待团队评审。

## RULE-005 按型号整组分配空闲 GPU

**规则**。只分配 `IDLE` 卡。单卡选择 ID 最小的空闲卡。多卡按指定型号筛选，未指定时以 ID 最小的空闲卡的型号为准。只有凑齐请求数量才写入绑定和分配日志。

- **制定理由**。整组分配保持任务请求和实际绑定一致。按指定型号或最小空闲卡 ID 确定型号使选择结果可复现。
- **依据**。[单卡与多卡选择](../backend/app/core/dispatcher.py#L77) · [架构 ADR-8](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L232) · [多卡测试](../backend/tests/test_multigpu.py#L52)
- **检查方式**。准备按 ID 排列的 A、B、B 三张空闲卡。测试单卡分配到最小 ID。多卡请求两张并指定 B 时核对两张 B 卡同时绑定。另起相同环境，省略偏好时检查任务继续排队，状态、绑定和日志无部分写入。
- **当前验证状态**。已静态核对同型号选择、型号偏好和资源不足分支。未运行现有多卡测试。
- **团队评审状态**。待团队评审。

## RULE-006 原子提交分配变更

**规则**。在同一 MySQL 事务中锁定队首任务和待分配 GPU，一次提交任务 `PENDING`、GPU `ALLOCATED`、`current_task_id` 和每卡一条 `ALLOCATE`。并发争用核对单卡只有一个任务绑定和一条分配记录，提交前异常核对无部分写入。

- **制定理由**。任务状态、GPU 绑定及分配日志由不同模块读取。行锁和一次提交使它们在争用时保持一致。
- **依据**。[分配事务](../backend/app/core/dispatcher.py#L58) · [架构 AD-1](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L41) · [100 路争用用例](../backend/tests/test_dispatcher_concurrency.py#L216)
- **检查方式**。在符合 RULE-002 的 MySQL 环境核对实际隔离级别与 AD-1 的 `REPEATABLE READ` 一致。准备一张空闲卡和 100 个任务，并发触发 100 次分配，暂停回收，核对唯一绑定和一条 `ALLOCATE`，并补验其余 99 个任务仍为 `QUEUED`。另在提交前注入错误，核对任务、卡及分配记录均无部分写入。
- **当前验证状态**。已静态核对行锁、提交边界和既有单绑定、单日志断言。MySQL 运行、99 个等待断言和异常回滚待补验。
- **团队评审状态**。待团队评审。

## RULE-007 按子进程结果转换任务状态

**规则**。子进程成功启动后才将任务及绑定 GPU 更新为 `RUNNING`。退出码为 0 时记为 `COMPLETED`，非 0 或启动失败时记为 `FAILED`。回归覆盖成功、非零退出和启动失败。

- **制定理由**。仅在启动成功后写入运行状态，使状态与实际执行对应。失败路径需要覆盖进程无法启动及已启动但异常退出。
- **依据**。[进程启动分支](../backend/app/core/process_manager.py#L155) · [退出状态写回](../backend/app/core/process_manager.py#L280) · [LIFE-03～05、LIFE-08](test_plan.md#L123) · [进程管理测试](../backend/tests/test_process_manager.py#L51)
- **检查方式**。分别提交正常退出、非零退出和无法启动的受控命令。对成功启动的任务观察任务和 GPU 同为 `RUNNING`，再核对三种场景的最终状态、结束时间和退出码。
- **当前验证状态**。已静态核对状态写回及对应测试代码。本次未执行这些用例。
- **团队评审状态**。待团队评审。

## RULE-008 回收任务占用的全部 GPU

**规则**。回收时用 `GPU.current_task_id` 查找任务绑定的全部卡，逐卡恢复 `IDLE`、清除绑定并写入一条 `RELEASE`。双卡任务验收核对两张卡。终止运行任务时同时检查实际进程是否退出。

- **制定理由**。任务可以绑定多张卡。根据每张 GPU 上的当前任务关联回收，可覆盖整组资源。数据库终态本身不足以判断进程树已经退出。
- **依据**。[批量回收](../backend/app/core/process_manager.py#L280) · [终止与回收路由](../backend/app/api/routes/tasks.py#L157) · [多卡释放测试](../backend/tests/test_multigpu.py#L200) · [手册终止场景](测试与部署手册.md#L251)
- **检查方式**。使用双卡任务分别验证完成、失败和终止。按 GPU ID 核对两张卡均为 `IDLE`、绑定已清除且每卡一条 `RELEASE`。终止路径记录进程及子进程是否退出，独立覆盖失联和终止超时。
- **当前验证状态**。已静态核对整组回收和现有双卡用例。终止进程树、双卡异常分支及失联回收待补验。
- **团队评审状态**。待团队评审。

## RULE-009 保持任务提交契约

**规则**。`POST /tasks` 受理后返回 HTTP 201，任务初始为 `QUEUED`。`gpu_count` 缺省为 1，输入范围为 1–64，越界返回 422。分别验证参数边界与实际可分配容量。

- **制定理由**。HTTP 201 表示任务已受理，实际分配由调度器执行。请求数值范围和硬件可分配能力各有独立验收条件。
- **依据**。[创建任务路由](../backend/app/api/routes/tasks.py#L26) · [输入模型](../backend/app/schemas/task.py#L8) · [参数边界用例](../backend/tests/test_multigpu.py#L286) · [任务模型](../backend/app/models/task.py#L36)
- **检查方式**。暂停分配后，分别省略 `gpu_count`、传入 1、64、0 和 65。验证合法请求返回 201 且初始为 `QUEUED`，省略时为 1，无效请求返回 422 且不新增任务。可分配容量在独立资源场景验证。
- **当前验证状态**。已静态核对 API 校验和初始状态。参数用例待运行，实际容量按 PRD O-05 待确认。
- **团队评审状态**。待团队评审。

## RULE-010 保持任务排队序号口径

**规则**。接口排队位置按提交时间和 ID 计算，计入 `QUEUED`、`PENDING`、`RUNNING`，终态返回空值。以不同状态和相同提交时间的任务验证序号。

- **制定理由**。任务页需要显示统一的活跃序号。调度选择队首与前端计算序号各有明确的状态集合。
- **依据**。[详情路由](../backend/app/api/routes/tasks.py#L74) · [排队序号计算](../backend/app/api/routes/tasks.py#L229) · [活跃和终态测试](../backend/tests/test_tasks.py#L194)
- **检查方式**。以相同提交时间构造不同任务 ID，加入三种活跃状态及四种终态。在列表和详情中验证活跃任务的全局序号按 ID 打破并列，终态的 `queue_position` 为 `null`。
- **当前验证状态**。已静态核对状态集合和计数逻辑。现有列表与详情用例未执行，并列场景待复验。
- **团队评审状态**。待团队评审。

## RULE-011 保持取消和终止的状态边界

**规则**。按现有接口边界，仅 `QUEUED` 可取消，仅 `PENDING` 和 `RUNNING` 可终止。对其他状态调用相应操作时应返回 400，并保留原状态。

- **制定理由**。取消撤销尚未分配的任务，终止用于停止已分配或正在运行的任务。明确各动作的允许状态有助于处理拒绝和资源回收。
- **依据**。[取消与终止路由](../backend/app/api/routes/tasks.py#L89) · [取消测试](../backend/tests/test_tasks.py#L231) · [生命周期测试计划](test_plan.md#L123)
- **检查方式**。使用独立样本遍历任务状态。对可操作状态检查 `CANCELLED` 或 `TERMINATED`。对其余状态检查 HTTP 400 并核对状态和绑定未变。并发场景另按待补验清单执行。
- **当前验证状态**。已静态核对当前允许状态和错误分支。终止场景、取消与分配竞态、终止与启动竞态待补验。
- **团队评审状态**。待团队评审。

## RULE-012 限制运行中 GPU 的维护标记

**规则**。GPU 管理接口应拒绝把 `RUNNING` 卡直接标为 `MAINTENANCE` 或 `FAULTY`。两种修改分别验收为 HTTP 400，并核对原状态和任务绑定。

- **制定理由**。修改已运行的 GPU 状态会影响调度对可用性的判断。现有路由专门拒绝运行卡进入维护或故障。
- **依据**。[GPU 更新路由](../backend/app/api/routes/gpus.py#L39) · [两个拒绝用例](../backend/tests/test_gpus.py#L125) · [架构评审 AR-05](architecture_review.md#L132)
- **检查方式**。使待测 GPU 处于 `RUNNING` 并绑定一个任务，分别请求 `MAINTENANCE` 和 `FAULTY`。两次均核对 HTTP 400、GPU 状态仍为 `RUNNING`、`current_task_id` 与操作前相同。
- **当前验证状态**。已静态核对两条拒绝分支和既有响应断言。绑定保留和管理写入竞态待补验。
- **团队评审状态**。待团队评审。

## RULE-013 同步验证前后端接口契约

**规则**。改动任务或 GPU 接口时，同步回归前端实际使用的 `/tasks`、`/tasks/admin`、`/gpus`，以及列表的 `items` 和错误响应的 `detail`。接口路径或响应结构有变更时，同步更新消费者和契约用例。

- **制定理由**。Vue 页面直接读取当前路由和返回字段。接口变更单独发布会影响任务列表、GPU 列表和错误显示。
- **依据**。[路由注册](../backend/app/main.py#L39) · [前端 API 调用](../frontend/src/App.vue#L227) · [错误响应](../backend/app/utils/middleware.py#L25) · [API 测试](../backend/tests/test_tasks.py#L63)
- **检查方式**。后端执行任务、GPU 和错误响应相关回归。用浏览器操作提交和两类列表刷新，查看实际路径及列表 `items`。构造一项业务错误，核对返回的 `detail` 和页面反馈。
- **当前验证状态**。已静态核对直接路由、`items` 与 `detail` 的消费者。本次未运行 API 或页面回归。
- **团队评审状态**。待团队评审。

## 待补验与已登记的待确认事项

下表沿用现有 PRD、Epic 和风险记录，用于课程验收追踪。各项依赖和验收结果仍按对应来源确认。

| 事项 | 关联规则 | 待取得的证据或决策 |
| --- | --- | --- |
| MySQL 并发测试库保护 | RULE-002 | 验证 fixture 实际连接到隔离库，配置错误时在建表或删表前中止。库名保护的实现方案待评审。见 [R-02](risk_lisk.md#L40)。 |
| 100 路争用与失败回滚 | RULE-006 | 保留唯一绑定和单条分配记录的现有断言，补验其余 99 个任务保持 `QUEUED`，并注入提交前异常核对事务回滚。见 [FR-12](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L77) 和 [Story 3-4](../_bmad-output/planning-artifacts/epics.md#story-3-4-验证分配事务和并发独占)。 |
| 取消、启动、终止与进程失联 | RULE-008、RULE-011 | 复验取消与分配的互斥结果、终止与启动竞争时的进程退出及逐卡释放。终止退回仅更新数据库或确认超时的场景，单独检查是否仍有活动进程。见 [FR-08](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L63)、[NFR-05](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L95) 和 [R-08](risk_lisk.md#L93)。 |
| 管理写入与分配竞争 | RULE-006、RULE-012 | 复验管理接口修改已绑定 GPU 为 `IDLE` 或维护操作与调度竞争时的任务绑定和卡状态。见 [FR-11](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L71) 和 [AR-05](architecture_review.md#L132)。 |
| 停机、重启及真实 GPU 映射 | RULE-003、RULE-007、RULE-008 | 复验服务正常和异常退出后的任务及 GPU 对账，确认目标部署平台，实机核对单卡和双卡任务所见设备 UUID、数量与实际占用。见 [NFR-05、NFR-06](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L95) 和 [O-03](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L112)。 |
| 接口口径、角色与状态推送 | RULE-009、RULE-011、RULE-013 | 当前接口保留既有状态边界。并发失败的 HTTP 409、接口版本前缀和取消边界等待 O-01、O-02 决策。角色授权和 WebSocket 按既有计划验收。见 [FR-06](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L56)、[FR-13](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L83) 和 [待确认决策](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L106)。 |
| 参数上限、测量环境与实际容量 | RULE-005、RULE-009 | 确认目标 GPU 数量和性能测量口径。若纳入 64 卡实配，需覆盖全部 GPU ID 的持久化与释放。见 [O-05](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L114)。 |
