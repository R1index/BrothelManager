"""Файловое хранилище игровых данных."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Dict, Iterator, Optional

from .. import assets_util

__all__ = ["DataStore"]


class DataStore:
    """Управление каталогами и чтением/записью JSON."""

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.config_path = self.base_dir / "config.json"
        self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.market_dir = self.data_dir / "markets"
        self.catalog_path = self.data_dir / "girls_catalog.json"
        self.assets_dir = self.base_dir / "assets" / "girls"
        self._lock = RLock()
        self.ensure_dirs()

    # ------------------------------------------------------------------
    # Переопределение путей
    # ------------------------------------------------------------------
    def configure_paths(self, payload: Optional[Dict[str, str]]) -> None:
        if not payload:
            self.ensure_dirs()
            return

        data_dir = payload.get("data_dir")
        if data_dir:
            self.data_dir = (self.base_dir / data_dir).resolve()
        users = payload.get("users")
        if users:
            self.users_dir = (self.base_dir / users).resolve()
        else:
            self.users_dir = self.data_dir / "users"
        markets = payload.get("markets")
        if markets:
            self.market_dir = (self.base_dir / markets).resolve()
        else:
            self.market_dir = self.data_dir / "markets"
        catalog = payload.get("catalog")
        if catalog:
            self.catalog_path = (self.base_dir / catalog).resolve()
        else:
            self.catalog_path = self.data_dir / "girls_catalog.json"
        assets = payload.get("assets")
        if assets:
            self.assets_dir = (self.base_dir / assets).resolve()
        else:
            self.assets_dir = self.base_dir / "assets" / "girls"

        self.ensure_dirs()

    # ------------------------------------------------------------------
    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.market_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def user_path(self, user_id: int) -> Path:
        return self.users_dir / f"{int(user_id)}.json"

    def market_path(self, user_id: int) -> Path:
        return self.market_dir / f"{int(user_id)}.json"

    # ------------------------------------------------------------------
    def read_json(self, path: Path) -> Dict:
        with self._lock:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, payload: Dict) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    def iter_user_ids(self) -> Iterator[int]:
        if not self.users_dir.exists():
            return iter(())
        for file in self.users_dir.glob("*.json"):
            try:
                yield int(file.stem)
            except ValueError:
                continue

    # ------------------------------------------------------------------
    def load_catalog(self) -> Dict:
        payload = self.read_json(self.catalog_path)
        girls = payload.get("girls") or []
        normalized = []
        for entry in girls:
            if not isinstance(entry, dict):
                continue
            normalized.append(entry)
        return {"girls": normalized}

    # ------------------------------------------------------------------
    def apply_assets_dir(self) -> None:
        assets_util.set_assets_dir(self.assets_dir)


