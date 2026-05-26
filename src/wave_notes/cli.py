from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .audio import WAV_SAMPLE_WIDTHS, list_devices, record_for_seconds
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
    start.add_argument("title")
    start.set_defaults(handler=cmd_start)

    stop = sub.add_parser("stop", help="Stop the active recording")
    stop.add_argument("--process", action="store_true", help="Run configured downstream processing after stop")
    stop.set_defaults(handler=cmd_stop)

    status = sub.add_parser("status", help="Show active recording status")
    status.set_defaults(handler=cmd_status)

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
    check("Pi command", bool(pi_path), pi_path or f"{config.notes.pi_command} not found on PATH")
    check("Output root", True, str(config.output.root_dir))
    check(
        "Audio device config",
        bool(config.audio.device_name),
        config.audio.device_name or "not set; default input will be used",
        required=False,
    )
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
    _config(args)
    state = read_state()
    if not state:
        print("No active recording.")
        return
    pid = int(state.get("pid", 0))
    alive = process_alive(pid) if pid else False
    print(f"Recording active: {alive}")
    print(f"PID: {pid}")
    print(f"Session: {state.get('session_dir')}")
    print(f"Started: {state.get('started_at')}")


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


def _recorder_popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}
