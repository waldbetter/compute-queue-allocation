# Database Schema — MySQL 8.0

## ER Diagram

```mermaid
erDiagram
    USERS ||--o{ TASKS : "submits"
    USERS ||--o{ ALLOCATION_LOG : "acts"
    GPUS }o--o{ TASKS : "allocated_to"
    TASKS ||--o{ ALLOCATION_LOG : "records"

    USERS {
        bigint_unsigned id PK
        varchar username UK
        varchar email NULL
        enum role "member | admin"
        bigint gpu_usage_sec "累计占用秒数"
        datetime created_at
    }
    GPUS {
        bigint_unsigned id PK
        varchar name UNIQUE
        varchar model
        int total_memory_mb
        enum status "IDLE|ALLOCATED|RUNNING|MAINTENANCE|FAULTY"
        bigint current_task_id FK NULL
        datetime last_heartbeat NULL
        datetime created_at
    }
    TASKS {
        bigint_unsigned id PK
        bigint user_id FK
        varchar name
        text command
        int gpu_count CHECK "gpu_count >= 1"
        varchar gpu_model_preference NULL
        int estimated_duration_sec NULL
        int priority "保留但 MVP 不排序"
        enum status "QUEUED|PENDING|RUNNING|COMPLETED|FAILED|CANCELLED|TERMINATED"
        bigint allocated_gpu_id FK NULL
        varchar allocated_gpu_ids NULL "逗号分隔多卡ID，如 1,2"
        datetime submitted_at
        datetime started_at NULL
        datetime finished_at NULL
        int exit_code NULL
        varchar log_path NULL
        text notes NULL
    }
    ALLOCATION_LOG {
        bigint_unsigned id PK
        bigint task_id FK NULL
        bigint gpu_id FK
        enum action "ALLOCATE|RELEASE|TERMINATE|MAINTENANCE_SET|MAINTENANCE_CLEAR"
        bigint actor_user_id FK NULL
        datetime timestamp
        varchar notes NULL
    }
```

## DDL

```sql
CREATE TABLE users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(128) NULL,
    role ENUM('member', 'admin') NOT NULL DEFAULT 'member',
    gpu_usage_sec BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE gpus (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    model VARCHAR(64) NOT NULL,
    total_memory_mb INT NOT NULL,
    status ENUM('IDLE', 'ALLOCATED', 'RUNNING', 'MAINTENANCE', 'FAULTY') NOT NULL DEFAULT 'IDLE',
    current_task_id BIGINT UNSIGNED NULL,
    last_heartbeat DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE tasks (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(128) NOT NULL,
    command TEXT NOT NULL,
    gpu_count INT NOT NULL DEFAULT 1,
    gpu_model_preference VARCHAR(64) NULL,
    estimated_duration_sec INT NULL,
    priority INT NOT NULL DEFAULT 0,
    status ENUM('QUEUED', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'TERMINATED') NOT NULL DEFAULT 'QUEUED',
    allocated_gpu_id BIGINT UNSIGNED NULL,
    allocated_gpu_ids VARCHAR(64) NULL,
    submitted_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    started_at DATETIME(3) NULL,
    finished_at DATETIME(3) NULL,
    exit_code INT NULL,
    log_path VARCHAR(256) NULL,
    notes TEXT NULL,
    INDEX idx_user_status (user_id, status),
    INDEX idx_status_submitted (status, submitted_at),
    CONSTRAINT fk_task_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE allocation_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NULL,
    gpu_id BIGINT UNSIGNED NOT NULL,
    action ENUM('ALLOCATE', 'RELEASE', 'TERMINATE', 'MAINTENANCE_SET', 'MAINTENANCE_CLEAR') NOT NULL,
    actor_user_id BIGINT UNSIGNED NULL,
    timestamp DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    notes VARCHAR(256) NULL,
    INDEX idx_gpu_time (gpu_id, timestamp),
    INDEX idx_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 关键查询

```sql
-- AD-1: 事务内分配 GPU 的完整模板
START TRANSACTION;
SELECT id FROM gpus WHERE status = 'IDLE' ORDER BY id ASC LIMIT 1 FOR UPDATE;
SELECT id FROM tasks WHERE status IN ('QUEUED', 'PENDING') ORDER BY submitted_at ASC, id ASC LIMIT 1 FOR UPDATE;
UPDATE gpus SET status = 'ALLOCATED', current_task_id = ? WHERE id = ?;
UPDATE tasks SET status = 'PENDING', allocated_gpu_id = ? WHERE id = ?;
INSERT INTO allocation_log (task_id, gpu_id, action, actor_user_id, notes) VALUES (?, ?, 'ALLOCATE', ?, 'dispatcher');
COMMIT;

-- AD-1b（2026-10-29 多卡）: 同型号多卡分配模板
-- 1) SELECT 队首 QUEUED 任务 FOR UPDATE（FCFS 排序）
-- 2) 任务 gpu_count=N 时：SELECT id FROM gpus WHERE status='IDLE' AND model=<目标型号>
--    ORDER BY id ASC LIMIT N FOR UPDATE（目标型号 = gpu_model_preference 或最早空闲卡型号）
-- 3) 若 COUNT < N 则不分配，保持排队（队首阻塞，保 FCFS）
-- 4) 逐卡 UPDATE gpus SET status='ALLOCATED', current_task_id=?；每卡 INSERT allocation_log('ALLOCATE')
-- 5) UPDATE tasks SET status='PENDING', allocated_gpu_id=<第一张卡>, allocated_gpu_ids='1,2,...'
-- 6) COMMIT

-- AD-2: 排队位置（不缓存 queue_position）
SELECT COUNT(*) + 1 FROM tasks
WHERE status IN ('QUEUED', 'PENDING')
  AND (submitted_at < ? OR (submitted_at = ? AND id < ?));
```