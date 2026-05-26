from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import AppConfig
from .session import SessionPaths, append_log, update_metadata, write_json


def generate_notes(paths: SessionPaths, config: AppConfig, provider: str | None = None) -> Path:
    provider_name = provider or config.notes.provider
    transcript = _load_transcript(paths)
    prompt = build_notes_prompt(transcript)
    prompt_path = paths.root / "notes.prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    append_log(paths, f"notes generation started provider={provider_name}")
    if provider_name == "pi":
        markdown = _generate_with_pi(prompt_path, config)
    elif provider_name == "openai":
        markdown = _generate_with_openai(prompt, config)
    else:
        raise SystemExit(f"Unsupported notes provider: {provider_name}")

    notes_md = paths.root / "notes.md"
    notes_json = paths.root / "notes.json"
    notes_md.write_text(markdown.strip() + "\n", encoding="utf-8")
    write_json(notes_json, {"provider": provider_name, "source": transcript.name, "markdown": notes_md.name})
    update_metadata(paths, notes={"provider": provider_name, "markdown": notes_md.name, "json": notes_json.name})
    append_log(paths, f"notes generation finished provider={provider_name}")
    return notes_md


def build_notes_prompt(transcript_path: Path) -> str:
    transcript_text = transcript_path.read_text(encoding="utf-8")
    return f"""You are producing durable meeting notes from a transcript.

Return Markdown only. Use these sections:

# Meeting Notes

## Short Summary

## Key Decisions

## Action Items

Use a table with columns: Owner, Action, Due Date, Evidence. Use "Unassigned" and "Not specified" when needed.

## Open Questions

## Important Context

## Follow-Ups

Keep the notes factual. Do not invent speakers, decisions, owners, or dates.

Transcript:

{transcript_text}
"""


def _generate_with_pi(prompt_path: Path, config: AppConfig) -> str:
    args = [
        "--no-tools",
        "--no-session",
        "--mode",
        "text",
        "-p",
    ]
    if config.notes.pi_provider:
        args.extend(["--provider", config.notes.pi_provider])
    if config.notes.pi_model:
        args.extend(["--model", config.notes.pi_model])
    thinking = _pi_thinking_arg(config.notes.pi_thinking)
    if thinking:
        args.extend(["--thinking", thinking])
    args.append(f"@{prompt_path}")

    cmd = _pi_subprocess_command(config.notes.pi_command, args)
    try:
        completed = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "Pi notes generation failed.\n"
            f"Command not found: {config.notes.pi_command}\n"
            "Set [notes].pi_command to the full path or add Pi to PATH."
        ) from exc
    if completed.returncode != 0:
        raise SystemExit(
            "Pi notes generation failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr:\n{completed.stderr.strip()}"
        )
    return completed.stdout or ""


def _pi_subprocess_command(command: str, args: list[str]) -> list[str]:
    resolved = shutil.which(command) or command
    suffix = Path(resolved).suffix.casefold()
    if os.name == "nt" and suffix in {".bat", ".cmd"}:
        command_line = subprocess.list2cmdline([resolved, *args])
        return ["cmd.exe", "/d", "/c", command_line]
    return [resolved, *args]


def _pi_thinking_arg(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    return "off" if normalized == "none" else normalized


def _generate_with_openai(prompt: str, config: AppConfig) -> str:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=config.notes.openai_model,
        input=prompt,
    )
    text = getattr(response, "output_text", "")
    if text:
        return text
    return json.dumps(response.model_dump(), indent=2)


def _load_transcript(paths: SessionPaths) -> Path:
    candidates = [
        paths.root / "transcript.openai.md",
        paths.root / "transcript.parakeet.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"No transcript markdown found in {paths.root}")
