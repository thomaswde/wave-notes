from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from wave_notes.audio import _wav_sample_width, split_wav_fixed
from wave_notes.config import AppConfig, OutputConfig, load_config
from wave_notes.cli import build_parser
from wave_notes.notes import _pi_subprocess_command, _pi_thinking_arg
from wave_notes.session import make_session, slugify


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
