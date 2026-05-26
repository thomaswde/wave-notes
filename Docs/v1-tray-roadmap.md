# V1 Tray Utility Roadmap

## Target Shape

Version 1 should be a Windows tray utility backed by the existing `meeting` CLI
engine. The tray app should start with Windows, expose quick recording controls,
and keep all session artifacts as ordinary files.

## Core Tray Actions

- Start recording immediately.
- Stop recording.
- Stop and process the recording.
- Show current recording status.
- Open the latest session folder.
- Open settings.

## Settings GUI

The settings tool should edit the same config file used by the CLI:

```text
~\.wave-notes\config.toml
```

The first settings screen should cover:

- Audio input device.
- Output folder.
- STT provider and model.
- Notes provider, model, and thinking level.
- After-stop processing toggles.

## Meeting Titles

V1 should allow recordings to start without a title. Untitled sessions use a
timestamp-only folder name first:

```text
2026-05-26_1430
```

During processing, an AI title step can generate a concise title from the
transcript or notes. The app can then append the title to the timestamp:

```text
2026-05-26_1430_product-roadmap-review
```

Calendar integration is a strong future enhancement, but it is not required for
V1.

## Engineering Notes

- Keep the CLI as the durable engine and let the tray call it.
- Prefer small, observable commands over hidden app-only behavior.
- Preserve rerunnable stages: recording, transcription, notes, and title
  generation should remain independently callable.
- Continue using portable session folders as the storage contract.
