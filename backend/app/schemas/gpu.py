from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.gpu import GpuStatus


class GpuCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=64)
    total_memory_mb: int = Field(..., gt=0)


class GpuUpdate(BaseModel):
    status: GpuStatus | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=256)


class GpuResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model: str
    total_memory_mb: int
    status: GpuStatus
    current_task_id: int | None
    last_heartbeat: datetime | None
    notes: str | None
    created_at: datetime


class GpuListResponse(BaseModel):
    items: list[GpuResponse]
    total: int
    page: int
    page_size: int