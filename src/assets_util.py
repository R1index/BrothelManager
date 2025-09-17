from __future__ import annotations
import os
import unicodedata
from pathlib import Path
from typing import Optional

# Base: <project_root>/assets/girls
# This file is at: <root>/src/assets_util.py
BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_GIRLS_ASSETS = BASE_DIR / "assets" / "girls"
_GIRLS_ASSETS = _DEFAULT_GIRLS_ASSETS


def set_assets_dir(path: Path | str | None) -> None:
    """Override the base directory used to look up girl assets."""

    global _GIRLS_ASSETS
    if path is None:
        _GIRLS_ASSETS = _DEFAULT_GIRLS_ASSETS
        return
    new_path = Path(path).expanduser()
    try:
        _GIRLS_ASSETS = new_path.resolve()
    except OSError:
        # Path may not exist yet — keep the normalized version without resolve().
        _GIRLS_ASSETS = new_path


def get_assets_dir() -> Path:
    """Return the currently configured assets directory."""

    return _GIRLS_ASSETS

def _slug(s: str) -> str:
    """Make safe lowercase slug for filesystem paths."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    return s.strip().lower().replace(" ", "_")

def profile_image_path(girl_name: str, base_id: str = "") -> Optional[str]:
    """
    Look for:
      assets/girls/<name>/<name>_profile.png
      fallback: assets/girls/<base_id>/<base_id>_profile.png
    """
    name_slug = _slug(girl_name)
    base_slug = _slug(base_id) if base_id else None

    base_path = get_assets_dir()

    candidates = []
    if name_slug:
        candidates.append(base_path / name_slug / f"{name_slug}_profile.png")
    if base_slug and base_slug != name_slug:
        candidates.append(base_path / base_slug / f"{base_slug}_profile.png")

    for p in candidates:
        if p.exists():
            return str(p)
    return None

def action_image_path(girl_name: str, base_id: str, main_skill: str, sub_skill: str) -> Optional[str]:
    """
    Look for:
      assets/girls/<name>/<main>/<sub>.png
      fallback: assets/girls/<base_id>/<main>/<sub>.png

    where <main> ∈ human|insect|beast|monster,
          <sub> ∈ anal|vaginal|oral|breast|hand|foot|toy
    """
    name_slug = _slug(girl_name)
    base_slug = _slug(base_id) if base_id else None
    main = _slug(main_skill)
    sub = _slug(sub_skill)

    base_path = get_assets_dir()

    candidates = []
    if name_slug:
        candidates.append(base_path / name_slug / main / f"{sub}.png")
    if base_slug and base_slug != name_slug:
        candidates.append(base_path / base_slug / main / f"{sub}.png")

    for p in candidates:
        if p.exists():
            return str(p)
    return None

def pregnant_profile_image_path(girl_name: str, base_id: str = "") -> Optional[str]:
    """
    Look for:
      assets/girls/<name>/<name>_pregnant.png
      assets/girls/<name>/pregnant.png
      fallback: assets/girls/<base_id>/<base_id>_pregnant.png
    """
    name_slug = _slug(girl_name)
    base_slug = _slug(base_id) if base_id else None

    base_path = get_assets_dir()

    candidates = []
    if name_slug:
        candidates.append(base_path / name_slug / f"{name_slug}_pregnant.png")
        candidates.append(base_path / name_slug / "pregnant.png")
    if base_slug and base_slug != name_slug:
        candidates.append(base_path / base_slug / f"{base_slug}_pregnant.png")

    for p in candidates:
        if p.exists():
            return str(p)
    return None

