# GPU 队列分配系统

软件工程项目管理课程作业（BMAD 方法论实践）。系统用于实验室或课题组共享单台物理机的 GPU。成员在 Web 页面提交本机可执行的训练或推理命令，调度器按提交顺序分配 GPU，进程管理器执行命令、记录结果并回收资源。

## 核心功能

- **GPU 资源登记与状态管理**。通过 API 登记 GPU、修改状态和备注。页面展示卡的型号、显存、状态和当前任务，GPU 管理页当前为只读。
- **任务提交、FCFS 排队与自动分配**。调度器从 `QUEUED` 中按提交时间、任务 ID 升序取队首。GPU 分配使用 MySQL 行锁和事务，按卡记录分配及释放。
- **同型号多卡**。`gpu_count` 的 API 输入范围为 1–64。多卡任务需要一次性获得足量同型号空闲卡，未凑齐时队首继续排队。进程管理器注入 `CUDA_VISIBLE_DEVICES` 并批量回收。64 是参数上限，实际容量及物理 GPU 映射待实机验证。
- **任务取消、终止与查看**。可以取消 `QUEUED` 任务，终止 `PENDING` 或 `RUNNING` 任务。Overview、Tasks 和 GPUs 页面每 3 秒轮询，后端记录任务时间、退出码和运行日志。

当前版本面向本机课程演示。身份与角色授权、WebSocket 推送和 GPU 网页写操作仍在计划中。 [PRD](_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md) · [演示截图](evidence/screenshots/)

## 技术栈与环境依赖

| 项目 | 当前配置或要求 |
| --- | --- |
| 后端 | Python、FastAPI、Uvicorn、SQLAlchemy Async、aiomysql、Pydantic Settings。部署手册记录 Python 3.11+，历史测试使用过 Python 3.12.15。依赖以根目录 [requirements.txt](requirements.txt) 为准。 |
| 数据库 | MySQL 8.0+，开发手册采用本机实例。应用通过 `DATABASE_URL` 配置连接，库须先创建。 |
| 前端 | Vue 3、Vite 5、Element Plus。安装使用 Node.js 和 npm。锁定的 Vite 版本声明支持 Node.js 18 或 20 及以上。 [package.json](frontend/package.json) · [锁文件](frontend/package-lock.json) |
| 实机 GPU | 真实 CUDA 任务需要 NVIDIA GPU、兼容驱动及任务自身的 Python/CUDA 依赖。目标机的设备映射与进程退出行为待实机验证。 |
| 测试 | pytest、pytest-asyncio。SQLite 常规回归另需安装 `aiosqlite`，MySQL 并发验证使用专用隔离库。 |

以下以 **Windows PowerShell、本机单后端进程**演示。Linux 目标部署和完整安装、运行流程待在目标环境验证。 [测试与部署手册](docs/测试与部署手册.md) · [历史测试摘要](evidence/screenshots/test-logs/historical-results.md)

## 目录结构

```text
├── backend/
│   ├── app/              后端入口、API、调度器、进程管理和数据库模型
│   ├── scripts/          MySQL 表初始化脚本
│   └── tests/            SQLite 功能回归、MySQL 并发和多卡用例
├── frontend/             Vue 页面、Vite 配置和 npm 依赖
├── docs/                 部署、测试、评审和课程交付文档
├── evidence/screenshots/ 演示截图、历史测试摘要和记录模板
├── _bmad/                BMAD 安装清单、配置及流程脚本
├── _bmad-output/         SPEC、架构、PRD、Epic 和历史 Sprint 状态
├── AGENTS.md             BMAD 项目规则，待团队评审
└── requirements.txt      后端依赖
```

## 安装与运行

以下步骤以仓库根目录为各 PowerShell 窗口的起点。安装与启动入口已按源码和配置核对，端到端实测待验证。

### 1. 准备 MySQL

在本机 MySQL 客户端中创建开发库，并为应用准备有建表和读写权限的账号。

```sql
CREATE DATABASE IF NOT EXISTS gpu_queue DEFAULT CHARACTER SET utf8mb4;
```

在 `backend/.env` 中配置以下内容，运行前替换账号和密码占位符。后端从 `backend/` 启动以读取该文件。

```dotenv
DATABASE_URL=mysql+aiomysql://<账号>:<密码>@127.0.0.1:3306/gpu_queue
```

### 2. 安装后端依赖并初始化表

首次安装时创建根目录虚拟环境。已有可用 `.venv` 时从安装依赖的命令开始。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
Set-Location .\backend
..\.venv\Scripts\python.exe -m scripts.init_db
```

脚本建立 `users`、`gpus`、`tasks` 和 `allocation_log` 四张表。常规初始化省略会删表的 `--reset`。

首次演示还要准备**用户和 GPU 数据**。建表脚本不填充样例。当前页面提交任务时使用默认 `user_id=1`。先在开发库确认该用户是否存在。仅当库由上面的 ORM 脚本新建且没有该用户时，执行下方 `INSERT`。已有环境保留现有记录。

```sql
SELECT id FROM users WHERE id = 1;
INSERT INTO users (id, username, `role`, gpu_usage_sec)
VALUES (1, 'demo', 'MEMBER', 0);
```

### 3. 启动前后端

在上一步的 `backend/` 目录启动后端。Windows 下使用单进程，并省略 `--reload`。

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

另开 PowerShell，从仓库根目录进入前端。使用锁文件安装依赖并启动 Vite 开发服务器。

```powershell
Set-Location .\frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 [Web 界面](http://localhost:5173)、[API 文档](http://localhost:8000/docs) 或 [健康接口](http://localhost:8000/health)。页面当前使用 `http://localhost:8000` 访问 API。健康接口只返回服务存活状态，演示时还需检查数据库读写及任务调度。

在 API 文档用 `POST /gpus` 登记一张待用 GPU，填写唯一 `name`、登记型号 `model` 和正整数 `total_memory_mb`。随后从 Overview 提交短任务，在 Tasks 核对运行和结束状态，并在 GPUs 核对回收。可用手册里的 `cmd /c echo hello` 验证子进程和日志链路，真实 CUDA 验收另用实机任务。以 `backend/` 启动时，应用日志在 `backend/logs/app.log`，任务输出在 `backend/logs/<任务ID>.log`。 [操作指南与场景](docs/测试与部署手册.md#7-页面操作指南)

### 4. 运行常规测试

以下为 SQLite 常规回归，执行结果待验证。另开 PowerShell 并从仓库根目录运行。

```powershell
.\.venv\Scripts\python.exe -m pip install aiosqlite
Set-Location .\backend
$env:SKIP_MYSQL_TESTS = '1'
..\.venv\Scripts\python.exe -m pytest tests -v --tb=short
```

MySQL 并发用例有独立的数据库连接，且会建表和删表。执行前先核对专用可丢弃库、连接目标和库名保护，并停掉连接同一库的后端。并发结果独立于 SQLite 记录。 [测试计划与安全前置](docs/test_plan.md#42-测试执行原则) · [待补验事项](docs/project-context.md#待补验与已登记的待确认事项)

## BMAD 工作流程

本仓库的 BMAD 安装清单记录版本 `6.12.4`。早期材料包括 SPEC、架构和 Story，当前课程交付在这些材料和实际源码上补齐 PRD、验收追溯、项目规则及 AI 使用记录。 [安装清单](_bmad/_config/manifest.yaml) · [实际 AI 与 Skills 使用](docs/ai-usage.md)

1. **明确要求**。以 SPEC 和架构为设计依据，结合源码整理 PRD。保留已有 CAP 与需求编号，并标注尚未实现或待验证的内容。
2. **拆解和追溯**。在 Epic 文档中关联需求、Story、Given–When–Then 验收和已有用例。历史 Sprint 状态可回查，当前实现与待办边界以 PRD 和 Epic 为准。
3. **实现、验证和人工确认**。依据项目规则及测试计划执行验证，保留测试与演示证据。规则评审和有人工确认的 AI 取舍按各自记录追踪。

## 文档导航

| 要查什么 | 文档 |
| --- | --- |
| 需求范围、优先级与验收 | [PRD](_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md) · [SPEC](_bmad-output/specs/spec-gpu-queue-allocation/SPEC.md) |
| 架构、接口与状态 | [架构文档](_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md) · [历史 API 契约](_bmad-output/specs/spec-gpu-queue-allocation/api-contracts.md) · [状态机](_bmad-output/specs/spec-gpu-queue-allocation/state-machines.md) |
| 故事、测试追溯与历史排期 | [Epic 与 Story](_bmad-output/planning-artifacts/epics.md) · [历史 Sprint 状态](_bmad-output/implementation-artifacts/sprint-status.yaml) |
| 部署、测试与证据 | [测试与部署手册](docs/测试与部署手册.md) · [系统测试计划](docs/test_plan.md) · [演示及测试证据](evidence/screenshots/) |
| 评审、变更与风险 | [架构评审](docs/architecture_review.md) · [变更影响](docs/change_impact.md) · [风险清单](docs/risk_lisk.md) |
| 课程交付与 AI 使用 | [代理规则](AGENTS.md) · [项目规则与验证](docs/project-context.md) · [AI 决策日志](docs/decision-log.md) · [AI 使用记录](docs/ai-usage.md) |

## 团队分工

| 工作 | 现有记录 |
| --- | --- |
| 核心后端、前端与早期规划材料 | Git 将调度与执行、多卡、前端和早期 BMAD 规划相关提交记在 `waldbetter` 名下。代表提交为 `2a04f45`、`6847e8c` 和 `3310d38`。 |
| 实验开发与验证 | 实验 A 数据记载成员 A 参与 Story 3-6 和 3-9 的开发，成员 B 记录相应测试。开发工时为回忆估算。实验计划和原始数据的 Git 提交作者为 `Yyyyy116`（`1b47e53`、`4aaa42b`）。 [实验记录出处](docs/ai-usage.md#早期项目记录) |
| 测试与架构验证 | 项目文档标注成员 B 为负责人，范围包括测试计划、架构评审、风险和变更影响。相关文档由 `YuXinyu327` 提交（`67c8cda`）。 [测试计划](docs/test_plan.md) · [架构评审](docs/architecture_review.md) |
| 成员 C（需求与课程交付）`fantoonyebo` | 新增 [PRD](_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/prd.md)、[PRD 决策日志](_bmad-output/planning-artifacts/prds/prd-compute-queue-allocation-2026-11-25/.memlog.md)、[AGENTS.md](AGENTS.md)、[课程版项目规则](docs/project-context.md)、[AI 决策日志](docs/decision-log.md)和 [AI 使用记录](docs/ai-usage.md)。 |
| 其他成员与交付责任人 | 需求、课程材料、其他模块的正式负责人及成员代号与账号对应关系待团队确认。 |
