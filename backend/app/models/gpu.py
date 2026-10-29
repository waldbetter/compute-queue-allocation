import enum

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GpuStatus(str, enum.Enum):
    IDLE = "IDLE"
    ALLOCATED = "ALLOCATED"
    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    FAULTY = "FAULTY"


class GPU(Base):
    __tablename__ = "gpus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    total_memory_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GpuStatus] = mapped_column(
        Enum(GpuStatus, name="gpu_status"),
        default=GpuStatus.IDLE,
        nullable=False,
    )
    current_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_heartbeat: Mapped[DateTime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)