from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

from .audio import WAV_SAMPLE_WIDTHS, list_devices, record_for_seconds, select_input_device, wav_duration_seconds
from .config import load_config, write_default_config
from .notes import generate_notes
from .session import (
    append_log,
    clear_state,
    make_session,
    process_alive,
    read_state,
    resolve_session,
    update_metadata,
    write_state,
)
from .transcribe import transcribe_session


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return
    args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meeting")
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Write a default config file")
    init.set_defaults(handler=cmd_init)

    devices = sub.add_parser("devices", help="List audio devices")
    devices.set_defaults(handler=cmd_devices)

    doctor = sub.add_parser("doctor", help="Check local readiness")
    doctor.set_defaults(handler=cmd_doctor)

    record = sub.add_parser("record", help="Record a short test WAV")
    record.add_argument("--seconds", type=float, default=30.0)
    record.add_argument("--output", type=Path)
    record.set_defaults(handler=cmd_record)

    start = sub.add_parser("start", help="Start recording a meeting")
    start.add_argument("title", nargs="?", help="Optional meeting title")
    start.set_defaults(handler=cmd_start)

    stop = sub.add_parser("stop", help="Stop the active recording")
    stop.add_argument("--process", action="store_true", help="Run configured downstream processing after stop")
    stop.set_defaults(handler=cmd_stop)

    status = sub.add_parser("status", help="Show active recording status")
    status.add_argument("--json", action="store_true", help="Write machine-readable status JSON")
    status.set_defaults(handler=cmd_status)

    inspect = sub.add_parser("inspect", help="Inspect a session's artifacts")
    inspect.add_argument("session", nargs="?", default="latest")
    inspect.set_defaults(handler=cmd_inspect)

    transcribe = sub.add_parser("transcribe", help="Transcribe a session")
    transcribe.add_argument("session", nargs="?", default="latest")
    transcribe.add_argument("--provider", default=None)
    transcribe.set_defaults(handler=cmd_transcribe)

    notes = sub.add_parser("notes", help="Generate notes for a session")
    notes.add_argument("session", nargs="?", default="latest")
    notes.add_argument("--provider", default=None)
    notes.set_defaults(handler=cmd_notes)

    return parser


def cmd_init(args: argparse.Namespace) -> None:
    path = write_default_config(args.config)
    print(f"Config ready: {path}")


def cmd_devices(args: argparse.Namespace) -> None:
    _config(args)
    for device in list_devices():
        marker = "input" if device["max_input_channels"] > 0 else "     "
        print(
            f"{device['index']:>3} {marker} "
            f"in={device['max_input_channels']} out={device['max_output_channels']} "
            f"rate={device['default_samplerate']:.0f} {device['name']}"
        )


def cmd_doctor(args: argparse.Namespace) -> None:
    config = _config(args)
    failures = 0

    def check(label: str, ok: bool, detail: str, required: bool = True) -> None:
        nonlocal failures
        status = "OK" if ok else ("MISSING" if required else "WARN")
        print(f"{status:7} {label}: {detail}")
        if required and not ok:
            failures += 1

    check("Python", True, sys.version.split()[0])
    try:
        import sounddevice  # noqa: F401

        import numpy  # noqa: F401

        check("Audio package", True, "sounddevice and numpy import")
    except ImportError:
        check("Audio package", False, "install with: python -m pip install -e '.[audio]'")

    openai_key_set = bool(os.environ.get("OPENAI_API_KEY"))
    check("OpenAI key", openai_key_set, "OPENAI_API_KEY is set" if openai_key_set else "set OPENAI_API_KEY")
    pi_path = shutil.which(config.notes.pi_command)
    pi_required = config.notes.provider == "pi"
    check("Pi command", bool(pi_path), pi_path or f"{config.notes.pi_command} not found on PATH", required=pi_required)
    if pi_path:
        check("Pi launch", _pi_version_ok(pi_path), "pi --version runs", required=pi_required)
    check("Output root", True, str(config.output.root_dir))
    if config.notes.provider == "pi" and config.notes.pi_provider == "openai":
        check(
            "Pi OpenAI key",
            openai_key_set,
            "OPENAI_API_KEY is set" if openai_key_set else "set OPENAI_API_KEY for Pi provider=openai",
        )
    check(
        "Audio device config",
        bool(config.audio.device_name),
        config.audio.device_name or "not set; default input will be used",
        required=False,
    )
    if config.audio.device_name:
        try:
            device_index = select_input_device(config.audio.device_name)
            check("Audio device match", True, f"input index {device_index}")
        except SystemExit as exc:
            check("Audio device match", False, str(exc))
    check(
        "Audio dtype",
        config.audio.dtype in WAV_SAMPLE_WIDTHS,
        config.audio.dtype if config.audio.dtype in WAV_SAMPLE_WIDTHS else f"{config.audio.dtype}; use int16 or int32",
    )

    if failures:
        raise SystemExit(1)


def cmd_record(args: argparse.Namespace) -> None:
    config = _config(args)
    output = args.output or Path.cwd() / f"recording-test-{datetime.now():%Y%m%d-%H%M%S}.wav"
    print(f"Recording {args.seconds:g}s to {output}")
    record_for_seconds(output, config.audio, args.seconds)
    print(f"Wrote {output}")


def cmd_start(args: argparse.Namespace) -> None:
    config = _config(args)
    state = read_state()
    if state.get("pid") and process_alive(int(state["pid"])):
        raise SystemExit(f"Recording already active: pid={state['pid']} session={state.get('session_dir')}")

    paths = make_session(config, args.title)
    cmd = [
        sys.executable,
        "-m",
        "wave_notes.recorder",
        "--session",
        str(paths.root),
        "--device-name",
        config.audio.device_name or "",
        "--sample-rate",
        str(config.audio.sample_rate),
        "--channels",
        str(config.audio.channels),
        "--dtype",
        config.audio.dtype,
    ]
    log_handle = paths.log.open("a", encoding="utf-8")
    popen_kwargs = _recorder_popen_kwargs()
    process = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, **popen_kwargs)
    write_state(
        {
            "pid": process.pid,
            "session_dir": str(paths.root),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    append_log(paths, f"started recorder pid={process.pid}")
    print(f"Recording started: {paths.root}")
    print(f"PID: {process.pid}")


def cmd_stop(args: argparse.Namespace) -> None:
    config = _config(args)
    state = read_state()
    if not state.get("pid") or not state.get("session_dir"):
        raise SystemExit("No active recording state found.")

    pid = int(state["pid"])
    paths = resolve_session(config, str(state["session_dir"]))
    paths.stop_signal.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    if process_alive(pid):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process_alive(pid):
            time.sleep(0.2)
        if process_alive(pid):
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
        if process_alive(pid) and hasattr(signal, "SIGKILL"):
            os.kill(pid, signal.SIGKILL)

    clear_state()
    update_metadata(paths, status="recorded", stopped_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    append_log(paths, "stop command completed")
    print(f"Recording stopped: {paths.root}")

    should_process = args.process or config.after_stop.transcribe or config.after_stop.notes
    if should_process:
        if args.process or config.after_stop.transcribe:
            transcribe_session(paths, config)
            print("Transcription complete")
        if args.process or config.after_stop.notes:
            generate_notes(paths, config)
            print("Notes complete")


def cmd_status(args: argparse.Namespace) -> None:
    config = _config(args)
    payload = _status_payload(config)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not payload["pid"] and not payload["session_path"]:
        print("No active recording.")
        return
    print(f"Recording active: {payload['active']}")
    print(f"PID: {payload['pid'] or 0}")
    print(f"Session: {payload['session_path']}")
    print(f"Started: {payload['started_at']}")
    if payload["elapsed_seconds"] is not None:
        print(f"Elapsed seconds: {payload['elapsed_seconds']}")
    if payload["latest_session_path"]:
        print(f"Latest session: {payload['latest_session_path']}")


def cmd_inspect(args: argparse.Namespace) -> None:
    config = _config(args)
    paths = resolve_session(config, args.session)
    metadata = _read_metadata(paths.metadata)
    print(f"Session: {paths.root}")
    print(f"Status: {metadata.get('status', 'unknown')}")
    print(f"Title: {metadata.get('title') or '(untitled)'}")
    print(f"Created: {metadata.get('created_at', 'unknown')}")
    print(f"Stopped: {metadata.get('stopped_at', 'not stopped')}")
    _print_artifact("Audio", paths.audio, _audio_detail(paths.audio))
    _print_artifact("Transcript JSON", paths.root / "transcript.openai.json")
    _print_artifact("Transcript Markdown", paths.root / "transcript.openai.md")
    _print_artifact("Notes Markdown", paths.root / "notes.md")
    _print_artifact("Notes JSON", paths.root / "notes.json")
    _print_artifact("Log", paths.log)


def cmd_transcribe(args: argparse.Namespace) -> None:
    config = _config(args)
    paths = resolve_session(config, args.session)
    output = transcribe_session(paths, config, args.provider)
    print(f"Wrote {output}")


def cmd_notes(args: argparse.Namespace) -> None:
    config = _config(args)
    paths = resolve_session(config, args.session)
    output = generate_notes(paths, config, args.provider)
    print(f"Wrote {output}")


def _config(args: argparse.Namespace):
    return load_config(args.config)


def _status_payload(config) -> dict:
    state = read_state()
    pid = _state_pid(state)
    started_at = state.get("started_at")
    return {
        "active": process_alive(pid) if pid else False,
        "pid": pid,
        "session_path": state.get("session_dir") or None,
        "started_at": started_at or None,
        "elapsed_seconds": _elapsed_seconds(started_at),
        "latest_session_path": _latest_session_path(config),
    }


def _state_pid(state: dict) -> int | None:
    try:
        pid = int(state.get("pid", 0))
    except (TypeError, ValueError):
        return None
    return pid or None


def _elapsed_seconds(started_at: str | None) -> int | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.astimezone()
    return max(0, int((datetime.now().astimezone() - started).total_seconds()))


def _latest_session_path(config) -> str | None:
    root = config.output.root_dir
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


def _recorder_popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _read_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _print_artifact(label: str, path: Path, detail: str | None = None) -> None:
    if not path.exists():
        print(f"{label}: missing")
        return
    suffix = f" ({detail})" if detail else ""
    print(f"{label}: {path}{suffix}")


def _audio_detail(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return f"{wav_duration_seconds(path):.1f}s, {path.stat().st_size} bytes"
    except (EOFError, wave.Error):
        return f"{path.stat().st_size} bytes, unreadable WAV header"


def _pi_version_ok(pi_path: str) -> bool:
    cmd = _windows_command_shim(pi_path, ["--version"])
    try:
        completed = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _windows_command_shim(command: str, args: list[str]) -> list[str]:
    suffix = Path(command).suffix.casefold()
    if os.name == "nt" and suffix in {".bat", ".cmd"}:
        return ["cmd.exe", "/d", "/c", subprocess.list2cmdline([command, *args])]
    return [command, *args]
