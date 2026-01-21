"""
Sera Otonom - Config Loader

YAML config dosyalarını yükler ve environment variable'ları çözer.
"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigLoader:
    """YAML config yükleyici"""

    # Environment variable pattern: ${VAR_NAME}
    ENV_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def __init__(self, base_path: Optional[Path] = None):
        """
        Config loader'ı başlat

        Args:
            base_path: Proje kök dizini (None ise otomatik bulur)
        """
        self.base_path = base_path or self._find_project_root()
        self._load_env()
        self._cache: Dict[str, Any] = {}
        logger.info(f"ConfigLoader initialized with base_path: {self.base_path}")

    def _find_project_root(self) -> Path:
        """Proje kök dizinini bul (requirements.txt veya .env olan yer)"""
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "requirements.txt").exists() or (current / ".env").exists():
                return current
            current = current.parent
        return Path.cwd()

    def _load_env(self) -> None:
        """Load .env file if exists"""
        env_path = self.base_path / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded .env from {env_path}")
        else:
            logger.warning(f".env not found at {env_path}")

    def _resolve_env_vars(self, value: Any) -> Any:
        """
        String içindeki ${VAR} pattern'lerini environment variable ile değiştir

        Args:
            value: Herhangi bir değer

        Returns:
            Environment variable'lar çözülmüş değer
        """
        if isinstance(value, str):
            def replacer(match):
                var_name = match.group(1)
                env_value = os.getenv(var_name)
                if env_value is None:
                    logger.warning(f"Environment variable not found: {var_name}")
                    return match.group(0)  # Orijinal string'i koru
                return env_value
            return self.ENV_PATTERN.sub(replacer, value)
        elif isinstance(value, dict):
            return {k: self._resolve_env_vars(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_env_vars(item) for item in value]
        return value

    def load(self, config_name: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Config dosyasını yükle

        Args:
            config_name: Config dosya adı (uzantısız, örn: "settings")
            use_cache: Cache kullan mı?

        Returns:
            Config dictionary
        """
        if use_cache and config_name in self._cache:
            return self._cache[config_name]

        config_path = self.base_path / "config" / f"{config_name}.yaml"

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        resolved_config = self._resolve_env_vars(raw_config)

        if use_cache:
            self._cache[config_name] = resolved_config

        logger.info(f"Loaded config: {config_name}")
        return resolved_config

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        """Tüm config dosyalarını yükle"""
        configs = {}
        config_dir = self.base_path / "config"

        for yaml_file in config_dir.glob("*.yaml"):
            name = yaml_file.stem
            configs[name] = self.load(name)

        return configs

    def get(self, config_name: str, key_path: str, default: Any = None) -> Any:
        """
        Config'den nested değer al

        Args:
            config_name: Config dosya adı
            key_path: Nokta ile ayrılmış key yolu (örn: "tts.mqtt.broker")
            default: Bulunamazsa dönecek değer

        Returns:
            Config değeri veya default
        """
        config = self.load(config_name)
        keys = key_path.split('.')

        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def reload(self, config_name: Optional[str] = None) -> None:
        """Cache'i temizle ve yeniden yükle"""
        if config_name:
            self._cache.pop(config_name, None)
        else:
            self._cache.clear()
        logger.info(f"Config cache cleared: {config_name or 'all'}")


# Global instance
_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """Global config loader instance'ı al"""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader


def get_config(config_name: str) -> Dict[str, Any]:
    """Shortcut: Config yükle"""
    return get_config_loader().load(config_name)


def get_setting(key_path: str, default: Any = None) -> Any:
    """Shortcut: settings.yaml'dan değer al"""
    return get_config_loader().get("settings", key_path, default)
