# API Contracts

所有 API 前缀 `/api/v1`。错误响应统一格式：`{"code": 非0, "data": null, "message": "..."}`

## Tasks

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | /tasks | member | 提交任务；gpu_count 1-N（多卡限同型号，上限 64）；成功返回 task_id + queue_position |
| GET | /tasks | member | 当前用户的任务列表 |
| GET | /tasks/admin | admin | 全部任务列表 |
| GET | /tasks/{id} | member+owner / admin | 任务详情（含 queue_position） |
| POST | /tasks/{id}/cancel | member+owner | 仅 QUEUED/PENDING 状态可取消 |
| POST | /tasks/{id}/terminate | admin | 任意状态可终止 |

### POST /tasks

Request body:
```json
{
  "name": "resnet50-train-v1",
  "command": "python train.py --model resnet50 --epochs 30",
  "gpu_count": 2,
  "gpu_model_preference": "A100",
  "estimated_duration_sec": 7200
}
```

> `gpu_count`：1-N（上限 64）。多卡任务将一次性分配 N 张**同型号**空闲卡（型号取 `gpu_model_preference`，未填则以最早空闲卡型号为基准）；凑不齐则保持排队等待，不做跨型号混搭。

Response 201:
```json
{
  "code": 0,
  "data": {
    "task_id": 42,
    "status": "QUEUED",
    "queue_position": 3
  }
}
```

Error 422 - gpu_count 校验失败（<1 或 >64）:
```json
{"code": 422, "data": null, "message": "gpu_count 必须在 1-64 之间"}
```

> 注（2026-10-29）：实际响应为完整任务对象（含 `allocated_gpu_id` / `allocated_gpu_ids`，分配后非空；多卡任务 `allocated_gpu_ids` 为逗号分隔串，如 `"1,2"`）。

## GPUs

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | /gpus | member | GPU 列表 |
| POST | /gpus | admin | 登记新卡 |
| GET | /gpus/{id} | member | 详情 |
| PATCH | /gpus/{id} | admin | 更新状态（含 MAINTENANCE/FAULTY 标记） |

### POST /gpus

```json
{"name": "node01-gpu0", "model": "RTX 3090", "total_memory_mb": 24576}
```

### PATCH /gpus/{id}

```json
{"status": "MAINTENANCE", "notes": "需要升级驱动"}
```

Error 400 - RUNNING 中禁止标记维护:
```json
{"code": 400, "data": null, "message": "GPU 正在运行任务，需先终止后再标记维护"}
```

## Users

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | /users/me | 已登录 | 当前用户信息 |
| POST | /users | admin | 创建测试用户（MVP 简化） |

### POST /users

```json
{"username": "alice", "role": "member"}
```

## WebSocket — /ws/events

客户端连接后立即收到快照：
```json
{
  "event": "snapshot",
  "timestamp": 1735296000000,
  "payload": {
    "tasks": [...],
    "gpus": [...]
  }
}
```

后续推送事件：

| event | payload |
|-------|---------|
| task:created | `{task_id, status, queue_position}` |
| task:status_changed | `{task_id, old_status, new_status, queue_position?}` |
| task:cancelled | `{task_id}` |
| task:terminated | `{task_id}` |
| gpu:status_changed | `{gpu_id, old_status, new_status}` |
| queue:reordered | `[{task_id, queue_position}]` |