from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.mysql.database import get_db
from app.models.gpu import GPU, GpuStatus
from app.schemas.gpu import GpuCreate, GpuListResponse, GpuResponse, GpuUpdate
from app.utils.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/gpus", tags=["gpus"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@router.post("", response_model=GpuResponse, status_code=201)
async def create_gpu(
    payload: GpuCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GpuResponse:
    gpu = GPU(
        name=payload.name,
        model=payload.model,
        total_memory_mb=payload.total_memory_mb,
    )
    db.add(gpu)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(f"GPU name '{payload.name}' already exists")
    await db.refresh(gpu)
    return gpu


@router.patch("/{gpu_id}", response_model=GpuResponse)
async def update_gpu(
    gpu_id: int,
    payload: GpuUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GpuResponse:
    result = await db.execute(select(GPU).where(GPU.id == gpu_id))
    gpu = result.scalar_one_or_none()
    if gpu is None:
        raise NotFoundError(f"GPU {gpu_id} not found")

    fields = payload.model_fields_set
    new_status = payload.status if "status" in fields else None

    if new_status is not None:
        if gpu.status == GpuStatus.RUNNING and new_status in (
            GpuStatus.MAINTENANCE,
            GpuStatus.FAULTY,
        ):
            raise ValidationError(
                "GPU is running a task; terminate it first before marking MAINTENANCE or FAULTY"
            )
        gpu.status = new_status

    if "notes" in fields:
        gpu.notes = payload.notes

    await db.commit()
    await db.refresh(gpu)
    return gpu


@router.get("", response_model=GpuListResponse)
async def list_gpus(
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[GpuStatus | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> GpuListResponse:
    stmt = select(GPU)
    if status is not None:
        stmt = stmt.where(GPU.status == status)
    stmt = stmt.order_by(GPU.id.asc())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(items_stmt)).scalars().all()

    return GpuListResponse(
        items=rows,
        total=total,
        page=page,
        page_size=page_size,
    )