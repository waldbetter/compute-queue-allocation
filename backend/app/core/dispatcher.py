import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus

logger = logging.getLogger("dispatcher")


class Dispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        interval: float = 0.5,
        max_passes_per_tick: int = 5,
    ):
        self._session_factory = session_factory
        self._interval = interval
        self._max_passes_per_tick = max_passes_per_tick
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="dispatcher")
        logger.info("Dispatcher started (interval=%.3fs)", self._interval)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Dispatcher stopped")

    async def run_once(self) -> int:
        allocated = 0
        async with self._session_factory() as db:
            for _ in range(self._max_passes_per_tick):
                ok = await self.try_allocate_gpu(db)
                if not ok:
                    break
                allocated += 1
        return allocated

    async def try_allocate_gpu(self, db: AsyncSession) -> bool:
        """
        AD-1: 完整事务内分配 GPU。
        支持多卡任务（同型号组队）：任务要求 N 张卡时，必须一次性凑齐
        N 张同型号空闲卡并全部 FOR UPDATE 锁定，否则保持排队（队首阻塞策略）。
        返回 True 表示成功分配了一对 (task, gpus)；False 表示本轮无可分配资源。
        """

        queued_task = (await db.execute(
            select(Task)
            .where(Task.status == TaskStatus.QUEUED)
            .order_by(Task.submitted_at.asc(), Task.id.asc())
            .limit(1)
            .with_for_update()
        )).scalar_one_or_none()

        if queued_task is None:
            return False

        gpu_count = max(1, queued_task.gpu_count or 1)

        if gpu_count > 1:
            # 多卡：先确定目标型号（任务 preference 优先，否则以最早空闲卡的型号为基准），
            # 再一次性锁住 N 张同型号空闲卡
            base = (await db.execute(
                select(GPU)
                .where(GPU.status == GpuStatus.IDLE)
                .order_by(GPU.id.asc())
                .limit(1)
            )).scalar_one_or_none()
            if base is None:
                return False
            target_model = queued_task.gpu_model_preference or base.model
            gpus = (await db.execute(
                select(GPU)
                .where(
                    GPU.status == GpuStatus.IDLE,
                    GPU.model == target_model,
                )
                .order_by(GPU.id.asc())
                .limit(gpu_count)
                .with_for_update()
            )).scalars().all()
            if len(gpus) < gpu_count:
                # 凑不齐同型号 N 张卡：保持排队，等下一轮（队首阻塞，保 FCFS 语义）
                return False
        else:
            gpus = (await db.execute(
                select(GPU)
                .where(GPU.status == GpuStatus.IDLE)
                .order_by(GPU.id.asc())
                .limit(1)
                .with_for_update()
            )).scalars().all()
            if not gpus:
                return False

        for gpu in gpus:
            gpu.status = GpuStatus.ALLOCATED
            gpu.current_task_id = queued_task.id
            db.add(AllocationLog(
                task_id=queued_task.id,
                gpu_id=gpu.id,
                action=AllocationAction.ALLOCATE,
                actor_user_id=None,
                notes=f"dispatcher: FCFS allocation ({gpu_count} GPU)",
            ))

        queued_task.status = TaskStatus.PENDING
        queued_task.allocated_gpu_id = gpus[0].id
        queued_task.allocated_gpu_ids = ",".join(str(g.id) for g in gpus)

        await db.commit()
        logger.info(
            "Allocated GPU(s) %s to task %s (user=%s, count=%s)",
            queued_task.allocated_gpu_ids, queued_task.id,
            queued_task.user_id, gpu_count,
        )
        return True

    async def _run_loop(self) -> None:
        logger.info("Dispatcher loop running")
        while not self._stop_event.is_set():
            try:
                allocated = await self.run_once()
                if allocated > 0:
                    logger.debug("Allocated %d pair(s) this tick", allocated)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Dispatcher tick error: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
            except asyncio.TimeoutError:
                pass