from __future__ import annotations

import queue
import signal
import threading
import time
import wave
from pathlib import Path
from typing import Any

from .config import AudioConfig


WAV_SAMPLE_WIDTHS = {
    "int16": 2,
    "int32": 4,
}


def list_devices() -> list[dict[str, Any]]:
    sd = _sounddevice()
    devices = sd.query_devices()
    result: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        result.append(
            {
                "index": index,
                "name": device.get("name", ""),
                "max_input_channels": int(device.get("max_input_channels", 0)),
                "max_output_channels": int(device.get("max_output_channels", 0)),
                "default_samplerate": float(device.get("default_samplerate", 0)),
            }
        )
    return result


def select_input_device(device_name: str | None) -> int | None:
    if not device_name:
        return None

    candidates = [d for d in list_devices() if d["max_input_channels"] > 0]
    lowered = device_name.casefold()
    exact = [d for d in candidates if d["name"].casefold() == lowered]
    if exact:
        return int(exact[0]["index"])
    partial = [d for d in candidates if lowered in d["name"].casefold()]
    if len(partial) == 1:
        return int(partial[0]["index"])
    if len(partial) > 1:
        names = ", ".join(f"{d['index']}:{d['name']}" for d in partial)
        raise SystemExit(f"Device name matched multiple inputs: {names}")
    raise SystemExit(f"No input device matched configured name: {device_name}")


def record_until_stopped(audio_path: Path, config: AudioConfig, stop_signal: Path | None = None) -> None:
    sd = _sounddevice()
    sample_width = _wav_sample_width(config.dtype)
    device = select_input_device(config.device_name)
    stop_event = threading.Event()
    audio_queue: queue.SimpleQueue[bytes] = queue.SimpleQueue()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "wb") as wav:
        wav.setnchannels(config.channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(config.sample_rate)

        def callback(indata: Any, frames: int, _time_info: Any, status: Any) -> None:
            if status:
                print(status, flush=True)
            audio_queue.put(indata.tobytes())

        with sd.InputStream(
            samplerate=config.sample_rate,
            channels=config.channels,
            dtype=config.dtype,
            device=device,
            callback=callback,
        ):
            while not stop_event.is_set():
                if stop_signal and stop_signal.exists():
                    stop_event.set()
                    break
                _write_queued_audio(wav, audio_queue)
                time.sleep(0.1)
            _write_queued_audio(wav, audio_queue)
        _write_queued_audio(wav, audio_queue)


def record_for_seconds(audio_path: Path, config: AudioConfig, seconds: float) -> None:
    sd = _sounddevice()
    sample_width = _wav_sample_width(config.dtype)
    device = select_input_device(config.device_name)
    frames = int(config.sample_rate * seconds)
    data = sd.rec(
        frames,
        samplerate=config.sample_rate,
        channels=config.channels,
        dtype=config.dtype,
        device=device,
    )
    sd.wait()
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "wb") as wav:
        wav.setnchannels(config.channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(config.sample_rate)
        wav.writeframes(data.tobytes())


def split_wav_fixed(input_path: Path, chunks_dir: Path, chunk_seconds: int) -> list[Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for existing in chunks_dir.glob("*.wav"):
        existing.unlink()

    chunks: list[Path] = []
    with wave.open(str(input_path), "rb") as source:
        params = source.getparams()
        frames_per_chunk = int(params.framerate * chunk_seconds)
        index = 1
        while True:
            frames = source.readframes(frames_per_chunk)
            if not frames:
                break
            chunk_path = chunks_dir / f"{index:06d}.wav"
            with wave.open(str(chunk_path), "wb") as chunk:
                chunk.setparams(params)
                chunk.writeframes(frames)
            chunks.append(chunk_path)
            index += 1
    return chunks


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def _sounddevice() -> Any:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise SystemExit(
            "Audio capture requires the optional dependency 'sounddevice'. "
            "Install with: python -m pip install -e '.[audio]'"
        ) from exc
    return sd


def _write_queued_audio(wav: wave.Wave_write, audio_queue: queue.SimpleQueue[bytes]) -> None:
    while True:
        try:
            chunk = audio_queue.get_nowait()
        except queue.Empty:
            break
        wav.writeframesraw(chunk)


def _wav_sample_width(dtype: str) -> int:
    try:
        return WAV_SAMPLE_WIDTHS[dtype]
    except KeyError as exc:
        supported = ", ".join(sorted(WAV_SAMPLE_WIDTHS))
        raise SystemExit(
            f"Unsupported audio dtype for WAV recording: {dtype}. "
            f"Use one of: {supported}."
        ) from exc
