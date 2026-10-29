from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskStatus


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    command: str = Field(..., min_length=1)
    gpu_count: int = Field(default=1, ge=1, le=64)
    gpu_model_preference: str | None = Field(default=None, max_length=64)
    estimated_duration_sec: int | None = Field(default=None, gt=0)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    command: str
    gpu_count: int
    gpu_model_preference: str | None
    estimated_duration_sec: int | None
    status: TaskStatus
    allocated_gpu_id: int | None
    allocated_gpu_ids: str | None
    submitted_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    notes: str | None
    queue_position: int | None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int