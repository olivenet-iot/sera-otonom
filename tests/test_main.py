"""
Sera Otonom - Main Entry Point Unit Tests

pytest ile main.py modülü testleri
"""

import pytest
import sys
import argparse
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Project root'u ekle
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Test edilecek modül
from main import (
    __version__,
    create_parser,
    check_health,
    GracefulShutdown,
    setup_logging,
    LOG_DIR,
    LOG_FILE
)


# ==================== Version Tests ====================

class TestVersion:
    """Version flag testleri"""

    def test_version_defined(self):
        """__version__ tanımlı olmalı"""
        assert __version__ is not None
        assert isinstance(__version__, str)

    def test_version_format(self):
        """Version formatı x.y.z olmalı"""
        parts = __version__.split('.')
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_version_flag(self):
        """--version flag argparse ile çalışmalı"""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(['--version'])
        assert exc_info.value.code == 0


# ==================== Parser Tests ====================

class TestCreateParser:
    """Argparse testleri"""

    def test_parser_creation(self):
        """Parser oluşturulabilmeli"""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_default_values(self):
        """Default değerler doğru olmalı"""
        parser = create_parser()
        args = parser.parse_args([])

        assert args.config == "config/settings.yaml"
        assert args.debug is False
        assert args.dry_run is False
        assert args.no_claude is False
        assert args.once is False

    def test_debug_flag(self):
        """--debug flag çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--debug'])
        assert args.debug is True

    def test_debug_short_flag(self):
        """-d flag çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['-d'])
        assert args.debug is True

    def test_dry_run_flag(self):
        """--dry-run flag çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_no_claude_flag(self):
        """--no-claude flag çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--no-claude'])
        assert args.no_claude is True

    def test_once_flag(self):
        """--once flag çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--once'])
        assert args.once is True

    def test_config_option(self):
        """--config option çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--config', 'custom/path.yaml'])
        assert args.config == 'custom/path.yaml'

    def test_config_short_option(self):
        """-c option çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['-c', 'custom/path.yaml'])
        assert args.config == 'custom/path.yaml'

    def test_status_subcommand(self):
        """status subcommand çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['status'])
        assert args.command == 'status'

    def test_combined_flags(self):
        """Birden fazla flag kombinasyonu çalışmalı"""
        parser = create_parser()
        args = parser.parse_args(['--debug', '--dry-run', '--no-claude', '--once'])

        assert args.debug is True
        assert args.dry_run is True
        assert args.no_claude is True
        assert args.once is True

    def test_invalid_argument(self):
        """Geçersiz argüman hata vermeli"""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(['--invalid-arg'])
        assert exc_info.value.code == 2

    def test_help_flag(self):
        """--help flag çalışmalı"""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(['--help'])
        assert exc_info.value.code == 0


# ==================== Health Check Tests ====================

class TestCheckHealth:
    """Health check testleri"""

    @patch('main.PROJECT_ROOT', Path('/nonexistent/path'))
    def test_check_health_config_missing(self):
        """Config dosyası yoksa kritik hata"""
        result = check_health()
        assert result['ok'] is False
        assert any('Config dosyası' in issue for issue in result['issues'])

    @patch('main.PROJECT_ROOT')
    def test_check_health_templates_missing(self, mock_root, tmp_path):
        """Templates dizini yoksa kritik hata"""
        # Geçici dizin oluştur sadece config ile
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text("brain:\n  cycle_interval_seconds: 300")

        mock_root.__truediv__ = lambda self, x: tmp_path / x

        with patch('main.PROJECT_ROOT', tmp_path):
            result = check_health()
            assert result['ok'] is False
            assert any('Template dizini' in issue for issue in result['issues'])

    @patch('main.PROJECT_ROOT')
    @patch('main.get_config_loader')
    def test_check_health_success(self, mock_config_loader, mock_root, tmp_path):
        """Tüm dosyalar varsa ok"""
        # Gerekli dizinleri oluştur
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text("brain:\n  cycle_interval_seconds: 300")

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        templates_dir = state_dir / "templates"
        templates_dir.mkdir()

        (tmp_path / ".env").write_text("TEST=1")

        # Mock config loader
        mock_loader = MagicMock()
        mock_loader.load.return_value = {
            'tts': {'mqtt': {'broker': 'localhost'}},
            'weather': {'api_key': 'test_key'}
        }
        mock_config_loader.return_value = mock_loader

        with patch('main.PROJECT_ROOT', tmp_path):
            result = check_health()
            assert result['ok'] is True
            assert len(result['issues']) == 0

    @patch('main.PROJECT_ROOT')
    @patch('main.get_config_loader')
    def test_check_health_env_missing_warning(self, mock_config_loader, mock_root, tmp_path):
        """.env yoksa sadece warning"""
        # Gerekli dizinleri oluştur
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.yaml").write_text("brain:\n  cycle_interval_seconds: 300")

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        templates_dir = state_dir / "templates"
        templates_dir.mkdir()

        # .env dosyası yok

        # Mock config loader
        mock_loader = MagicMock()
        mock_loader.load.return_value = {
            'tts': {'mqtt': {'broker': 'localhost'}},
            'weather': {'api_key': 'test_key'}
        }
        mock_config_loader.return_value = mock_loader

        with patch('main.PROJECT_ROOT', tmp_path):
            result = check_health()
            assert result['ok'] is True  # Still OK, just warning
            assert any('.env' in w for w in result['warnings'])


# ==================== GracefulShutdown Tests ====================

class TestGracefulShutdown:
    """GracefulShutdown sınıfı testleri"""

    def test_init(self):
        """GracefulShutdown oluşturulabilmeli"""
        gs = GracefulShutdown()
        assert gs.shutdown_requested is False
        assert gs._brain is None

    def test_set_brain(self):
        """Brain set edilebilmeli"""
        gs = GracefulShutdown()
        mock_brain = Mock()
        gs.set_brain(mock_brain)
        assert gs._brain == mock_brain

    def test_request_shutdown(self):
        """Shutdown request çalışmalı"""
        gs = GracefulShutdown()

        import signal
        gs.request_shutdown(signal.SIGINT, None)

        assert gs.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_shutdown_without_brain(self):
        """Brain yokken shutdown çalışmalı"""
        gs = GracefulShutdown()
        # Should not raise
        await gs.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_with_brain(self):
        """Brain varken shutdown çalışmalı"""
        from unittest.mock import AsyncMock

        gs = GracefulShutdown()
        mock_brain = Mock()
        mock_brain.stop = AsyncMock()

        gs.set_brain(mock_brain)
        await gs.shutdown(timeout=5.0)

        mock_brain.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self):
        """Shutdown timeout çalışmalı"""
        from unittest.mock import AsyncMock
        import asyncio

        gs = GracefulShutdown()
        mock_brain = Mock()

        # Slow stop that will timeout
        async def slow_stop():
            await asyncio.sleep(10)

        mock_brain.stop = slow_stop

        gs.set_brain(mock_brain)

        # Should not hang, should timeout
        await gs.shutdown(timeout=0.1)


# ==================== Logging Tests ====================

class TestSetupLogging:
    """Logging setup testleri"""

    def test_log_dir_constant(self):
        """LOG_DIR sabiti tanımlı olmalı"""
        assert LOG_DIR is not None
        assert isinstance(LOG_DIR, Path)

    def test_log_file_constant(self):
        """LOG_FILE sabiti tanımlı olmalı"""
        assert LOG_FILE == "sera.log"

    @patch('main.LOG_DIR')
    def test_setup_logging_debug(self, mock_log_dir, tmp_path):
        """Debug logging çalışmalı"""
        import logging

        mock_log_dir.mkdir = Mock()
        mock_log_dir.__truediv__ = lambda self, x: tmp_path / x

        with patch('main.LOG_DIR', tmp_path):
            tmp_path.mkdir(parents=True, exist_ok=True)
            setup_logging(debug=True)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    @patch('main.LOG_DIR')
    def test_setup_logging_info(self, mock_log_dir, tmp_path):
        """Info logging çalışmalı"""
        import logging

        with patch('main.LOG_DIR', tmp_path):
            tmp_path.mkdir(parents=True, exist_ok=True)
            setup_logging(debug=False)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO


# ==================== Integration Tests ====================

class TestMainIntegration:
    """Entegrasyon testleri"""

    def test_imports(self):
        """Tüm gerekli modüller import edilebilmeli"""
        from main import (
            main,
            create_parser,
            check_health,
            setup_logging,
            GracefulShutdown,
            show_status,
            run_once,
            run_continuous,
            async_main,
            __version__
        )
        # All imports successful
        assert True

    def test_project_root_exists(self):
        """PROJECT_ROOT doğru tanımlı olmalı"""
        from main import PROJECT_ROOT
        assert PROJECT_ROOT.exists()
        assert (PROJECT_ROOT / "main.py").exists()
