from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import default_config_path


POLL_SECONDS = 2


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def detail(self) -> str:
        return (self.stderr or self.stdout).strip()


@dataclass
class TrayState:
    active: bool = False
    pid: int | None = None
    session_path: str | None = None
    started_at: str | None = None
    elapsed_seconds: int | None = None
    latest_session_path: str | None = None
    last_error: str | None = None
    busy: bool = False
    quit_requested: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def main() -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise SystemExit(
            "Tray support is not installed. Install it with: python -m pip install -e .[tray]"
        ) from exc

    controller = TrayController(pystray, make_icon_image(Image, ImageDraw))
    controller.run()


class TrayController:
    def __init__(
        self,
        pystray_module: Any,
        image: Any,
        runner: Callable[[list[str]], CommandResult] | None = None,
    ) -> None:
        self.pystray = pystray_module
        self.image = image
        self.runner = runner or run_meeting
        self.state = TrayState()
        self.icon = self.pystray.Icon("wave-notes", self.image, "Wave Notes", self._menu())

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.icon.run()

    def _menu(self) -> Any:
        item = self.pystray.MenuItem
        return self.pystray.Menu(
            item(lambda _: self._status_label(), self.show_status, enabled=False),
            item("Refresh Status", self.show_status),
            item("Start Recording", self.start_recording, enabled=lambda _: not self._is_active_or_busy()),
            item("Stop Recording", self.stop_recording, enabled=lambda _: self._is_active_and_idle()),
            item("Stop and Process", self.stop_and_process, enabled=lambda _: self._is_active_and_idle()),
            self.pystray.Menu.SEPARATOR,
            item("Open Latest Session", self.open_latest, enabled=lambda _: self._has_latest_session()),
            item("Settings", self.open_settings),
            item("Doctor", self.run_doctor),
            self.pystray.Menu.SEPARATOR,
            item("Quit", self.quit),
        )

    def start_recording(self, *_: Any) -> None:
        self._run_action("Starting recording", ["start", "--json"], self._handle_start)

    def stop_recording(self, *_: Any) -> None:
        self._run_action("Stopping recording", ["stop", "--json"], self._handle_stop)

    def stop_and_process(self, *_: Any) -> None:
        self._run_action("Stopping and processing", ["stop", "--process", "--json"], self._handle_stop)

    def show_status(self, *_: Any) -> None:
        self._refresh_status(notify=True)

    def open_latest(self, *_: Any) -> None:
        self._run_action("Opening latest session", ["open", "latest"], lambda _result: self._notify("Opened latest session"))

    def run_doctor(self, *_: Any) -> None:
        self._run_action("Running doctor", ["doctor"], self._handle_doctor)

    def open_settings(self, *_: Any) -> None:
        def action() -> None:
            self._set_busy(True)
            try:
                init_result = self.runner(["init"])
                if not init_result.ok:
                    self._notify("Settings unavailable", init_result.detail)
                    return
                open_path(default_config_path())
                self._notify("Settings opened", str(default_config_path()))
            finally:
                self._set_busy(False)

        threading.Thread(target=action, daemon=True).start()

    def quit(self, *_: Any) -> None:
        with self.state.lock:
            self.state.quit_requested = True
        self.icon.stop()

    def _poll_loop(self) -> None:
        while True:
            with self.state.lock:
                if self.state.quit_requested:
                    return
            self._refresh_status(notify=False)
            time.sleep(POLL_SECONDS)

    def _refresh_status(self, notify: bool) -> None:
        result = self.runner(["status", "--json"])
        if not result.ok:
            with self.state.lock:
                self.state.last_error = result.detail
            if notify:
                self._notify("Status unavailable", result.detail)
            self._update_icon()
            return

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            with self.state.lock:
                self.state.last_error = "Could not parse meeting status JSON."
            if notify:
                self._notify("Status unavailable", self.state.last_error)
            self._update_icon()
            return

        with self.state.lock:
            self.state.active = bool(payload.get("active"))
            self.state.pid = payload.get("pid")
            self.state.session_path = payload.get("session_path")
            self.state.started_at = payload.get("started_at")
            self.state.elapsed_seconds = payload.get("elapsed_seconds")
            self.state.latest_session_path = payload.get("latest_session_path")
            self.state.last_error = None

        if notify:
            self._notify("Wave Notes", self._status_label())
        self._update_icon()

    def _run_action(
        self,
        title: str,
        args: list[str],
        on_success: Callable[[CommandResult], None],
    ) -> None:
        def action() -> None:
            self._set_busy(True)
            try:
                result = self.runner(args)
                if result.ok:
                    on_success(result)
                else:
                    self._notify(title, result.detail or "Command failed.")
                self._refresh_status(notify=False)
            finally:
                self._set_busy(False)

        threading.Thread(target=action, daemon=True).start()

    def _handle_start(self, result: CommandResult) -> None:
        payload = _json_payload(result)
        session_path = payload.get("session_path") if payload else None
        self._notify("Recording started", session_path or "Wave Notes is recording.")

    def _handle_stop(self, result: CommandResult) -> None:
        payload = _json_payload(result)
        session_path = payload.get("session_path") if payload else None
        processed = bool(payload.get("processed")) if payload else False
        title = "Processing complete" if processed else "Recording stopped"
        self._notify(title, session_path or "Session complete.")

    def _handle_doctor(self, result: CommandResult) -> None:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self._notify("Doctor complete", lines[-1] if lines else "Readiness checks finished.")

    def _notify(self, title: str, message: str | None = None) -> None:
        try:
            self.icon.notify(message or "", title)
        except (AttributeError, NotImplementedError):
            pass

    def _update_icon(self) -> None:
        self.icon.title = self._status_label()
        try:
            self.icon.update_menu()
        except AttributeError:
            pass

    def _status_label(self) -> str:
        with self.state.lock:
            if self.state.busy:
                return "Wave Notes: Working..."
            if self.state.last_error:
                return "Wave Notes: Needs attention"
            if self.state.active:
                elapsed = _format_elapsed(self.state.elapsed_seconds)
                return f"Wave Notes: Recording {elapsed}" if elapsed else "Wave Notes: Recording"
            return "Wave Notes: Idle"

    def _is_active_or_busy(self) -> bool:
        with self.state.lock:
            return self.state.active or self.state.busy

    def _is_active_and_idle(self) -> bool:
        with self.state.lock:
            return self.state.active and not self.state.busy

    def _has_latest_session(self) -> bool:
        with self.state.lock:
            return bool(self.state.latest_session_path) and not self.state.busy

    def _set_busy(self, busy: bool) -> None:
        with self.state.lock:
            self.state.busy = busy
        self._update_icon()


def run_meeting(args: list[str]) -> CommandResult:
    cmd = meeting_command(args)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    completed = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def meeting_command(args: list[str]) -> list[str]:
    executable = shutil.which("meeting")
    if executable:
        return [executable, *args]
    return [sys.executable, "-m", "wave_notes", *args]


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
        return
    subprocess.run(["xdg-open", str(path)], check=False)


def make_icon_image(image_cls: Any, draw_cls: Any) -> Any:
    image = image_cls.new("RGBA", (64, 64), (24, 31, 42, 0))
    draw = draw_cls.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(18, 29, 46, 255))
    draw.ellipse((22, 16, 42, 36), fill=(99, 190, 123, 255))
    draw.rounded_rectangle((28, 32, 36, 48), radius=4, fill=(99, 190, 123, 255))
    draw.line((20, 48, 44, 48), fill=(99, 190, 123, 255), width=4)
    return image


def _json_payload(result: CommandResult) -> dict[str, Any]:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _format_elapsed(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    minutes, remaining = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:d}:{remaining:02d}"


if __name__ == "__main__":
    main()
