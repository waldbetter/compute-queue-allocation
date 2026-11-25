# AI 建议否决决策日志

整理日期 2026-11-25 · 工作区源码基线 `092db91`

**课程可计入记录 0 / 5，缺 5 条。** 下列 6 条为待核实线索。现有资料能说明部分方案取舍、实现或验证范围。AI 建议原文、团队明确否决及人工确认之间的关联仍缺证据。全组共同贡献的覆盖情况也待核实。

## 证据范围与计入条件

- 已查阅当前 SPEC、架构、PRD、Epic、变更分析、测试计划、演示证据与历史测试摘要。Git 历史核对包含本地可见分支、远端跟踪分支、提交说明及文件变更，另查看 `origin/d/experiment-report` 中的实验计划 `1b47e53:experiments/experiment-a-plan.md` 和实验数据 `4aaa42b:experiments/experiment-a-raw.csv`。未能获取远端 PR 或 Issue 的讨论内容。
- 计入一条课程记录需能回查同一决策的 AI 建议原文或可靠摘录、团队明确否决及理由、最终方案、关联需求、验证依据和人工确认。多个材料可共同证明一条决策。提交作者只能说明提交出处，评审参与者和共同贡献以实际记录为准。
- 验证依据区分源码、已有用例、演示、历史执行与待执行验证。历史摘要中不同批次有不同结果，本次未运行测试。 [历史测试摘要](../evidence/screenshots/test-logs/historical-results.md)

## 待核实决策线索

### DEC-001 并发测试使用本机 MySQL

- **关联需求**。CAP-6、FR-12、Story 3-4、RULE-002。
- **AI 建议线索**。旧 Story 3-4 写有使用 Testcontainers 启动一次性 MySQL 的方案。AI 来源和原始会话待补。
- **否决理由证据**。架构 Deferred 表记载直接使用本机 MySQL 可减少外部依赖，并将多人并行开发需要隔离列为重访条件。未找到团队讨论中的原话。
- **最终方案**。SPEC Q2 记载通过 `DATABASE_URL` 配置应用直连本机 MySQL，MVP 不引入 Testcontainers。当前并发 fixture 另用固定连接设置，并执行建表和删表。
- **验证依据**。用现有 fixture 核对连接路径。并发验收仍需专用可丢弃库和库名保护，本次未执行。 [旧 Story 3-4](../_bmad-output/specs/spec-gpu-queue-allocation/stories.yaml#L128) · [SPEC Q2](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md#L87) · [架构 Deferred](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L222) · [MySQL fixture](../backend/tests/test_dispatcher_concurrency.py#L39) · [测试计划](test_plan.md#L69)
- **人工确认状态**。SPEC 节标题标为组内确认，可定位选型结论。AI 提议者、否决过程和确认人待补，未计入。

### DEC-002 GPU 分配采用悲观行锁

- **关联需求**。CAP-2、CAP-6、FR-12、Story 3-4、RULE-006。
- **AI 建议线索**。架构 Deferred 表列出以带 `status='IDLE'` 条件的更新做乐观锁。AI 来源待补。
- **否决理由证据**。架构文档记载乐观锁需冲突重试，悲观锁适合作为 MVP 可靠性基线，请求量上升时再重访。否决发言者及讨论记录待补。
- **最终方案**。AD-1 采用 MySQL 行锁，调度器在一次事务中更新任务、GPU 绑定和逐卡日志。Git 提交 `2a04f45` 记录调度器及进程管理实现。
- **验证依据**。源码可见 `with_for_update()` 和一次提交。100 路已有单绑定及单日志断言，其余 99 个任务仍为 `QUEUED` 与异常回滚待补验。 [架构 AD-1](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L41) · [架构 Deferred](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L221) · [调度器](../backend/app/core/dispatcher.py#L58) · [100 路用例](../backend/tests/test_dispatcher_concurrency.py#L216)
- **人工确认状态**。架构及代码可回查。确认人、日期及是否为对 AI 建议的明确否决待补，未计入。

### DEC-003 任务执行暂不引入 Docker

- **关联需求**。CAP-2、FR-04、BC-01、BC-04、Story 3-5。
- **AI 建议线索**。架构 Deferred 表列出 Docker 容器化执行。未找到原始 AI 建议。
- **否决理由证据**。架构文档说明本机 `subprocess` 启动简单，出现环境隔离或资源限制需求时再考虑容器。团队讨论及明确否决待补。
- **最终方案**。在单机后端使用本地子进程执行任务。Git 提交 `2a04f45` 可定位进程管理实现。
- **验证依据**。源码使用 `asyncio.create_subprocess_exec`，已有启动、成功退出、非零退出和启动失败用例。此次未执行。 [架构 Deferred](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L224) · [子进程启动](../backend/app/core/process_manager.py#L222) · [进程管理测试](../backend/tests/test_process_manager.py#L51)
- **人工确认状态**。可核对架构取舍和实际实现。否决经过及人工确认待补，未计入。

### DEC-004 调度保留严格 FCFS

- **关联需求**。CAP-2、FR-02、FR-03、BC-02、Story 3-3、Story 3-9。
- **AI 建议线索**。架构 Deferred 表分别列出公平份额和 priority 字段参与排序。当前合并为一条调度取舍线索，AI 来源待补。
- **否决理由证据**。架构文档将 FCFS 作为争议较小的初版策略。ADR-8 记录多卡不足时阻塞队首的利用率代价。团队讨论中对备选方案的实际否决理由待补。
- **最终方案**。调度仅按提交时间和任务 ID 取队首。队首多卡资源不足时保持排队。Git 提交 `2a04f45` 可定位实现。
- **验证依据**。已有调度顺序以及队首多卡阻塞测试代码。测试计划列有同时间排序及队首阻塞检查，本次未执行。 [架构 Deferred](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L223) · [ADR-8](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L232) · [FCFS 用例](../backend/tests/test_dispatcher.py#L124) · [多卡阻塞用例](../backend/tests/test_multigpu.py#L140)
- **人工确认状态**。业务规则和设计取舍有记录。哪项备选由 AI 提出、团队如何否决及谁确认待补，未计入。

### DEC-005 保留手动终止，延后任务自动超时

- **关联需求**。CAP-4、FR-08、BC-05、Story 3-6。
- **AI 建议线索**。SPEC Q5 和架构 Deferred 表记录任务运行超时自动终止的选项。原始建议与 AI 来源待补。
- **否决理由证据**。架构文档说明管理员手动终止可满足 MVP，长时间僵尸任务积累时再重访。团队否决过程待补。
- **最终方案**。保留手动终止接口与进程回收路径，运行任务不设自动超时。Git 提交 `2a04f45` 可定位终止实现。
- **验证依据**。可核对手动终止代码、手册场景和变更分析。运行进程失联、进程树清理及资源回收的一致性仍需补验。 [SPEC Q5](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md#L90) · [架构 Deferred](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md#L226) · [终止路由](../backend/app/api/routes/tasks.py#L112) · [变更 CHG-01](change_impact.md#L16)
- **人工确认状态**。SPEC 将 Q5 列在组内确认章节并标注为原有条目。未找到否决原话、确认人或 AI 建议来源，未计入。

### DEC-006 前端采用 Element Plus，MVP 暂不引入 Tailwind

- **关联需求**。CAP-1、CAP-3、CAP-5、FR-01、FR-05、FR-09、Story 1-5。
- **AI 建议线索**。SPEC Q3 记录 MVP 不考虑 Tailwind。未找到把 Tailwind 明确作为 AI 建议提出的原始材料。
- **否决理由证据**。Q3 记录了选型结果，未载明对 Tailwind 的否决理由，需由实际参与者提供原始讨论。
- **最终方案**。当前代码采用 Vue 3、Vite 和 Element Plus。SPEC 同时规划了 Pinia 和 Vue Router，当前依赖清单未列入这两项。Git 提交 `6847e8c) 可定位前端实现。
- **验证依据**。检查前端依赖与入口初始化，并可用现有截图核对页面呈现。本次未执行构建或浏览器测试。 [SPEC Q3](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md#L88) · [前端依赖](../frontend/package.json) · [前端入口](../frontend/src/main.js) · [概览截图](../evidence/screenshots/01-overview-13-gpu-idle.png)
- **人工确认状态**。SPEC 节标题标为组内确认。AI 来源、否决理由及实际确认人待补，未计入。

## 全组待补充事项

1. 每位成员从自己参与的设计、实现或验证中认领已有线索，或提交实际发生的新决策。登记贡献人及其负责的证据，核对全组覆盖。分工和参与人目前待补。
2. 提供可定位的 AI 原始回复、截图或会话导出。保留时间、提问上下文和建议内容。对每条建议补上团队在纪要、聊天或 PR 中明确否决的理由，以及最终方案和人工确认人、日期。
3. 给每个最终方案补上可回查的提交、PR 或文档版本，以及对应验证材料。记录已执行的命令、环境、日期和结果。缺原始日志时，保留现有记录的证据等级并标明待复验。
4. 优先回查 DEC-001 至 DEC-006 的原始会话与组内讨论。涉及同一决定的多份材料合并使用。能补齐证据的条目转为已确认，重复、来源不清或仅延期的条目保留其真实状态。按满足条件的独立决策重新统计，课程目标至少 5 条。

实验 A 的计划将 Story 3-6 标为 BMAD 实验组，将 Story 3-9 标为口述需求对照组。实验 CSV 含回忆估算和历史执行条目，未附原始运行日志。这些材料可用于回查实验分工和既有测试线索。确认 AI 建议是否曾被否决仍需原始会话和团队记录。多卡方案可用于追溯实现与验收。 [多卡变更 CHG-02](change_impact.md#L49) · [历史测试摘要](../evidence/screenshots/test-logs/historical-results.md)
