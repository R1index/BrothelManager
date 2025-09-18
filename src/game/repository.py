"""Filesystem-backed persistence for player and market data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional


class DataStore:
    """Utility wrapper around the project's data directories."""

    def __init__(self, base_dir: Path | str | None = None):
        default_base = Path(__file__).resolve().parents[2]
        if base_dir is None:
            resolved_base = default_base
        else:
            resolved_base = Path(base_dir).expanduser()
            if not resolved_base.is_absolute():
                resolved_base = default_base / resolved_base
        resolved_base = resolved_base.resolve()
        self.base_dir = resolved_base
        self._base_anchor = resolved_base
        self.data_dir = self.base_dir / "data"
        self.users_dir = self.data_dir / "users"
        self.market_dir = self.data_dir / "markets"
        self.catalog_path = self.data_dir / "girls_catalog.json"
        self.assets_dir = self.base_dir / "assets" / "girls"
        self._catalog_cache: dict | None = None
        self._catalog_mtime: int | None = None
        self._ensure_dirs()

    def _coerce_path(self, value: Path | str, relative_to: Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = relative_to / path
        return path.resolve()

    def _ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.market_dir.mkdir(parents=True, exist_ok=True)
        catalog_parent = self.catalog_path.parent
        catalog_parent.mkdir(parents=True, exist_ok=True)

    def configure_paths(self, paths: dict | None) -> None:
        """Apply path overrides from configuration."""

        if not isinstance(paths, dict):
            self._ensure_dirs()
            return

        base_override = paths.get("base_dir")
        if base_override is not None:
            base_dir = self._coerce_path(base_override, self._base_anchor)
        else:
            base_dir = self._base_anchor
        self.base_dir = base_dir

        data_dir_value = paths.get("data_dir")
        users_dir_value = paths.get("users_dir") or paths.get("users")
        markets_dir_value = paths.get("markets_dir") or paths.get("markets")
        catalog_value = paths.get("catalog")
        assets_value = paths.get("assets")

        data_dir = base_dir / "data"
        users_dir = data_dir / "users"
        markets_dir = data_dir / "markets"

        if data_dir_value is not None:
            candidate = self._coerce_path(data_dir_value, base_dir)
            lowered = candidate.name.lower()
            if lowered == "users" and users_dir_value is None:
                users_dir = candidate
                data_dir = candidate.parent
                if markets_dir_value is None:
                    markets_dir = data_dir / "markets"
            elif lowered == "markets" and markets_dir_value is None:
                markets_dir = candidate
                data_dir = candidate.parent
                if users_dir_value is None:
                    users_dir = data_dir / "users"
            else:
                data_dir = candidate
                users_dir = candidate / "users"
                markets_dir = candidate / "markets"

        if users_dir_value is not None:
            users_dir = self._coerce_path(users_dir_value, base_dir)
        if markets_dir_value is not None:
            markets_dir = self._coerce_path(markets_dir_value, base_dir)

        self.data_dir = data_dir
        self.users_dir = users_dir
        self.market_dir = markets_dir

        if catalog_value is not None:
            self.catalog_path = self._coerce_path(catalog_value, base_dir)
        else:
            self.catalog_path = data_dir / "girls_catalog.json"
        self._catalog_cache = None
        self._catalog_mtime = None

        if assets_value is not None:
            self.assets_dir = self._coerce_path(assets_value, base_dir)
        else:
            self.assets_dir = base_dir / "assets" / "girls"

        self._ensure_dirs()

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
        path = self.catalog_path
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            self._catalog_cache = None
            self._catalog_mtime = None
            raise FileNotFoundError(f"Catalog not found: {path}")

        if self._catalog_cache is not None and self._catalog_mtime == mtime:
            return self._catalog_cache

        data = self.read_json(path)
        if data is None:
            raise FileNotFoundError(f"Catalog not found: {path}")

        self._catalog_cache = data
        self._catalog_mtime = mtime
        return data

    def iter_user_ids(self) -> Iterable[int]:
        for entry in self.users_dir.glob("*.json"):
            try:
                yield int(entry.stem)
            except ValueError:
                continue
