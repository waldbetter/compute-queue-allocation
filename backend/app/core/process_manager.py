import asyncio
import logging
import os
import shlex
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus

logger = logging.getLogger("process_manager")

LOG_DIR = "logs"


class ProcessManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        interval: float = 1.0,
    ):
        self._session_factory = session_factory
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._active_procs: dict[int, asyncio.subprocess.Process] = {}
        self._gpu_map: dict[int, int] = {}

    async def start(self) -> None:
        if self._task is not None:
            return
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="process-manager")
        logger.info("ProcessManager started (interval=%.3fs)", self._interval)

    async def stop(self) -> None:
        self._stop_event.set()
        for task_id, proc in list(self._active_procs.items()):
            try:
                proc.kill()
                await proc.wait()
                logger.warning("Killed orphan process task_id=%s", task_id)
            except Exception:
                pass
        self._active_procs.clear()
        self._gpu_map.clear()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("ProcessManager stopped")

    def is_active(self, task_id: int) -> bool:
        return task_id in self._active_procs

    async def terminate_task(self, task_id: int) -> bool:
        proc = self._active_procs.get(task_id)
        if proc is None:
            return False

        gpu_id = self._gpu_map.pop(task_id, None)
        self._active_procs.pop(task_id, None)

        await self._kill_process_tree(proc, task_id)

        async with self._session_factory() as db:
            task = (await db.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one_or_none()

            if task is None:
                logger.error("Task %s not found during termination", task_id)
                return True

            now = datetime.now()
            task.status = TaskStatus.TERMINATED
            task.finished_at = now
            task.exit_code = proc.returncode if proc.returncode is not None else -9

            # 释放该任务占用的全部 GPU（多卡）
            gpus = (await db.execute(
                select(GPU)
                .where(GPU.current_task_id == task_id)
                .order_by(GPU.id.asc())
            )).scalars().all()
            for gpu in gpus:
                gpu.status = GpuStatus.IDLE
                gpu.current_task_id = None
                db.add(AllocationLog(
                    task_id=task.id,
                    gpu_id=gpu.id,
                    action=AllocationAction.RELEASE,
                    actor_user_id=None,
                    notes="process_manager: task terminated",
                ))

            await db.commit()

        logger.info("Task %s terminated, GPU(s) %s released", task_id, gpu_id)
        return True

    async def _kill_process_tree(
        self,
        proc: asyncio.subprocess.Process,
        task_id: int,
    ) -> None:
        """终止进程。

        Windows 下用 taskkill /F /T 杀整棵进程树：create_subprocess_exec 启动
        `cmd /c ping ...` 这类命令时会产生 cmd.exe → ping.exe 父子进程，
        直接 proc.kill() 只杀父进程，子进程会残留继续运行。
        """
        try:
            if os.name == "nt":
                taskkill = await asyncio.create_subprocess_exec(
                    "taskkill", "/F", "/T", "/PID", str(proc.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(taskkill.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning("taskkill timed out for task %s", task_id)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Process tree for task %s did not exit after taskkill; "
                        "the process may still be running",
                        task_id,
                    )
            else:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Process %s did not exit within timeout after kill", task_id)
        except Exception as exc:
            logger.error("Error killing process %s: %s", task_id, exc)

    async def _run_once(self) -> None:
        async with self._session_factory() as db:
            await self._launch_pending(db)
            await self._collect_exited(db)

    async def _launch_pending(self, db: AsyncSession) -> None:
        # FOR UPDATE 行锁：与 terminate 接口的 PENDING 分支互斥，
        # 防止"终止"与"提升为 RUNNING"互相覆盖状态
        rows = (await db.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.PENDING,
                Task.allocated_gpu_id.isnot(None),
            )
            .with_for_update()
        )).scalars().all()

        for task in rows:
            if task.id in self._active_procs:
                continue

            # 任务占用的全部 GPU（分配阶段已写 GPU.current_task_id，天然支持多卡）
            gpus = (await db.execute(
                select(GPU)
                .where(GPU.current_task_id == task.id)
                .order_by(GPU.id.asc())
            )).scalars().all()

            if not gpus:
                logger.error(
                    "Task %s has no GPU bound (allocated_gpu_id=%s)",
                    task.id, task.allocated_gpu_id,
                )
                task.status = TaskStatus.FAILED
                task.finished_at = datetime.now()
                task.exit_code = -1
                await db.commit()
                continue

            proc = await self._spawn_process(task, gpus)

            if proc is None:
                task.status = TaskStatus.FAILED
                task.finished_at = datetime.now()
                task.exit_code = -1
                for gpu in gpus:
                    gpu.status = GpuStatus.IDLE
                    gpu.current_task_id = None
                    db.add(AllocationLog(
                        task_id=task.id,
                        gpu_id=gpu.id,
                        action=AllocationAction.RELEASE,
                        actor_user_id=None,
                        notes="process_manager: launch failed, reclaimed GPU",
                    ))
                await db.commit()
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            task.log_path = f"{LOG_DIR}/{task.id}.log"
            for gpu in gpus:
                gpu.status = GpuStatus.RUNNING
            await db.commit()

            self._active_procs[task.id] = proc
            self._gpu_map[task.id] = gpus[0].id
            logger.info(
                "Spawned process for task %s on GPU(s) %s (pid=%s)",
                task.id, ",".join(str(g.id) for g in gpus), proc.pid,
            )

    async def _spawn_process(
        self, task: Task, gpus: list[GPU]
    ) -> asyncio.subprocess.Process | None:
        env = os.environ.copy()
        # 多卡任务注入逗号分隔的设备号，如 "1,2"（CUDA 按物理卡序号识别）
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g.id) for g in gpus)

        log_path = Path(LOG_DIR) / f"{task.id}.log"
        try:
            log_fh = open(log_path, "w", encoding="utf-8")
        except OSError as exc:
            logger.error("Cannot open log file %s: %s", log_path, exc)
            return None

        try:
            cmd_parts = shlex.split(task.command)
            if not cmd_parts:
                logger.error("Task %s has empty command", task.id)
                log_fh.close()
                return None

            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=log_fh,
                stderr=log_fh,
                env=env,
            )
        except Exception as exc:
            logger.error(
                "Failed to spawn task %s (cmd=%r): %s",
                task.id, task.command, exc,
            )
            try:
                log_fh.close()
            except Exception:
                pass
            return None

        return proc

    async def _collect_exited(self, db: AsyncSession) -> None:
        done_ids = [
            tid for tid, p in self._active_procs.items()
            if p.returncode is not None
        ]

        for task_id in done_ids:
            proc = self._active_procs.pop(task_id)
            self._gpu_map.pop(task_id, None)

            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

            await self._finalize_task(db, task_id, proc.returncode)

    async def _finalize_task(
        self,
        db: AsyncSession,
        task_id: int,
        exit_code: int | None,
    ) -> None:
        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        # 按 current_task_id 释放该任务占用的全部 GPU（兼容多卡）
        gpus = (await db.execute(
            select(GPU)
            .where(GPU.current_task_id == task_id)
            .order_by(GPU.id.asc())
        )).scalars().all()

        if task is None:
            logger.error("Task %s not found during finalization", task_id)
            return

        now = datetime.now()
        task.finished_at = now
        task.exit_code = exit_code
        task.status = (
            TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED
        )

        for gpu in gpus:
            gpu.status = GpuStatus.IDLE
            gpu.current_task_id = None
            db.add(AllocationLog(
                task_id=task.id,
                gpu_id=gpu.id,
                action=AllocationAction.RELEASE,
                actor_user_id=None,
                notes=f"process_manager: exit code {exit_code}",
            ))
        await db.commit()

        logger.info(
            "Task %s finished: status=%s exit_code=%s GPU(s) %s released",
            task.id, task.status.value, exit_code,
            ",".join(str(g.id) for g in gpus) if gpus else "-",
        )

    async def _run_loop(self) -> None:
        logger.info("ProcessManager loop running")
        while not self._stop_event.is_set():
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("ProcessManager tick error: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
            except asyncio.TimeoutError:
                pass