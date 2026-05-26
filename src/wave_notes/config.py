from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_DIR_NAME = ".wave-notes"
DEFAULT_CONFIG_NAME = "config.toml"


@dataclass(frozen=True)
class AudioConfig:
    device_name: str | None = None
    sample_rate: int = 48_000
    channels: int = 2
    dtype: str = "int16"


@dataclass(frozen=True)
class OutputConfig:
    root_dir: Path = Path("Meetings")


@dataclass(frozen=True)
class SttConfig:
    default_provider: str = "openai"
    openai_model: str = "gpt-4o-mini-transcribe"
    chunk_seconds: int = 30


@dataclass(frozen=True)
class NotesConfig:
    provider: str = "pi"
    pi_command: str = "pi"
    pi_model: str | None = None
    pi_provider: str | None = None
    pi_thinking: str | None = None
    openai_model: str = "gpt-4.1-mini"


@dataclass(frozen=True)
class AfterStopConfig:
    transcribe: bool = False
    notes: bool = False


@dataclass(frozen=True)
class AppConfig:
    audio: AudioConfig = AudioConfig()
    output: OutputConfig = OutputConfig()
    stt: SttConfig = SttConfig()
    notes: NotesConfig = NotesConfig()
    after_stop: AfterStopConfig = AfterStopConfig()
    config_path: Path | None = None


def default_app_dir() -> Path:
    override = os.environ.get("WAVE_NOTES_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / APP_DIR_NAME


def default_config_path() -> Path:
    return default_app_dir() / DEFAULT_CONFIG_NAME


def load_config(path: Path | None = None) -> AppConfig:
    config_path = (path or default_config_path()).expanduser()
    if not config_path.exists():
        return AppConfig(config_path=config_path)

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    audio = data.get("audio", {})
    output = data.get("output", {})
    stt = data.get("stt", {})
    notes = data.get("notes", {})
    after_stop = data.get("after_stop", {})

    root_dir = _path_value(output.get("root_dir", "Meetings"), base_dir)

    return AppConfig(
        audio=AudioConfig(
            device_name=_optional_str(audio.get("device_name")),
            sample_rate=int(audio.get("sample_rate", 48_000)),
            channels=int(audio.get("channels", 2)),
            dtype=str(audio.get("dtype", "int16")),
        ),
        output=OutputConfig(root_dir=root_dir),
        stt=SttConfig(
            default_provider=str(stt.get("default_provider", "openai")),
            openai_model=str(stt.get("openai_model", "gpt-4o-mini-transcribe")),
            chunk_seconds=int(stt.get("chunk_seconds", 30)),
        ),
        notes=NotesConfig(
            provider=str(notes.get("provider", "pi")),
            pi_command=str(notes.get("pi_command", "pi")),
            pi_model=_optional_str(notes.get("pi_model")),
            pi_provider=_optional_str(notes.get("pi_provider")),
            pi_thinking=_optional_str(notes.get("pi_thinking")),
            openai_model=str(notes.get("openai_model", "gpt-4.1-mini")),
        ),
        after_stop=AfterStopConfig(
            transcribe=bool(after_stop.get("transcribe", False)),
            notes=bool(after_stop.get("notes", False)),
        ),
        config_path=config_path,
    )


def write_default_config(path: Path | None = None) -> Path:
    config_path = (path or default_config_path()).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        return config_path

    config_path.write_text(
        """[audio]
# Set this on Windows to the exact or partial device name, for example:
# device_name = "Wave Link Stream"
device_name = ""
sample_rate = 48000
channels = 2
dtype = "int16"

[output]
root_dir = "Meetings"

[stt]
default_provider = "openai"
openai_model = "gpt-4o-mini-transcribe"
chunk_seconds = 30

[notes]
provider = "pi"
pi_command = "pi"
# Optional, leave blank to use Pi defaults/subscription auth.
pi_model = ""
pi_provider = ""
pi_thinking = ""
openai_model = "gpt-4.1-mini"

[after_stop]
transcribe = false
notes = false
""",
        encoding="utf-8",
    )
    return config_path


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_value(value: Any, base_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()
