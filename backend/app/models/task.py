import enum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaskStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    gpu_model_preference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        default=TaskStatus.QUEUED,
        nullable=False,
    )
    allocated_gpu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allocated_gpu_ids: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)