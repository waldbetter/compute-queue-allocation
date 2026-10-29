from typing import Annotated

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.mysql.database import get_db
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskListResponse, TaskResponse
from app.utils.errors import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger("tasks")

router = APIRouter(prefix="/tasks", tags=["tasks"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: int = 1,
) -> TaskResponse:
    task = Task(
        user_id=user_id,
        name=payload.name,
        command=payload.command,
        gpu_count=payload.gpu_count,
        gpu_model_preference=payload.gpu_model_preference,
        estimated_duration_sec=payload.estimated_duration_sec,
        status=TaskStatus.QUEUED,
    )
    db.add(task)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(f"user_id {user_id} does not exist")
    await db.refresh(task)

    queue_position = await _compute_queue_position(db, task.submitted_at, task.id)
    return _build_task_response(task, queue_position)


@router.get("/admin", response_model=TaskListResponse)
async def list_all_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> TaskListResponse:
    stmt = select(Task).order_by(Task.submitted_at.desc())
    return await _paginate_tasks(db, stmt, page, page_size)


@router.get("", response_model=TaskListResponse)
async def list_my_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    user_id: int = 1,
) -> TaskListResponse:
    stmt = select(Task).where(Task.user_id == user_id).order_by(Task.submitted_at.desc())
    return await _paginate_tasks(db, stmt, page, page_size)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Task {task_id} not found")

    pos = await _compute_queue_position(db, task.submitted_at, task.id) \
        if task.status in (TaskStatus.QUEUED, TaskStatus.PENDING, TaskStatus.RUNNING) else None
    return _build_task_response(task, pos)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_queued_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Task {task_id} not found")

    if task.status != TaskStatus.QUEUED:
        raise ValidationError(
            f"Only QUEUED tasks can be cancelled; current status is {task.status.value}"
        )

    task.status = TaskStatus.CANCELLED
    task.finished_at = datetime.now()
    await db.commit()
    await db.refresh(task)

    return _build_task_response(task, None)


@router.post("/{task_id}/terminate", response_model=TaskResponse)
async def terminate_task(
    request: Request,
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Task {task_id} not found")

    if task.status == TaskStatus.QUEUED:
        raise ValidationError(
            f"QUEUED tasks cannot be terminated; use POST /tasks/{task_id}/cancel instead"
        )

    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TERMINATED):
        raise ValidationError(
            f"Task is already in terminal state: {task.status.value}"
        )

    if task.status == TaskStatus.RUNNING:
        await _terminate_running(request, db, task)
    elif task.status == TaskStatus.PENDING:
        # 带行锁重读：PENDING 可能正被 ProcessManager 提升为 RUNNING，直接覆盖会造成竞态
        row = (await db.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Task {task_id} not found")
        if row.status == TaskStatus.PENDING:
            await _terminate_in_db(
                db, row, "admin: pending task terminated, GPU reclaimed"
            )
        elif row.status == TaskStatus.RUNNING:
            await _terminate_running(request, db, row)
        else:
            raise ValidationError(
                f"Task state changed concurrently to {row.status.value}; please retry"
            )

    await db.refresh(task)
    return _build_task_response(task, None)


async def _terminate_running(
    request: Request,
    db: AsyncSession,
    task: Task,
) -> None:
    pm = getattr(request.app.state, "process_manager", None)
    if pm is not None and pm.is_active(task.id):
        ok = await pm.terminate_task(task.id)
        if not ok:
            logger.warning(
                "ProcessManager returned False for active task %s, falling back to DB-only termination",
                task.id,
            )
            await _terminate_in_db(db, task, "admin: task terminated (DB-only fallback)")
    else:
        await _terminate_in_db(db, task, "admin: task terminated (DB-only fallback)")


async def _terminate_in_db(db: AsyncSession, task: Task, notes: str) -> None:
    now = datetime.now()
    task.status = TaskStatus.TERMINATED
    task.finished_at = now
    task.exit_code = -9

    if task.allocated_gpu_id is not None:
        # 按 current_task_id 释放该任务占用的全部 GPU（多卡）
        gpus = (await db.execute(
            select(GPU).where(GPU.current_task_id == task.id)
        )).scalars().all()
        for gpu in gpus:
            gpu.status = GpuStatus.IDLE
            gpu.current_task_id = None
            db.add(AllocationLog(
                task_id=task.id,
                gpu_id=gpu.id,
                action=AllocationAction.RELEASE,
                actor_user_id=None,
                notes=notes,
            ))

    await db.commit()


async def _paginate_tasks(db, stmt, page, page_size) -> TaskListResponse:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    items_stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(items_stmt)).scalars().all()

    active_statuses = (TaskStatus.QUEUED, TaskStatus.PENDING, TaskStatus.RUNNING)
    positions: dict[int, int] = {}
    active_ids = [t.id for t in rows if t.status in active_statuses]
    for tid in active_ids:
        t = next((r for r in rows if r.id == tid), None)
        if t is not None and t.submitted_at is not None:
            positions[tid] = await _compute_queue_position(db, t.submitted_at, t.id)

    items = []
    for t in rows:
        items.append(TaskResponse(
            **t.__dict__,
            queue_position=positions.get(t.id),
        ))

    return TaskListResponse(items=items, total=total)


def _build_task_response(task: Task, queue_position: int | None) -> TaskResponse:
    return TaskResponse(**task.__dict__, queue_position=queue_position)


async def _compute_queue_position(db: AsyncSession, submitted_at, task_id: int) -> int:
    active_statuses = (TaskStatus.QUEUED, TaskStatus.PENDING, TaskStatus.RUNNING)
    count_stmt = select(func.count()).select_from(Task).where(
        Task.status.in_(active_statuses),
        Task.submitted_at < submitted_at,
    )
    earlier = (await db.execute(count_stmt)).scalar_one() or 0

    same_time_stmt = select(func.count()).select_from(Task).where(
        Task.status.in_(active_statuses),
        Task.submitted_at == submitted_at,
        Task.id <= task_id,
    )
    same_time = (await db.execute(same_time_stmt)).scalar_one() or 0

    return earlier + same_time