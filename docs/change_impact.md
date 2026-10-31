# compute-queue-allocation 需求/功能变更影响分析

- 日期：2026-10-31
- 负责人：B（测试与架构验证负责人）
- 依据：本次项目 ZIP 中的源码、README 和《测试与部署手册》
- 说明：仓库材料提到终止功能和多 GPU 功能的新增日期，但未提供完整、正式的需求变更单及变更前基线。因此本文件将其作为“项目文档记录的功能增量”分析，不虚构需求提出人、审批人或实际缺陷修复记录。

## 1. 变更概况

| 变更编号 | 项目文档记录的功能增量 | 记录日期 | 主要影响 | 当前判断 |
|---|---|---|---|---|
| CHG-01 | 增加任务终止能力；Windows 下使用 taskkill 终止进程树 | 2026-10-29 | Task API、ProcessManager、任务状态、GPU 回收、前端操作 | 源码可见实现，需验证异常进程路径 |
| CHG-02 | 增加多 GPU 同型号分配，支持 gpu_count 1–64 | 2026-10-29 | Task 模型/API、Dispatcher、ProcessManager、GPU 绑定、日志、前端展示 | 源码和多卡测试可见实现 |
| CHG-03 | 多卡任务按型号偏好匹配；资源不足时队首阻塞 | 2026-10-29（手册记录） | Dispatcher 调度规则、FCFS 行为、资源利用率 | 属于明确策略约束，需防止回归 |

## 2. CHG-01：任务终止与 Windows 进程树清理

### 2.1 变更内容
项目手册记录终止功能于 2026-10-29 实现。API 增加/提供 `POST /tasks/{id}/terminate`。ProcessManager 通过 `terminate_task()` 结束任务进程并释放 GPU。Windows 环境使用 `taskkill /F /T /PID`，避免仅杀父进程后遗留子进程。

### 2.2 受影响模块

| 模块/文件 | 影响说明 |
|---|---|
| `backend/app/api/routes/tasks.py` | 增加终止 API；区分 QUEUED、PENDING、RUNNING 和终态 |
| `backend/app/core/process_manager.py` | 增加进程树终止、活动进程映射管理和 GPU 释放 |
| `backend/app/models/task.py` | 使用 TERMINATED 终态、finished_at、exit_code |
| `backend/app/models/gpu.py` | 终止后将任务关联 GPU 置为 IDLE 并清空 current_task_id |
| `backend/app/models/allocation_log.py` | 终止时记录 RELEASE |
| 前端任务操作界面 | 需要展示终止入口和终止后的状态（需结合实际 UI 手工确认） |

### 2.3 主要风险
- PENDING 状态下，ProcessManager 可能正将任务提升为 RUNNING，因此接口通过行锁重读状态；需验证竞态。
- RUNNING 任务若不在 ProcessManager 内存活动映射中，路由会进入 DB-only fallback；必须验证操作系统进程是否真的结束。
- 服务异常重启后内存中的 PID 映射丢失，终止与恢复能力需要额外设计。
- Windows `taskkill` 的实际行为依赖进程权限、PID 有效性和进程树情况。

### 2.4 回归测试范围
- QUEUED 任务调用 terminate 应拒绝，并提示使用 cancel。
- PENDING 任务终止后应为 TERMINATED，所有已占 GPU 释放。
- RUNNING 任务终止后进程树应消失，任务为 TERMINATED，GPU 为 IDLE。
- 已处于 COMPLETED/FAILED/CANCELLED/TERMINATED 的任务重复终止应拒绝。
- 多卡 RUNNING 任务终止时应释放全部 GPU，逐卡写 RELEASE。
- ProcessManager 未记录活动进程时的 fallback 路径不得造成进程仍运行但 GPU 已释放。

### 2.5 当前状态
源码包含终止 API、`terminate_task()`、Windows taskkill 分支及数据库释放逻辑。历史测试输出显示 ProcessManager 基础测试曾通过，但本次 ZIP 的日志不能证明所有终止异常路径均已通过。状态：**实现可见，回归验证待补充**。

## 3. CHG-02：多 GPU 同型号分配

### 3.1 变更内容
项目手册记录多 GPU 功能于 2026-10-29 新增。Task 支持 `gpu_count`（1–64）和 `gpu_model_preference`；分配结果通过 `allocated_gpu_id` 与 `allocated_gpu_ids` 保存。多卡任务必须一次性获得 N 张同型号空闲 GPU。

### 3.2 受影响模块

| 模块/文件 | 影响说明 |
|---|---|
| `backend/app/models/task.py` | 新增/使用 gpu_count、gpu_model_preference、allocated_gpu_ids |
| `backend/app/schemas/task.py` | 请求参数校验与响应字段 |
| `backend/app/api/routes/tasks.py` | 创建任务时接收多卡参数 |
| `backend/app/core/dispatcher.py` | 选择同型号 GPU 并一次性锁定 |
| `backend/app/core/process_manager.py` | 根据 current_task_id 找到全部 GPU，注入多设备环境变量并批量释放 |
| `backend/app/models/allocation_log.py` | 每张 GPU 独立记录 ALLOCATE/RELEASE |
| 前端任务表单和列表 | 需要支持卡数/型号偏好输入和 GPU 列表展示 |

### 3.3 主要风险
- 只能同型号组合，跨型号混搭不支持。
- 凑不齐 N 张卡时任务保持 QUEUED。
- `allocated_gpu_ids` 使用逗号分隔字符串，后续扩展时需注意解析、排序和数据校验。
- ProcessManager 使用 GPU 数据库 ID 构造 `CUDA_VISIBLE_DEVICES`，需核验数据库 ID 是否等于物理设备索引。
- 多卡任务终止、失败和正常完成时必须释放全部 GPU，不能只释放 `allocated_gpu_id` 指向的第一张卡。

### 3.4 回归测试范围
- 2 张同型号空闲卡 + 1 个 gpu_count=2 任务：一次性分配成功。
- 目标型号不足 N 张：不允许部分占卡。
- 不同型号 GPU 不混合分配。
- 无型号偏好时按当前代码策略选择最早 ID 空闲 GPU 的型号。
- gpu_count=1 的旧行为保持不变。
- 多卡成功、失败、终止后所有 GPU 均释放。
- API 拒绝 0、负数、65 等非法 gpu_count，接受 1、2、8、64 等合法值。

### 3.5 当前状态
源码和 `backend/tests/test_multigpu.py` 已覆盖多卡分配、型号偏好、队首阻塞、ProcessManager 多卡释放和 API 参数范围。项目历史测试日志中记录过 67 项测试通过。状态：**主要实现和测试已存在，仍需在当前 Windows 环境重新执行并补充异常场景**。

## 4. CHG-03：多卡资源不足时的 FCFS 队首阻塞策略

### 4.1 变更/规则说明
手册说明：如果队首多卡任务无法凑齐同型号 GPU，Dispatcher 返回无可分配资源，后续单卡任务也不会越过队首。这是当前系统明确的 FCFS 语义，不应未经产品确认就当成调度缺陷修改。

### 4.2 影响范围
- Dispatcher 的队列处理策略。
- 任务等待时间和 GPU 利用率。
- 前端排队位置和用户对“GPU 空闲但任务未运行”的理解。
- 测试必须验证队首任务和队尾任务都保持 QUEUED。

### 4.3 回归测试
使用两张同型号 GPU：让其中一张处于占用状态；队首请求两张 GPU，队尾请求一张 GPU。执行 Dispatcher 后，队首和队尾都应保持 QUEUED，剩余一张空闲 GPU 不分配给队尾。

## 5. 变更影响矩阵

| 变更 | API | 数据模型 | Dispatcher | ProcessManager | 前端 | 测试重点 |
|---|---|---|---|---|---|---|
| CHG-01 任务终止 | 高 | 中 | 无直接改动 | 高 | 中 | 进程树、状态、GPU 释放 |
| CHG-02 多 GPU | 中 | 高 | 高 | 高 | 高 | 同型号一次性分配、批量释放 |
| CHG-03 队首阻塞 | 无 | 无 | 高 | 无 | 中 | FCFS 与等待行为 |

## 6. 需求变更管理建议

后续每次需求变更应补齐以下信息：
1. 变更单编号、提出人、提出日期和审批人。
2. 变更前行为、变更后行为和验收标准。
3. 受影响模块、数据字段、API 和 UI。
4. 风险分析、兼容性和数据库迁移方案。
5. 单元测试、集成测试、回归测试和手工验收结果。
6. 关联代码提交/PR、缺陷编号和测试证据。

## 7. 尚缺资料

本次上传内容没有提供正式需求变更单、变更审批记录或完整的变更前版本验收基线。因此：
- CHG-01/02/03 是根据项目手册中的功能记录和源码进行的影响分析；
- 不推断具体提出人、审批人或实际业务原因；
- 若课程要求严格的“需求变更流程”，需要团队补充真实的变更记录。
