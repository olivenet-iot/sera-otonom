"""
Sera Otonom - Scheduler

Periyodik görevleri zamanlayan modül
"""

import logging
import asyncio
from typing import Callable, Optional, Any, Awaitable, Union
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Görev durumları"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskStats:
    """Görev istatistikleri"""
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_run: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    total_duration_ms: int = 0
    avg_duration_ms: float = 0.0


@dataclass
class ScheduledTask:
    """Zamanlanmış görev"""
    name: str
    callback: Callable[[], Union[Any, Awaitable[Any]]]
    interval_seconds: int
    enabled: bool = True
    run_immediately: bool = False
    status: TaskStatus = TaskStatus.PENDING
    stats: TaskStats = field(default_factory=TaskStats)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)


class SeraScheduler:
    """Async görev zamanlayıcı"""

    def __init__(self, default_interval_seconds: int = 300):
        """
        Scheduler'ı başlat

        Args:
            default_interval_seconds: Varsayılan çalışma aralığı (saniye)
        """
        self.default_interval = default_interval_seconds
        self.tasks: dict[str, ScheduledTask] = {}
        self.is_running = False
        self._stop_event = asyncio.Event()
        logger.info(f"SeraScheduler initialized with {default_interval_seconds}s default interval")

    def add_task(
        self,
        name: str,
        callback: Callable[[], Union[Any, Awaitable[Any]]],
        interval_seconds: Optional[int] = None,
        run_immediately: bool = False,
        enabled: bool = True
    ) -> bool:
        """
        Yeni görev ekle

        Args:
            name: Görev adı (unique)
            callback: Çağrılacak fonksiyon (sync veya async)
            interval_seconds: Çalışma aralığı (saniye)
            run_immediately: Hemen çalıştır mı?
            enabled: Aktif mi?

        Returns:
            Başarılı ise True
        """
        if name in self.tasks:
            logger.warning(f"Task already exists: {name}")
            return False

        task = ScheduledTask(
            name=name,
            callback=callback,
            interval_seconds=interval_seconds or self.default_interval,
            enabled=enabled,
            run_immediately=run_immediately
        )
        self.tasks[name] = task
        logger.info(f"Task added: {name} (interval={task.interval_seconds}s, enabled={enabled})")

        # Scheduler çalışıyorsa görevi başlat
        if self.is_running and enabled:
            task._task = asyncio.create_task(self._task_loop(task))

        return True

    def remove_task(self, name: str) -> bool:
        """
        Görevi kaldır

        Args:
            name: Görev adı

        Returns:
            Başarılı ise True
        """
        if name not in self.tasks:
            logger.warning(f"Task not found: {name}")
            return False

        task = self.tasks[name]

        # Running task'ı iptal et
        if task._task and not task._task.done():
            task._task.cancel()

        del self.tasks[name]
        logger.info(f"Task removed: {name}")
        return True

    def enable_task(self, name: str) -> bool:
        """
        Görevi aktif et

        Args:
            name: Görev adı

        Returns:
            Başarılı ise True
        """
        if name not in self.tasks:
            logger.warning(f"Task not found: {name}")
            return False

        task = self.tasks[name]
        if task.enabled:
            return True

        task.enabled = True
        logger.info(f"Task enabled: {name}")

        # Scheduler çalışıyorsa görevi başlat
        if self.is_running:
            task._task = asyncio.create_task(self._task_loop(task))

        return True

    def disable_task(self, name: str) -> bool:
        """
        Görevi pasif yap

        Args:
            name: Görev adı

        Returns:
            Başarılı ise True
        """
        if name not in self.tasks:
            logger.warning(f"Task not found: {name}")
            return False

        task = self.tasks[name]
        task.enabled = False

        # Running task'ı iptal et
        if task._task and not task._task.done():
            task._task.cancel()
            task.status = TaskStatus.CANCELLED

        logger.info(f"Task disabled: {name}")
        return True

    async def run_task_once(self, name: str) -> Optional[Any]:
        """
        Görevi manuel olarak bir kez çalıştır

        Args:
            name: Görev adı

        Returns:
            Callback sonucu veya None (hata durumunda)
        """
        if name not in self.tasks:
            logger.warning(f"Task not found: {name}")
            return None

        task = self.tasks[name]
        return await self._execute_task(task)

    async def _execute_task(self, task: ScheduledTask) -> Optional[Any]:
        """
        Tek bir görevi çalıştır

        Args:
            task: Çalıştırılacak görev

        Returns:
            Callback sonucu
        """
        task.status = TaskStatus.RUNNING
        task.stats.run_count += 1
        task.stats.last_run = datetime.now()

        start_time = datetime.now()

        try:
            # Sync veya async callback'i çalıştır
            if asyncio.iscoroutinefunction(task.callback):
                result = await task.callback()
            else:
                result = task.callback()

            # Başarılı
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            task.stats.success_count += 1
            task.stats.last_success = datetime.now()
            task.stats.total_duration_ms += duration_ms
            task.stats.avg_duration_ms = task.stats.total_duration_ms / task.stats.run_count
            task.status = TaskStatus.COMPLETED

            logger.debug(f"Task {task.name} completed in {duration_ms}ms")
            return result

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            logger.info(f"Task {task.name} cancelled")
            raise
        except Exception as e:
            task.stats.failure_count += 1
            task.stats.last_failure = datetime.now()
            task.stats.last_error = str(e)
            task.status = TaskStatus.FAILED

            logger.error(f"Task {task.name} failed: {e}")
            return None

    async def _task_loop(self, task: ScheduledTask) -> None:
        """
        Tek bir görev için async döngü

        Args:
            task: Döngüsü çalıştırılacak görev
        """
        try:
            # run_immediately ise hemen çalıştır
            if task.run_immediately:
                await self._execute_task(task)

            while not self._stop_event.is_set() and task.enabled:
                try:
                    # Interval bekle
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=task.interval_seconds
                    )
                    # Stop event set edildi, çık
                    break
                except asyncio.TimeoutError:
                    # Timeout - normal durum, çalıştır
                    pass

                if task.enabled and not self._stop_event.is_set():
                    await self._execute_task(task)

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            logger.debug(f"Task loop cancelled: {task.name}")

    async def start(self) -> None:
        """Tüm görevleri başlat"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        self._stop_event.clear()
        self.is_running = True

        # Aktif görevleri başlat
        for task in self.tasks.values():
            if task.enabled:
                task._task = asyncio.create_task(self._task_loop(task))

        logger.info(f"Scheduler started with {len(self.tasks)} tasks")

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Tüm görevleri durdur

        Args:
            timeout: Görevlerin durması için maksimum süre (saniye)
        """
        if not self.is_running:
            return

        self._stop_event.set()
        self.is_running = False

        # Tüm task'ları topla
        running_tasks = [
            task._task for task in self.tasks.values()
            if task._task and not task._task.done()
        ]

        if running_tasks:
            # Graceful shutdown dene
            try:
                await asyncio.wait_for(
                    asyncio.gather(*running_tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                # Zorla iptal et
                for t in running_tasks:
                    t.cancel()
                await asyncio.gather(*running_tasks, return_exceptions=True)

        logger.info("Scheduler stopped")

    def get_task_info(self, name: str) -> Optional[dict]:
        """
        Görev bilgisi al

        Args:
            name: Görev adı

        Returns:
            Görev bilgisi dict'i
        """
        if name not in self.tasks:
            return None

        task = self.tasks[name]
        return {
            "name": task.name,
            "interval_seconds": task.interval_seconds,
            "enabled": task.enabled,
            "status": task.status.value,
            "stats": {
                "run_count": task.stats.run_count,
                "success_count": task.stats.success_count,
                "failure_count": task.stats.failure_count,
                "last_run": task.stats.last_run.isoformat() if task.stats.last_run else None,
                "last_success": task.stats.last_success.isoformat() if task.stats.last_success else None,
                "avg_duration_ms": task.stats.avg_duration_ms,
                "last_error": task.stats.last_error
            }
        }

    def get_all_tasks_info(self) -> dict:
        """Tüm görevlerin bilgisini al"""
        return {
            "is_running": self.is_running,
            "task_count": len(self.tasks),
            "tasks": {name: self.get_task_info(name) for name in self.tasks}
        }


if __name__ == "__main__":
    import asyncio

    async def test():
        print("SeraScheduler Test")
        print("=" * 50)

        scheduler = SeraScheduler(default_interval_seconds=5)

        # Test görevleri
        call_count = {"task1": 0, "task2": 0}

        async def task1():
            call_count["task1"] += 1
            print(f"Task 1 executed (count: {call_count['task1']})")
            return "task1 result"

        def task2():  # Sync task
            call_count["task2"] += 1
            print(f"Task 2 executed (count: {call_count['task2']})")

        # Görevleri ekle
        scheduler.add_task("task1", task1, interval_seconds=2, run_immediately=True)
        scheduler.add_task("task2", task2, interval_seconds=3, run_immediately=False)

        print(f"\nTasks: {scheduler.get_all_tasks_info()}")

        # Başlat
        await scheduler.start()

        # 5 saniye bekle
        print("\nWaiting 5 seconds...")
        await asyncio.sleep(5)

        # Manuel çalıştır
        print("\nManual execution of task1...")
        result = await scheduler.run_task_once("task1")
        print(f"Result: {result}")

        # Durum kontrol
        print(f"\nTask1 info: {scheduler.get_task_info('task1')}")

        # Durdur
        await scheduler.stop()
        print(f"\nFinal counts: {call_count}")

    asyncio.run(test())
