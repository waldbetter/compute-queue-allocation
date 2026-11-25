# 项目 AI 使用记录

整理日期 2026-11-25 · 核对基线 `092db91`

本记录覆盖 GPU 算力队列分配系统中有据可查的 AI 辅助工作。当前 Codex 会话用于补齐课程交付文档。早期开发只记录项目材料能够印证的范围，其余信息由参与成员补充。

## 工具与 BMAD 版本

| 工具或配置 | 可确认的使用范围 | 证据与待补充内容 |
| --- | --- | --- |
| OpenAI Codex | 本会话实际用于读取源码和 Git 历史、整理需求与验收追溯、编写项目规则和课程文档、核对编号与引用。 | 来自本会话用户请求、助手操作及产物。实际模型为`GPT-6.2 Sol`。 |
| BMAD Method `6.12.4` | 当前工作区安装清单中，安装版本及内置 `core`、`bmm` 模块版本均为 `6.12.4`。本会话使用下节列出的 Skills。 | Git 基线 `092db91` 的安装清单也记录 `6.12.4`。基线配置列出 Trae，当前工作区另列 Codex。通过 `git show 092db91:_bmad/_config/manifest.yaml` 可复核基线。 [当前 BMAD 安装清单](../_bmad/_config/manifest.yaml) |
| Trae IDE | 项目 SPEC 将 Trae 记为 Windows 开发环境，BMAD 安装清单包含 Trae 集成配置。 | Trae 内实际调用的 AI 功能、模型、Skills、成员和产物对应关系待补充。 [SPEC 开发环境约束](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md#L54) |
| 其他成员使用的 AI 工具 | 待补充。 | 待提供工具名称和版本、实际模型、使用环节及相关成果出处。 |

## 本会话调用的 Skills 与成果

| 环节 | 实际调用 | AI 参与内容与产物 | 人工审核情况 |
| --- | --- | --- | --- |
| 需求整理 | `bmad-prd` | 根据 SPEC、架构、源码和历史材料编写 13 项 FR、7 项 NFR、业务约束及验收条件，保留已实现、计划和待验证的边界。 [PRD](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md) · [BMAD 决策日志](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/.memlog.md) | 用户指定中文、沿用编号及文件边界。优先级是文档中的建议，PRD 的未决事项和团队签核状态待补充。 |
| PRD 文档核对 | `bmad-review`（`structure`、`prose`） | 按 PRD 工作流做结构与措辞检查。本会话另进行了只读来源复核和验收清晰度审查，最后由 Codex 将修改落实到原 PRD。 [PRD](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md) · [核对与定稿记录](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/.memlog.md#L8) | 这一轮审阅由 AI 辅助完成。没有收到团队对 PRD 的逐项人工签核记录。 |
| Epic 与验收追溯 | `bmad-create-epics-and-stories` | 在既有 `epics.md` 内沿用 29 个 Story 编号，新增 2 个 Story，建立 49 条 Given–When–Then 验收标准及需求、Story 与用例的追溯。校验编号、覆盖和链接。 [Epic 与用户故事](../_bmad-output/planning-artifacts/epics.md) | 用户给出复用范围和验收格式。正式 Story 排期、缺口补充及用例执行结果待补充。 |
| 项目规则 | `bmad-project-context` | 基于源码、架构和测试提出 13 条规则，展示原生规则块供确认。经允许写入后，将同一规则正文映射至课程交付文档，并补上依据和验证方法。 [AGENTS.md](../AGENTS.md) · [课程版项目规则](project-context.md) | 用户明确同意以**待团队评审**状态写入根目录规则，并要求同时交付课程版。两份文件的规则正文已逐条校验。团队对规则的最终评审待补充。 |
| AI 建议否决证据整理 | Codex，未调用专项 BMAD Skill | 检查可见 Git 分支、架构取舍和实验材料，整理 6 条待核实线索，并记录 AI 原文、团队否决与确认信息的缺口。 [否决决策日志](decision-log.md) | 当前可计入课程的记录为 0 条。全组贡献和原始确认材料待补充。 |
| AI 使用归档 | Codex，未调用专项 BMAD Skill | 整理版本、实际调用、产物、审核过程和局限性，汇总为本文件。 | 记录依据为当前会话和可回查的项目材料。其他成员记录及全组确认待补充。 |

## 早期项目记录

- Git 提交 `3310d38` 归档了 BMAD 规划材料，包括 SPEC、架构、Story 清单和 Sprint 状态。各文件对应的原始对话、具体 Skill、模型及参与者待补充。保留旧版材料作为历史来源。 [SPEC](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md) · [架构文档](../_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md) · [历史 Story 清单](../_bmad-output/specs/spec-gpu-queue-allocation/stories.yaml)
- 实验 A 的计划与数据将 Story 3-6「任务取消与终止」记为走 BMAD 完整规划的实验组，将 Story 3-9「多卡同型号分配」记为口述需求对照组。两条开发投入为回忆估算，测试条目有记录但随附材料中没有原始运行日志。原始记录可用 `git show 1b47e53:experiments/experiment-a-plan.md` 和 `git show 4aaa42b:experiments/experiment-a-raw.csv` 查看。实际使用的 AI 工具、Skills 与代码贡献范围待成员补充。
- SPEC 设有「组内确认」章节，架构评审记录标注测试与架构验证负责人 B，并记录可靠性问题和验收限制。相关材料可回查方案及评审结论。原始参与名单、逐项讨论及确认材料待补充。 [SPEC 决策记录](../_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md#L84) · [架构评审](architecture_review.md#L124)

## 审核方式与局限性

1. 先由人工给出文档范围、保留的旧成果和验收格式。Codex 对照源码、规格、测试计划与历史材料编写，标记设计和实现有差异的条目。例如，架构规划 WebSocket，当前页面使用轮询，PRD 将推送列为计划。 [PRD FR-06](../_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md#L56) · [当前前端轮询](../frontend/src/App.vue#L350)
2. 文档校验覆盖编号、需求追溯、引用及规则正文的一致性。规则发布仍待团队评审。PRD、Epic 的定稿状态记录文档流程，产品验收结论需要对应运行证据。 [项目规则验证状态](project-context.md) · [测试计划](test_plan.md)
3. 本会话的课程文档任务未修改业务代码，也未运行项目测试。历史测试摘要来自多个执行批次，MySQL 行锁、真实 GPU 映射和进程清理仍按项目计划补验。实验 A 的回忆估算与缺失日志限制了对效率、质量或 AI 单独贡献的判断。 [历史测试摘要](../evidence/screenshots/test-logs/historical-results.md) · [已登记补验事项](project-context.md#L137)
4. 安装清单只能核对版本和配置。历史 Git 提交、页面截图与产物可核对交付内容，历史工具调用、AI 原话和团队审批仍需具体过程记录。 [否决决策日志](decision-log.md)

## 其他成员待补充

| 待补内容 | 可用于复核的材料 |
| --- | --- |
| 成员及日期、实际工具、客户端或模型版本、各自使用的 BMAD 版本与 Skills | 会话导出、调用记录或当时的安装清单 |
| AI 参与的 Story 或工作环节、生成内容、人工修改与最终产物 | 会话摘录和文件版本、提交或 PR |
| 审核人、确认日期、决定及理由 | 有出处的评审记录、会议纪要或对话 |
| 实际运行的验证及其限制 | 测试命令、平台、时间、结果和原始日志 |
