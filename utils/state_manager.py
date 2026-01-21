"""
Sera Otonom - State Manager

JSON state dosyalarını yönetir (read/write/update)
"""

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional
from threading import Lock
import copy

logger = logging.getLogger(__name__)


class StateManager:
    """Thread-safe JSON state yöneticisi"""

    def __init__(self, base_path: Optional[Path] = None):
        """
        State manager'ı başlat

        Args:
            base_path: Proje kök dizini
        """
        self.base_path = base_path or self._find_project_root()
        self.state_dir = self.base_path / "state"
        self.template_dir = self.state_dir / "templates"
        self._locks: Dict[str, Lock] = {}
        self._cache: Dict[str, Dict] = {}

        # State dizinini oluştur
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Template'lerden state dosyalarını başlat
        self._initialize_from_templates()

        logger.info(f"StateManager initialized with state_dir: {self.state_dir}")

    def _find_project_root(self) -> Path:
        """Proje kök dizinini bul"""
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "state").exists():
                return current
            current = current.parent
        return Path.cwd()

    def _get_lock(self, state_name: str) -> Lock:
        """State için lock al (lazy initialization)"""
        if state_name not in self._locks:
            self._locks[state_name] = Lock()
        return self._locks[state_name]

    def _initialize_from_templates(self) -> None:
        """Template'lerden state dosyalarını oluştur (yoksa)"""
        if not self.template_dir.exists():
            logger.warning(f"Template directory not found: {self.template_dir}")
            return

        for template_file in self.template_dir.glob("*.json"):
            state_name = template_file.stem
            state_file = self.state_dir / f"{state_name}.json"

            if not state_file.exists():
                shutil.copy(template_file, state_file)
                logger.info(f"Initialized state from template: {state_name}")

    def _get_state_path(self, state_name: str) -> Path:
        """State dosya yolunu al"""
        return self.state_dir / f"{state_name}.json"

    def read(self, state_name: str, use_cache: bool = False) -> Dict[str, Any]:
        """
        State dosyasını oku

        Args:
            state_name: State dosya adı (uzantısız, örn: "current")
            use_cache: Cache kullan mı? (dikkatli kullan, stale data riski)

        Returns:
            State dictionary
        """
        if use_cache and state_name in self._cache:
            return copy.deepcopy(self._cache[state_name])

        state_path = self._get_state_path(state_name)

        with self._get_lock(state_name):
            if not state_path.exists():
                # Template'den oluşturmayı dene
                template_path = self.template_dir / f"{state_name}.json"
                if template_path.exists():
                    shutil.copy(template_path, state_path)
                else:
                    raise FileNotFoundError(f"State file not found: {state_path}")

            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)

        self._cache[state_name] = copy.deepcopy(state)
        return state

    def write(self, state_name: str, data: Dict[str, Any]) -> None:
        """
        State dosyasına yaz (tamamen üzerine yaz)

        Args:
            state_name: State dosya adı
            data: Yazılacak data
        """
        state_path = self._get_state_path(state_name)

        with self._get_lock(state_name):
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        self._cache[state_name] = copy.deepcopy(data)
        logger.debug(f"State written: {state_name}")

    def update(self, state_name: str, updates: Dict[str, Any], deep: bool = True) -> Dict[str, Any]:
        """
        State dosyasını güncelle (merge)

        Args:
            state_name: State dosya adı
            updates: Güncellenecek key-value'lar
            deep: Deep merge mi shallow merge mi?

        Returns:
            Güncellenmiş state
        """
        state = self.read(state_name)

        if deep:
            self._deep_merge(state, updates)
        else:
            state.update(updates)

        # Timestamp güncelle
        state['timestamp'] = datetime.utcnow().isoformat() + 'Z'

        self.write(state_name, state)
        return state

    def _deep_merge(self, base: Dict, updates: Dict) -> None:
        """Dictionary'leri deep merge et (in-place)"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def get(self, state_name: str, key_path: str, default: Any = None) -> Any:
        """
        State'den nested değer al

        Args:
            state_name: State dosya adı
            key_path: Nokta ile ayrılmış key yolu (örn: "sensors.temperature.value")
            default: Bulunamazsa dönecek değer
        """
        state = self.read(state_name)
        keys = key_path.split('.')

        value = state
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def set(self, state_name: str, key_path: str, value: Any) -> None:
        """
        State'de nested değer set et

        Args:
            state_name: State dosya adı
            key_path: Nokta ile ayrılmış key yolu
            value: Atanacak değer
        """
        state = self.read(state_name)
        keys = key_path.split('.')

        # Navigate to parent
        current = state
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Set value
        current[keys[-1]] = value

        # Update timestamp
        state['timestamp'] = datetime.utcnow().isoformat() + 'Z'

        self.write(state_name, state)

    def append_to_list(
        self,
        state_name: str,
        list_path: str,
        item: Any,
        max_items: Optional[int] = None
    ) -> None:
        """
        State'deki bir listeye item ekle

        Args:
            state_name: State dosya adı
            list_path: Liste key yolu
            item: Eklenecek item
            max_items: Maksimum item sayısı (aşarsa eskiler silinir)
        """
        state = self.read(state_name)
        keys = list_path.split('.')

        # Navigate to list
        current = state
        for key in keys[:-1]:
            current = current.get(key, {})

        list_key = keys[-1]
        if list_key not in current:
            current[list_key] = []

        current[list_key].append(item)

        # Limit list size
        if max_items and len(current[list_key]) > max_items:
            current[list_key] = current[list_key][-max_items:]

        state['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        self.write(state_name, state)

    def reset(self, state_name: str) -> None:
        """State'i template'e sıfırla"""
        template_path = self.template_dir / f"{state_name}.json"
        state_path = self._get_state_path(state_name)

        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        with self._get_lock(state_name):
            shutil.copy(template_path, state_path)
            self._cache.pop(state_name, None)

        logger.info(f"State reset to template: {state_name}")

    def reset_all(self) -> None:
        """Tüm state'leri template'lere sıfırla"""
        for template_file in self.template_dir.glob("*.json"):
            self.reset(template_file.stem)


# Global instance
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Global state manager instance'ı al"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


def get_state(state_name: str) -> Dict[str, Any]:
    """Shortcut: State oku"""
    return get_state_manager().read(state_name)


def update_state(state_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Shortcut: State güncelle"""
    return get_state_manager().update(state_name, updates)
