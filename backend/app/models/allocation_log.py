import enum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AllocationAction(str, enum.Enum):
    ALLOCATE = "ALLOCATE"
    RELEASE = "RELEASE"
    TERMINATE = "TERMINATE"
    MAINTENANCE_SET = "MAINTENANCE_SET"
    MAINTENANCE_CLEAR = "MAINTENANCE_CLEAR"


class AllocationLog(Base):
    __tablename__ = "allocation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[AllocationAction] = mapped_column(
        Enum(AllocationAction, name="alloc_action"),
        nullable=False,
    )
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)