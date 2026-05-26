from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from wave_notes.audio import split_wav_fixed
from wave_notes.config import load_config
from wave_notes.session import slugify


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


if __name__ == "__main__":
    unittest.main()
