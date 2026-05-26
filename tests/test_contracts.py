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
from wave_notes.session import make_session, slugify, write_state


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

    def test_start_title_is_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start"])

        self.assertIsNone(args.title)

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
