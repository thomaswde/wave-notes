from __future__ import annotations

import json
from pathlib import Path

from .audio import split_wav_fixed, wav_duration_seconds
from .config import AppConfig
from .session import SessionPaths, append_log, update_metadata, write_json


def transcribe_session(paths: SessionPaths, config: AppConfig, provider: str | None = None) -> Path:
    provider_name = provider or config.stt.default_provider
    if provider_name != "openai":
        raise SystemExit(f"Unsupported STT provider for this cut: {provider_name}")
    if not paths.audio.exists():
        raise SystemExit(f"Audio file not found: {paths.audio}")

    append_log(paths, f"transcription started provider={provider_name}")
    chunks = split_wav_fixed(paths.audio, paths.chunks, config.stt.chunk_seconds)
    segments = _transcribe_openai_chunks(chunks, config.stt.openai_model, config.stt.chunk_seconds)
    payload = {
        "provider": provider_name,
        "model": config.stt.openai_model,
        "source_audio": "audio.wav",
        "chunk_seconds": config.stt.chunk_seconds,
        "segments": segments,
    }

    json_path = paths.root / "transcript.openai.json"
    md_path = paths.root / "transcript.openai.md"
    write_json(json_path, payload)
    md_path.write_text(render_transcript_markdown(payload), encoding="utf-8")
    update_metadata(paths, transcript={"provider": provider_name, "json": json_path.name, "markdown": md_path.name})
    append_log(paths, f"transcription finished provider={provider_name} segments={len(segments)}")
    return json_path


def render_transcript_markdown(payload: dict) -> str:
    lines = [
        "# Transcript",
        "",
        f"- Provider: {payload['provider']}",
        f"- Model: {payload['model']}",
        f"- Source: {payload['source_audio']}",
        "",
    ]
    for segment in payload["segments"]:
        lines.append(
            f"## {segment['index']:03d} "
            f"[{_fmt_time(segment['start_seconds'])} - {_fmt_time(segment['end_seconds'])}]"
        )
        lines.append("")
        lines.append(segment["text"].strip())
        lines.append("")
    return "\n".join(lines)


def _transcribe_openai_chunks(chunks: list[Path], model: str, chunk_seconds: int) -> list[dict]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("OpenAI STT requires the 'openai' package. Install with: python -m pip install -e .") from exc

    client = OpenAI()
    segments: list[dict] = []
    elapsed = 0.0
    for index, chunk_path in enumerate(chunks, start=1):
        duration = wav_duration_seconds(chunk_path)
        with chunk_path.open("rb") as handle:
            response = client.audio.transcriptions.create(
                model=model,
                file=handle,
                response_format="json",
            )
        text = _response_text(response)
        segments.append(
            {
                "index": index,
                "start_seconds": round(elapsed, 3),
                "end_seconds": round(elapsed + duration, 3),
                "text": text,
                "provider": "openai",
                "chunk_file": f"chunks/{chunk_path.name}",
            }
        )
        elapsed += duration or chunk_seconds
    return segments


def _response_text(response: object) -> str:
    if hasattr(response, "text"):
        return str(getattr(response, "text"))
    if isinstance(response, dict):
        return str(response.get("text", ""))
    return json.dumps(response, default=str)


def _fmt_time(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
