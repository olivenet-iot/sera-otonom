"""
Sera Otonom - Brain (Ana Orchestrator)

Bu modül tüm sistemi koordine eder:
- Sensör verilerini toplar
- Hava tahminini alır
- Claude Code'u çağırır
- Kararları uygular
"""

import logging
import asyncio
import uuid
from typing import Optional
from datetime import datetime
from pathlib import Path

from .claude_runner import ClaudeRunner, ClaudeResponse, FallbackDecisionMaker
from .scheduler import SeraScheduler, TaskStatus
from .data_collector import DataCollector
from utils.state_manager import get_state_manager
from utils.config_loader import get_config_loader

logger = logging.getLogger(__name__)


class SeraBrain:
    """Ana orchestrator sınıfı"""

    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        use_claude: bool = True,
        use_fallback: bool = True
    ):
        """
        Brain'i başlat

        Args:
            config_path: Ana config dosyasının yolu
            use_claude: Claude Code kullanılsın mı?
            use_fallback: Claude başarısız olursa fallback kullanılsın mı?
        """
        self.config_path = config_path
        self.use_claude = use_claude
        self.use_fallback = use_fallback

        # Load configs
        self.config_loader = get_config_loader()
        self.state_manager = get_state_manager()

        try:
            self.settings = self.config_loader.load("settings")
        except FileNotFoundError:
            logger.warning("settings.yaml not found, using defaults")
            self.settings = {}

        try:
            self.thresholds = self.config_loader.load("thresholds")
        except FileNotFoundError:
            logger.warning("thresholds.yaml not found, using empty config")
            self.thresholds = {}

        # Brain config
        brain_config = self.settings.get("brain", {})
        self.cycle_interval = brain_config.get("cycle_interval_seconds", 300)
        self.claude_timeout = brain_config.get("claude_timeout_seconds", 120)
        self.max_retries = brain_config.get("max_retries", 3)
        self.decision_limits = brain_config.get("decision_limits", {})

        # Components (lazily initialized)
        self.data_collector: Optional[DataCollector] = None
        self.scheduler: Optional[SeraScheduler] = None
        self.claude_runner: Optional[ClaudeRunner] = None
        self.fallback_maker: Optional[FallbackDecisionMaker] = None

        # State
        self.is_running = False
        self._initialized = False
        self._cycle_count = 0
        self._last_cycle_time: Optional[datetime] = None
        self._last_decision: Optional[ClaudeResponse] = None

        logger.info("SeraBrain initialized")

    async def initialize(self) -> bool:
        """
        Tüm bileşenleri başlat

        Returns:
            Başarılı ise True
        """
        if self._initialized:
            logger.warning("Brain already initialized")
            return True

        success = True

        # Initialize DataCollector
        try:
            self.data_collector = DataCollector(
                settings_config=self.settings,
                threshold_config=self.thresholds
            )
            if not await self.data_collector.initialize_connectors():
                logger.warning("DataCollector connector initialization partial failure")
                # Don't fail completely, some connectors may work
        except Exception as e:
            logger.error(f"DataCollector initialization failed: {e}")
            success = False

        # Initialize ClaudeRunner
        if self.use_claude:
            try:
                self.claude_runner = ClaudeRunner(
                    timeout=self.claude_timeout,
                    max_retries=self.max_retries
                )
                logger.info("ClaudeRunner initialized")
            except Exception as e:
                logger.error(f"ClaudeRunner initialization failed: {e}")
                self.claude_runner = None

        # Initialize FallbackDecisionMaker
        if self.use_fallback:
            self.fallback_maker = FallbackDecisionMaker(self.thresholds)

        # Initialize Scheduler
        self.scheduler = SeraScheduler(default_interval_seconds=self.cycle_interval)
        self._setup_scheduled_tasks()

        self._initialized = True
        logger.info("Brain initialization complete")
        return success

    def _setup_scheduled_tasks(self) -> None:
        """Zamanlanmış görevleri ayarla"""
        if not self.scheduler:
            return

        # Brain cycle - her 5 dakikada bir
        self.scheduler.add_task(
            name="brain_cycle",
            callback=self.run_cycle,
            interval_seconds=self.cycle_interval,
            run_immediately=False
        )

        # Weather update - her 30 dakikada bir
        weather_interval = self.settings.get("weather", {}).get("update_interval_minutes", 30) * 60
        self.scheduler.add_task(
            name="weather_update",
            callback=self._update_weather,
            interval_seconds=weather_interval,
            run_immediately=True  # Başlangıçta hemen çalıştır
        )

        logger.info("Scheduled tasks configured")

    async def start(self) -> None:
        """Brain döngüsünü başlat"""
        if self.is_running:
            logger.warning("Brain already running")
            return

        if not self._initialized:
            await self.initialize()

        self.is_running = True

        # Scheduler'ı başlat
        if self.scheduler:
            await self.scheduler.start()

        logger.info("Brain started")

    async def stop(self) -> None:
        """Brain döngüsünü durdur"""
        if not self.is_running:
            return

        self.is_running = False

        # Scheduler'ı durdur
        if self.scheduler:
            await self.scheduler.stop()

        # Data collector'ı kapat
        if self.data_collector:
            await self.data_collector.shutdown()

        logger.info("Brain stopped")

    async def run_cycle(self) -> dict:
        """
        Tek bir analiz döngüsü çalıştır

        Returns:
            Döngü sonucu (decision, thoughts, actions)
        """
        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{datetime.now().strftime('%H%M%S')}"

        logger.info(f"Starting brain cycle: {cycle_id}")

        result = {
            "cycle_id": cycle_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "success": False,
            "decision": None,
            "reasoning": None,
            "error": None
        }

        try:
            # 1. Veri topla
            context = await self._collect_context()
            if not context or "error" in context:
                result["error"] = context.get("error", "Failed to collect context")
                logger.error(f"Context collection failed: {result['error']}")
                return result

            # 2. Karar ver
            decision_result = await self._make_decision(context)

            if decision_result.success:
                result["success"] = True
                result["decision"] = decision_result.decision
                result["reasoning"] = decision_result.reasoning
                result["analysis"] = decision_result.analysis

                # 3. Kararı işle
                await self._process_decision(decision_result)

                # 4. Kaydet
                await self._save_decision(decision_result, cycle_id)

                self._last_decision = decision_result
                self._last_cycle_time = datetime.utcnow()

                logger.info(f"Cycle {cycle_id} completed: {decision_result.decision.get('action', 'none')}")
            else:
                result["error"] = decision_result.error
                logger.warning(f"Cycle {cycle_id} decision failed: {decision_result.error}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Cycle {cycle_id} failed with exception: {e}")

        return result

    async def _collect_context(self) -> dict:
        """Veri topla"""
        if not self.data_collector:
            return {"error": "DataCollector not initialized"}

        return await self.data_collector.collect_context()

    async def _make_decision(self, context: dict) -> ClaudeResponse:
        """
        Claude veya fallback ile karar ver

        Args:
            context: Toplanan veriler

        Returns:
            ClaudeResponse
        """
        # Claude dene
        if self.use_claude and self.claude_runner:
            try:
                result = await self.claude_runner.run(context)
                if result.success:
                    logger.info("Decision made by Claude")
                    return result
                logger.warning(f"Claude failed: {result.error}")
            except Exception as e:
                logger.error(f"Claude exception: {e}")

        # Fallback dene
        if self.use_fallback and self.fallback_maker:
            logger.info("Using fallback decision maker")
            return self.fallback_maker.make_decision(context.get("sensors", {}))

        # Hiçbiri çalışmadı
        return ClaudeResponse(
            success=False,
            error="No decision maker available"
        )

    async def _process_decision(self, result: ClaudeResponse) -> None:
        """
        Kararı pending_actions'a ekle

        Args:
            result: Karar sonucu
        """
        if not result.success or not result.decision:
            return

        decision = result.decision
        action = decision.get("action", "none")

        if action == "none":
            logger.debug("No action needed")
            return

        # Action'ı pending_actions'a ekle
        pending_action = {
            "id": str(uuid.uuid4())[:8],
            "action": action,
            "device": decision.get("device"),
            "duration_minutes": decision.get("duration_minutes"),
            "reason": decision.get("reason"),
            "confidence": decision.get("confidence"),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "status": "pending"
        }

        try:
            device_state = self.state_manager.read("device_states")
            pending = device_state.get("pending_actions", [])
            pending.append(pending_action)

            self.state_manager.update("device_states", {
                "pending_actions": pending,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })

            logger.info(f"Action queued: {action} for {decision.get('device')}")

        except Exception as e:
            logger.error(f"Failed to queue action: {e}")

    async def _save_decision(self, result: ClaudeResponse, cycle_id: str) -> None:
        """
        Kararı state'e kaydet

        Args:
            result: Karar sonucu
            cycle_id: Döngü ID'si
        """
        try:
            # Save to decisions.json
            decision_entry = {
                "id": str(uuid.uuid4())[:8],
                "cycle_id": cycle_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "decision": result.decision,
                "analysis": result.analysis,
                "confidence": result.decision.get("confidence") if result.decision else None,
                "source": "fallback" if "[Fallback" in result.raw_output else "claude"
            }

            self.state_manager.append_to_list(
                "decisions",
                "decisions",
                decision_entry,
                max_items=100  # Son 100 karar
            )

            # Update stats
            decisions_state = self.state_manager.read("decisions")
            stats = decisions_state.get("stats", {})
            stats["total_decisions"] = stats.get("total_decisions", 0) + 1
            stats["last_decision_id"] = decision_entry["id"]

            self.state_manager.update("decisions", {
                "stats": stats,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            })

            # Save reasoning to thoughts.json
            thought_entry = {
                "id": str(uuid.uuid4())[:8],
                "cycle_id": cycle_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reasoning": result.reasoning,
                "raw_output": result.raw_output[:1000] if result.raw_output else None  # Truncate
            }

            self.state_manager.append_to_list(
                "thoughts",
                "thoughts",
                thought_entry,
                max_items=50  # Son 50 düşünce
            )

            logger.debug(f"Decision and thoughts saved for cycle {cycle_id}")

        except Exception as e:
            logger.error(f"Failed to save decision: {e}")

    async def _update_weather(self) -> dict:
        """Weather güncelleme görevi"""
        if self.data_collector:
            return await self.data_collector.update_weather()
        return {"error": "DataCollector not initialized"}

    async def trigger_cycle(self) -> dict:
        """
        Manuel döngü tetikle

        Returns:
            Döngü sonucu
        """
        logger.info("Manual cycle triggered")
        return await self.run_cycle()

    def get_status(self) -> dict:
        """Brain durumunu al"""
        status = {
            "is_running": self.is_running,
            "initialized": self._initialized,
            "cycle_count": self._cycle_count,
            "last_cycle_time": self._last_cycle_time.isoformat() if self._last_cycle_time else None,
            "use_claude": self.use_claude,
            "use_fallback": self.use_fallback,
            "config": {
                "cycle_interval": self.cycle_interval,
                "claude_timeout": self.claude_timeout
            }
        }

        if self._last_decision:
            status["last_decision"] = {
                "action": self._last_decision.decision.get("action") if self._last_decision.decision else None,
                "timestamp": self._last_decision.timestamp,
                "success": self._last_decision.success
            }

        if self.scheduler:
            status["scheduler"] = self.scheduler.get_all_tasks_info()

        if self.data_collector:
            status["mqtt"] = self.data_collector.get_mqtt_status()
            status["weather"] = self.data_collector.get_weather_status()

        return status


if __name__ == "__main__":
    import asyncio

    async def test():
        print("SeraBrain Test")
        print("=" * 50)

        # Create brain with Claude disabled for testing
        brain = SeraBrain(use_claude=False, use_fallback=True)

        print(f"\nInitial status: {brain.get_status()}")

        # Initialize
        print("\nInitializing...")
        await brain.initialize()

        print(f"\nAfter init status: {brain.get_status()}")

        # Run a single cycle
        print("\nRunning single cycle...")
        result = await brain.run_cycle()
        print(f"Cycle result: {result}")

        # Check status
        print(f"\nFinal status: {brain.get_status()}")

        # Cleanup
        await brain.stop()

    asyncio.run(test())
