"""Percorsi su disco. Tutto sotto %LOCALAPPDATA%\Sici29Hub."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Sici29Hub"


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


def data_dir() -> Path:
    d = _local_appdata() / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    return _sub("cache")


def covers_dir() -> Path:
    return _sub("covers")


def downloads_dir() -> Path:
    return _sub("downloads")


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "hub.log"


def resource_path(*parts: str) -> Path:
    """Risorsa inclusa nell'eseguibile (funziona sia da sorgente che da EXE)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).joinpath(*parts)
    return Path(__file__).resolve().parent.joinpath(*parts)
