from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, default_app_dir


STATE_FILE = "state.json"


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    audio: Path
    metadata: Path
    log: Path
    chunks: Path
    stop_signal: Path


def make_session(config: AppConfig, title: str | None = None) -> SessionPaths:
    now = datetime.now().astimezone()
    title_text = title.strip() if title else ""
    slug = slugify(title_text) if title_text else ""
    folder = f"{now:%Y-%m-%d_%H%M}_{slug}" if slug else f"{now:%Y-%m-%d_%H%M}"
    root = config.output.root_dir / folder
    paths = paths_for(root)
    paths.root.mkdir(parents=True, exist_ok=False)
    paths.chunks.mkdir(parents=True, exist_ok=True)

    metadata = {
        "title": title_text or None,
        "slug": slug,
        "session_dir": str(paths.root),
        "created_at": now.isoformat(timespec="seconds"),
        "status": "created",
        "audio": {
            "file": "audio.wav",
            "device_name": config.audio.device_name,
            "sample_rate": config.audio.sample_rate,
            "channels": config.audio.channels,
            "dtype": config.audio.dtype,
        },
    }
    write_json(paths.metadata, metadata)
    paths.log.write_text(f"{now.isoformat(timespec='seconds')} session created\n", encoding="utf-8")
    return paths


def paths_for(root: Path) -> SessionPaths:
    return SessionPaths(
        root=root,
        audio=root / "audio.wav",
        metadata=root / "metadata.json",
        log=root / "processing.log",
        chunks=root / "chunks",
        stop_signal=root / ".stop-recording",
    )


def latest_session(config: AppConfig) -> SessionPaths:
    root = config.output.root_dir
    if not root.exists():
        raise SystemExit(f"No output directory exists yet: {root}")
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        raise SystemExit(f"No sessions found in {root}")
    return paths_for(max(candidates, key=lambda p: p.stat().st_mtime))


def resolve_session(config: AppConfig, value: str) -> SessionPaths:
    if value == "latest":
        return latest_session(config)
    path = Path(value).expanduser()
    if not path.is_absolute():
        direct = config.output.root_dir / path
        path = direct if direct.exists() else path.resolve()
    if not path.exists() or not path.is_dir():
        raise SystemExit(f"Session directory not found: {path}")
    return paths_for(path)


def state_path() -> Path:
    return default_app_dir() / STATE_FILE


def read_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)


def clear_state() -> None:
    path = state_path()
    if path.exists():
        path.unlink()


def update_metadata(paths: SessionPaths, **updates: Any) -> None:
    metadata = {}
    if paths.metadata.exists():
        metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    metadata.update(updates)
    write_json(paths.metadata, metadata)


def append_log(paths: SessionPaths, message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with paths.log.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "meeting"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
