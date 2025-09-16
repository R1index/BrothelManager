"""Filesystem-backed persistence for player and market data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional


class DataStore:
    """Utility wrapper around the project's data directories."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2]
        self.base_dir = base_dir
        self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.market_dir = self.data_dir / "markets"
        self.catalog_path = self.data_dir / "girls_catalog.json"
        self.data_dir.mkdir(exist_ok=True)
        self.users_dir.mkdir(exist_ok=True)
        self.market_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Generic JSON helpers
    # ------------------------------------------------------------------
    def read_json(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Domain specific helpers
    # ------------------------------------------------------------------
    def user_path(self, uid: int) -> Path:
        return self.users_dir / f"{uid}.json"

    def market_path(self, uid: int) -> Path:
        return self.market_dir / f"{uid}.json"

    def load_catalog(self) -> dict:
        data = self.read_json(self.catalog_path)
        if data is None:
            raise FileNotFoundError(f"Catalog not found: {self.catalog_path}")
        return data

    def iter_user_ids(self) -> Iterable[int]:
        for entry in self.users_dir.glob("*.json"):
            try:
                yield int(entry.stem)
            except ValueError:
                continue
