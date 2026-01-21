#!/usr/bin/env python3
"""Sera Otonom - Ana Giriş Noktası"""

__version__ = "0.1.0"

# === IMPORTS ===
import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from logging.handlers import RotatingFileHandler

# Rich (console output)
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.panel import Panel

# Project imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.brain import SeraBrain
from utils.config_loader import get_config_loader
from utils.state_manager import get_state_manager

# === CONSTANTS ===
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = "sera.log"
MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 5

console = Console()
logger = logging.getLogger("sera")


# === GRACEFUL SHUTDOWN ===
class GracefulShutdown:
    """Signal handler for graceful shutdown"""

    def __init__(self):
        self.shutdown_requested = False
        self._brain: Optional[SeraBrain] = None

    def set_brain(self, brain: SeraBrain) -> None:
        """Set brain instance for shutdown"""
        self._brain = brain

    def request_shutdown(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM"""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, requesting shutdown...")
        console.print(f"\n[yellow]Kapatılıyor... ({sig_name})[/yellow]")
        self.shutdown_requested = True

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Gracefully shutdown brain with timeout"""
        if self._brain:
            try:
                logger.info(f"Stopping brain with {timeout}s timeout")
                await asyncio.wait_for(self._brain.stop(), timeout=timeout)
                logger.info("Brain stopped successfully")
            except asyncio.TimeoutError:
                logger.warning(f"Brain stop timed out after {timeout}s")
            except Exception as e:
                logger.error(f"Error during brain shutdown: {e}")


# Global shutdown handler
shutdown_handler = GracefulShutdown()


# === LOGGING SETUP ===
def setup_logging(debug: bool) -> None:
    """
    Setup logging with console and file handlers

    Args:
        debug: Enable DEBUG level logging
    """
    level = logging.DEBUG if debug else logging.INFO

    # Create logs directory
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # 1. Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=debug,
        rich_tracebacks=True,
        tracebacks_show_locals=debug
    )
    rich_handler.setLevel(level)
    root_logger.addHandler(rich_handler)

    # 2. Rotating file handler
    file_handler = RotatingFileHandler(
        LOG_DIR / LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)

    # 3. Quiet noisy library loggers
    for lib_logger in ['aiomqtt', 'aiohttp', 'asyncio', 'urllib3']:
        logging.getLogger(lib_logger).setLevel(logging.WARNING)

    logger.info(f"Logging initialized (level: {'DEBUG' if debug else 'INFO'})")


# === CLI PARSER ===
def create_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser(
        prog="sera-otonom",
        description="Sera Otonom - Akıllı Sera Yönetim Sistemi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python main.py --version          Versiyon göster
  python main.py status             Sistem durumunu göster
  python main.py --once --debug     Tek cycle çalıştır (debug modunda)
  python main.py --dry-run          Komut göndermeden simüle et
  python main.py --no-claude        Fallback mod kullan
        """
    )

    parser.add_argument(
        '--config', '-c',
        type=str,
        default="config/settings.yaml",
        help="Config dosyası yolu (default: config/settings.yaml)"
    )

    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        default=False,
        help="DEBUG logging aktif et"
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help="Komut göndermeden simüle et"
    )

    parser.add_argument(
        '--no-claude',
        action='store_true',
        default=False,
        help="Claude kullanma, fallback kullan"
    )

    parser.add_argument(
        '--once',
        action='store_true',
        default=False,
        help="Tek bir cycle çalıştır ve çık"
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f"Sera Otonom v{__version__}"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Komutlar')

    # Status subcommand
    subparsers.add_parser('status', help='Sistem durumunu göster')

    return parser


# === HEALTH CHECK ===
def check_health() -> dict:
    """
    Check system health and required files

    Returns:
        dict with 'ok' bool and 'issues' list
    """
    issues = []
    warnings = []

    # Check config/settings.yaml
    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        issues.append(f"Config dosyası bulunamadı: {settings_path}")

    # Check .env (warning only)
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        warnings.append(".env dosyası bulunamadı (opsiyonel)")

    # Check state/templates/
    templates_path = PROJECT_ROOT / "state" / "templates"
    if not templates_path.exists():
        issues.append(f"Template dizini bulunamadı: {templates_path}")

    # Check MQTT config (warning only)
    try:
        config_loader = get_config_loader()
        settings = config_loader.load("settings")
        mqtt_config = settings.get('tts', {}).get('mqtt', {})
        if not mqtt_config.get('broker'):
            warnings.append("MQTT broker yapılandırılmamış")
    except Exception:
        pass  # Will be caught as critical error above

    # Check weather API key (warning only)
    try:
        config_loader = get_config_loader()
        settings = config_loader.load("settings")
        weather_key = settings.get('weather', {}).get('api_key')
        if not weather_key or weather_key.startswith('${'):
            warnings.append("Weather API key yapılandırılmamış")
    except Exception:
        pass

    # Log warnings
    for warning in warnings:
        logger.warning(warning)

    return {
        'ok': len(issues) == 0,
        'issues': issues,
        'warnings': warnings
    }


# === STATUS COMMAND ===
def show_status() -> int:
    """
    Show system status from state files

    Returns:
        Exit code (0 for success)
    """
    state_manager = get_state_manager()

    # Read state files
    try:
        device_states = state_manager.read("device_states")
    except Exception:
        device_states = {}

    try:
        decisions = state_manager.read("decisions")
    except Exception:
        decisions = {}

    try:
        current = state_manager.read("current")
    except Exception:
        current = {}

    # Build status display
    status_lines = []
    status_lines.append(f"Versiyon:     {__version__}")

    # Check if running (simple heuristic based on timestamp)
    last_update = device_states.get('timestamp')
    running = False
    if last_update:
        try:
            last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            age_seconds = (datetime.now(last_dt.tzinfo) - last_dt).total_seconds()
            running = age_seconds < 600  # 10 minutes
        except Exception:
            pass

    status_symbol = "[green]●[/green]" if running else "[red]○[/red]"
    status_text = "Çalışıyor" if running else "Durdu"
    status_lines.append(f"Durum:        {status_symbol} {status_text}")

    # Create main panel
    main_content = "\n".join(status_lines)

    # Connections section
    conn_lines = []
    mqtt_connected = device_states.get('mqtt_connected', False)
    mqtt_symbol = "[green]●[/green]" if mqtt_connected else "[red]○[/red]"
    mqtt_text = "Bağlı" if mqtt_connected else "Bağlantı yok"
    conn_lines.append(f"├─ MQTT:           {mqtt_symbol} {mqtt_text}")

    # Claude status from last decision
    last_decision = decisions.get('decisions', [{}])[-1] if decisions.get('decisions') else {}
    claude_active = last_decision.get('source') == 'claude'
    claude_symbol = "[green]●[/green]" if claude_active else "[yellow]○[/yellow]"
    claude_text = "Aktif" if claude_active else "Devre dışı"
    conn_lines.append(f"└─ Claude:         {claude_symbol} {claude_text}")

    conn_content = "\n".join(conn_lines)

    # Devices section
    device_lines = []
    devices = device_states.get('devices', {})

    for device_id, device_info in devices.items():
        state = device_info.get('state', 'off')
        if state == 'on':
            symbol = "[green]●[/green]"
            text = "AÇIK"
        else:
            symbol = "[red]○[/red]"
            text = "KAPALI"

        # Format device name nicely
        device_name = device_id.replace('_', ' ').title()
        device_lines.append(f"├─ {device_name:14s} {symbol} {text}")

    # Adjust last item prefix
    if device_lines:
        device_lines[-1] = device_lines[-1].replace("├─", "└─")

    device_content = "\n".join(device_lines) if device_lines else "└─ Cihaz yok"

    # Sensors section (from current.json)
    sensor_lines = []
    sensors = current.get('sensors', {})

    for sensor_name, sensor_data in sensors.items():
        value = sensor_data.get('value')
        unit = sensor_data.get('unit', '')
        if value is not None:
            sensor_display = sensor_name.replace('_', ' ').title()
            sensor_lines.append(f"├─ {sensor_display:14s} {value}{unit}")

    if sensor_lines:
        sensor_lines[-1] = sensor_lines[-1].replace("├─", "└─")

    sensor_content = "\n".join(sensor_lines) if sensor_lines else "└─ Sensör verisi yok"

    # Build full output
    console.print()
    console.print(Panel(
        f"[bold]SERA OTONOM DURUMU[/bold]\n\n"
        f"{main_content}\n\n"
        f"[bold]BAĞLANTILAR[/bold]\n{conn_content}\n\n"
        f"[bold]CİHAZLAR[/bold]\n{device_content}\n\n"
        f"[bold]SENSÖRLER[/bold]\n{sensor_content}",
        border_style="blue",
        padding=(1, 2)
    ))
    console.print()

    return 0


# === RUN MODES ===
async def run_once(args) -> int:
    """
    Run a single brain cycle

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code
    """
    logger.info("Starting single cycle mode")

    use_claude = not args.no_claude
    dry_run = args.dry_run

    brain = SeraBrain(
        config_path=args.config,
        use_claude=use_claude,
        use_fallback=True,
        dry_run=dry_run
    )

    try:
        await brain.initialize()
        result = await brain.run_cycle()

        if result.get('success'):
            logger.info(f"Cycle completed: {result.get('decision', {}).get('action', 'none')}")
            return 0
        else:
            logger.error(f"Cycle failed: {result.get('error')}")
            return 1

    except Exception as e:
        logger.error(f"Run once failed: {e}")
        return 1
    finally:
        await brain.stop()


async def run_continuous(args) -> int:
    """
    Run continuous brain cycles

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code
    """
    logger.info("Starting continuous mode")

    use_claude = not args.no_claude
    dry_run = args.dry_run

    brain = SeraBrain(
        config_path=args.config,
        use_claude=use_claude,
        use_fallback=True,
        dry_run=dry_run
    )

    shutdown_handler.set_brain(brain)

    # Setup signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler.request_shutdown, sig, None)

    try:
        await brain.initialize()
        await brain.start()

        # Wait for shutdown signal
        while not shutdown_handler.shutdown_requested:
            await asyncio.sleep(1)

        logger.info("Shutdown requested, stopping...")
        await shutdown_handler.shutdown()
        return 0

    except Exception as e:
        logger.error(f"Continuous run failed: {e}")
        return 1
    finally:
        if brain.is_running:
            await brain.stop()


async def async_main(args) -> int:
    """
    Async main entry point

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code
    """
    if args.once:
        return await run_once(args)
    else:
        return await run_continuous(args)


# === MAIN ===
def main() -> int:
    """
    Main entry point

    Returns:
        Exit code
    """
    parser = create_parser()
    args = parser.parse_args()

    # Handle status subcommand before logging setup
    if args.command == 'status':
        return show_status()

    # Setup logging
    setup_logging(args.debug)

    logger.info(f"Sera Otonom v{__version__} başlatılıyor")

    if args.dry_run:
        logger.info("[DRY-RUN] Dry run modu aktif - komutlar gönderilmeyecek")

    if args.no_claude:
        logger.info("Claude devre dışı - fallback mod kullanılacak")

    # Health check
    health = check_health()
    if not health['ok']:
        for issue in health['issues']:
            logger.error(f"Kritik: {issue}")
        console.print("[red]Kritik hatalar nedeniyle başlatılamıyor![/red]")
        return 1

    # Run async main
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Kullanıcı tarafından durduruldu[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
