"""Файловое хранилище игровых данных."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

__all__ = ["DataStore"]


class DataStore:
    """Инкапсулирует доступ к JSON-файлам пользователей и рынков."""

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[2]).resolve()
        self.config_path = self.base_dir / "config.json"
        self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.market_dir = self.data_dir / "markets"
        self.catalog_path = self.data_dir / "girls_catalog.json"
        self.assets_dir = self.base_dir / "assets" / "girls"
        self.configure_paths(None)

    # ------------------------- конфигурация -------------------------
    def configure_paths(self, overrides: Optional[Dict[str, str]]) -> None:
        if overrides is None:
            overrides = {}
        data_dir = overrides.get("data_dir")
        if data_dir:
            self.data_dir = self._resolve_path(data_dir)
        else:
            self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.market_dir = self.data_dir / "markets"

        catalog = overrides.get("catalog")
        if catalog:
            self.catalog_path = self._resolve_path(catalog)
        else:
            self.catalog_path = self.data_dir / "girls_catalog.json"

        assets = overrides.get("assets")
        if assets:
            self.assets_dir = self._resolve_path(assets)
        else:
            self.assets_dir = self.base_dir / "assets" / "girls"

        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.market_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = (self.base_dir / value).resolve()
        return path

    # ------------------------- операции чтения/записи -------------------------
    def read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------- пути -------------------------
    def user_path(self, uid: int) -> Path:
        return self.users_dir / f"{int(uid)}.json"

    def market_path(self, uid: int) -> Path:
        return self.market_dir / f"{int(uid)}.json"

    # ------------------------- обход -------------------------
    def iter_user_ids(self) -> Iterator[int]:
        if not self.users_dir.exists():
            return iter(())
        return (
            int(path.stem)
            for path in self.users_dir.glob("*.json")
            if path.stem.isdigit()
        )

    # ------------------------- справочные данные -------------------------
    def load_catalog(self) -> dict:
        if not self.catalog_path.exists():
            return {"girls": []}
        try:
            return json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"girls": []}

