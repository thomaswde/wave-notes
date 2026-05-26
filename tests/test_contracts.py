from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from wave_notes.audio import _wav_sample_width, split_wav_fixed
from wave_notes.config import AppConfig, OutputConfig, load_config
from wave_notes.cli import build_parser
from wave_notes.notes import _pi_subprocess_command, _pi_thinking_arg
from wave_notes.session import make_session, process_alive, slugify, write_state
from wave_notes.tray import CommandResult, TrayController, _format_elapsed, meeting_command


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items) -> None:
        self.items = items


class FakeIcon:
    def __init__(self, name, image, title, menu) -> None:
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.notifications = []

    def notify(self, message, title) -> None:
        self.notifications.append((title, message))

    def update_menu(self) -> None:
        pass

    def stop(self) -> None:
        pass


class FakePystray:
    Icon = FakeIcon
    Menu = FakeMenu

    @staticmethod
    def MenuItem(text, action=None, enabled=True):
        return {"text": text, "action": action, "enabled": enabled}


class ContractTests(unittest.TestCase):
    def test_relative_output_root_resolves_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            config_path = cwd / "config.toml"
            config_path.write_text('[output]\nroot_dir = "Meetings"\n', encoding="utf-8")
            with patch("pathlib.Path.cwd", return_value=cwd):
                config = load_config(config_path)
            self.assertEqual(config.output.root_dir, (cwd / "Meetings").resolve())

    def test_slugify_meeting_title(self) -> None:
        self.assertEqual(slugify("Product Sync / Windows v1"), "product-sync-windows-v1")

    def test_process_alive_detects_current_process(self) -> None:
        self.assertTrue(process_alive(os.getpid()))

    def test_start_title_is_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start"])

        self.assertIsNone(args.title)

    def test_start_json_is_supported(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start", "--json"])

        self.assertTrue(args.json)

    def test_stop_json_is_supported(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["stop", "--json"])

        self.assertTrue(args.json)

    def test_status_json_is_supported(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "--json"])

        self.assertTrue(args.json)

    def test_latest_json_is_supported(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["latest", "--json"])

        self.assertTrue(args.json)

    def test_open_defaults_to_latest_session(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["open"])

        self.assertEqual(args.session, "latest")

    @patch("wave_notes.tray.shutil.which", return_value=r"C:\Tools\meeting.exe")
    def test_tray_command_prefers_installed_meeting_executable(self, _which) -> None:
        command = meeting_command(["status", "--json"])

        self.assertEqual(command, [r"C:\Tools\meeting.exe", "status", "--json"])

    @patch("wave_notes.tray.sys.executable", r"C:\Python\python.exe")
    @patch("wave_notes.tray.shutil.which", return_value=None)
    def test_tray_command_falls_back_to_module_execution(self, _which) -> None:
        command = meeting_command(["status", "--json"])

        self.assertEqual(command, [r"C:\Python\python.exe", "-m", "wave_notes", "status", "--json"])

    def test_tray_elapsed_format_is_compact(self) -> None:
        self.assertEqual(_format_elapsed(None), None)
        self.assertEqual(_format_elapsed(65), "1:05")
        self.assertEqual(_format_elapsed(3661), "1:01:01")

    def test_tray_command_result_detail_prefers_stderr(self) -> None:
        result = CommandResult(returncode=1, stdout="stdout detail", stderr="stderr detail")

        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "stderr detail")

    def test_tray_controller_refreshes_status_from_json(self) -> None:
        def runner(args: list[str]) -> CommandResult:
            self.assertEqual(args, ["status", "--json"])
            return CommandResult(
                0,
                json.dumps(
                    {
                        "active": True,
                        "pid": 1234,
                        "session_path": "D:/Meetings/session",
                        "started_at": "2026-05-26T12:00:00-04:00",
                        "elapsed_seconds": 125,
                        "latest_session_path": "D:/Meetings/session",
                    }
                ),
                "",
            )

        controller = TrayController(FakePystray, image=None, runner=runner)
        controller._refresh_status(notify=True)

        self.assertEqual(controller.icon.title, "Wave Notes: Recording 2:05")
        self.assertEqual(controller.state.pid, 1234)
        self.assertEqual(controller.icon.notifications[-1], ("Wave Notes", "Wave Notes: Recording 2:05"))

    def test_status_json_reports_inactive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.toml"
            config_path.write_text('[output]\nroot_dir = "Meetings"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "status", "--json"])

            output = io.StringIO()
            with patch.dict(os.environ, {"WAVE_NOTES_HOME": str(Path(temp) / "home")}), redirect_stdout(output):
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertEqual(
                payload,
                {
                    "active": False,
                    "pid": None,
                    "session_path": None,
                    "started_at": None,
                    "elapsed_seconds": None,
                    "latest_session_path": None,
                },
            )

    def test_status_json_reports_active_contract_and_latest_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_root = root / "Meetings"
            config_path = root / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            session = make_session(AppConfig(output=OutputConfig(root_dir=output_root)), "Status test")
            started_at = (datetime.now(timezone.utc) - timedelta(seconds=65)).isoformat(timespec="seconds")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "status", "--json"])

            output = io.StringIO()
            with (
                patch.dict(os.environ, {"WAVE_NOTES_HOME": str(root / "home")}),
                patch("wave_notes.cli.process_alive", return_value=True),
                redirect_stdout(output),
            ):
                write_state({"pid": 1234, "session_dir": str(session.root), "started_at": started_at})
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["active"])
            self.assertEqual(payload["pid"], 1234)
            self.assertEqual(payload["session_path"], str(session.root))
            self.assertEqual(payload["started_at"], started_at)
            self.assertGreaterEqual(payload["elapsed_seconds"], 60)
            self.assertEqual(payload["latest_session_path"], str(session.root))

    def test_start_json_reports_started_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_root = root / "Meetings"
            config_path = root / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "start", "Tray test", "--json"])

            output = io.StringIO()
            with (
                patch.dict(os.environ, {"WAVE_NOTES_HOME": str(root / "home")}),
                patch("wave_notes.cli.subprocess.Popen") as popen,
                redirect_stdout(output),
            ):
                popen.return_value.pid = 4321
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["started"])
            self.assertEqual(payload["pid"], 4321)
            self.assertTrue(payload["session_path"].endswith("_tray-test"))
            self.assertIsInstance(payload["started_at"], str)

    def test_stop_json_reports_stopped_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_root = root / "Meetings"
            config_path = root / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            session = make_session(AppConfig(output=OutputConfig(root_dir=output_root)), "Stopped tray test")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "stop", "--json"])

            output = io.StringIO()
            with (
                patch.dict(os.environ, {"WAVE_NOTES_HOME": str(root / "home")}),
                patch("wave_notes.cli.process_alive", return_value=False),
                redirect_stdout(output),
            ):
                write_state({"pid": 1234, "session_dir": str(session.root)})
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["stopped"])
            self.assertEqual(payload["session_path"], str(session.root))
            self.assertIsInstance(payload["stopped_at"], str)
            self.assertFalse(payload["processed"])
            self.assertIsNone(payload["transcript_path"])
            self.assertIsNone(payload["notes_path"])

    def test_latest_json_reports_missing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            missing_root = Path(temp) / "Meetings"
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{missing_root.as_posix()}"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "latest", "--json"])

            output = io.StringIO()
            with redirect_stdout(output):
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertFalse(payload["exists"])
            self.assertIsNone(payload["session_path"])
            self.assertIn("No output directory exists yet", payload["reason"])

    def test_latest_json_reports_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "Meetings"
            output_root.mkdir()
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "latest", "--json"])

            output = io.StringIO()
            with redirect_stdout(output):
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertFalse(payload["exists"])
            self.assertIsNone(payload["session_path"])
            self.assertIn("No sessions found", payload["reason"])

    def test_latest_json_reports_latest_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "Meetings"
            config = AppConfig(output=OutputConfig(root_dir=output_root))
            first = make_session(config, "First")
            second = make_session(config, "Second")
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "latest", "--json"])

            os.utime(first.root, (1_700_000_000, 1_700_000_000))
            os.utime(second.root, (1_700_000_100, 1_700_000_100))
            output = io.StringIO()
            with redirect_stdout(output):
                args.handler(args)

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["exists"])
            self.assertEqual(payload["session_path"], str(second.root))
            self.assertIsNone(payload["reason"])

    def test_open_session_uses_resolved_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "Meetings"
            session = make_session(AppConfig(output=OutputConfig(root_dir=output_root)), "Open test")
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[output]\nroot_dir = "{output_root.as_posix()}"\n', encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["--config", str(config_path), "open", "latest"])

            output = io.StringIO()
            with patch("wave_notes.cli._open_path") as open_path, redirect_stdout(output):
                args.handler(args)

            open_path.assert_called_once_with(session.root)
            self.assertIn(f"Opened {session.root}", output.getvalue())

    def test_untitled_session_uses_timestamp_only_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = AppConfig(output=OutputConfig(root_dir=Path(temp)))
            session = make_session(config)

            self.assertRegex(session.root.name, r"^\d{4}-\d{2}-\d{2}_\d{4}$")
            self.assertNotIn("_meeting", session.root.name)

    def test_split_wav_fixed_writes_numbered_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "audio.wav"
            chunks = root / "chunks"
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(10)
                wav.writeframes(b"\0\0" * 25)

            result = split_wav_fixed(source, chunks, chunk_seconds=1)

            self.assertEqual([p.name for p in result], ["000001.wav", "000002.wav", "000003.wav"])

    def test_unsupported_recording_dtype_exits_clearly(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Unsupported audio dtype"):
            _wav_sample_width("int24")

    @patch("wave_notes.notes.os.name", "nt")
    @patch("wave_notes.notes.shutil.which", return_value=r"C:\Tools\pi.cmd")
    def test_pi_cmd_shim_runs_through_cmd_exe(self, _which) -> None:
        command = _pi_subprocess_command("pi", ["--version"])

        self.assertEqual(command[:3], ["cmd.exe", "/d", "/c"])
        self.assertIn(r"C:\Tools\pi.cmd", command[3])
        self.assertIn("--version", command[3])

    def test_pi_thinking_none_maps_to_off(self) -> None:
        self.assertEqual(_pi_thinking_arg("none"), "off")
        self.assertEqual(_pi_thinking_arg("medium"), "medium")
        self.assertIsNone(_pi_thinking_arg(""))


if __name__ == "__main__":
    unittest.main()
