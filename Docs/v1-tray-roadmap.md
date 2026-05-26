# V1 Tray Utility Roadmap

## Target Shape

Version 1 should be a Windows tray utility backed by the existing `meeting` CLI
engine. The tray app should start with Windows, expose quick recording controls,
and keep all session artifacts as ordinary files.

The tray should not replace the CLI. It should make the proven CLI workflow feel
native on Windows while preserving the same config file, session folders,
metadata, logs, and rerunnable processing stages.

## Current Foundation

The repository already has a useful CLI-first foundation:

- `meeting init` writes `~\.wave-notes\config.toml`.
- `meeting devices` and `meeting doctor` support local setup checks.
- `meeting start [title]`, `meeting stop`, and `meeting status` manage one active
  recording through file-backed state.
- `meeting status --json` exposes stable tray-pollable recording state.
- `meeting latest`, `meeting latest --json`, and `meeting open latest` expose
  stable latest-session and folder-opening primitives.
- `meeting stop --process`, `meeting transcribe`, and `meeting notes` support the
  downstream pipeline.
- Session folders already preserve ordinary files such as `audio.wav`,
  `metadata.json`, transcripts, notes, chunks, and `processing.log`.

The tray work should therefore focus first on process control, user feedback, and
settings editing rather than reimplementing recording or processing behavior.

## Core Tray Actions

- Start recording immediately.
- Stop recording.
- Stop and process the recording.
- Show current recording status.
- Open the latest session folder.
- Open settings.

## Implementation Plan

### Phase 1: Tray Shell Over Existing Commands

Goal: create the smallest Windows tray app that can call the existing CLI
reliably.

Deliverables:

- Tray icon with menu actions for start, stop, stop and process, status, open
  latest session, settings, and quit.
- Command runner that invokes the local `meeting` executable or
  `python -m wave_notes` consistently from the installed environment.
- Visible success/error notifications for each action.
- Defensive handling for already-recording, no-active-recording, and missing
  config states.

Notes:

- Keep command output observable. When an action fails, surface the useful error
  and leave details in the session log where applicable.
- Prefer one active recording at a time, matching current CLI behavior.

### Phase 2: Structured Status Contract

Goal: make tray state reliable without scraping human-oriented terminal output.

Current CLI contract:

```powershell
meeting status --json
```

The JSON payload includes:

- `active`
- `pid`
- `session_path`
- `started_at`
- `elapsed_seconds`
- `latest_session_path`

Deliverables:

- Keep the machine-readable status mode stable for tray polling.
- Teach the tray to poll status periodically and update icon/menu state.
- Add tests around the status contract so GUI code can depend on it.

### Phase 3: Latest Session and Folder Actions

Goal: make the tray useful immediately after recording.

Current CLI contract:

```powershell
meeting latest
meeting latest --json
meeting open latest
```

`meeting latest --json` returns:

- `exists`
- `session_path`
- `reason`

Deliverables:

- Keep the latest-session command/API stable for tray use.
- Implement "Open latest session folder" from the tray using `meeting open latest`.
- After stop/process, offer a notification action or menu state that opens the
  completed folder.
- Ensure missing output directories and empty history fail gently.

## Pre-Tray Dependency Plan

Before building the system tray utility, the CLI should expose every operation
the tray needs as a stable command. That keeps the tray thin and avoids creating
a second source of truth.

Ready before tray shell:

- Done: status polling via `meeting status --json`.
- Done: latest-session resolution via `meeting latest --json`.
- Done: folder opening via `meeting open latest`.
- Done: recording controls via `meeting start`, `meeting stop`, and
  `meeting stop --process`.
- Done: structured recording control results via `meeting start --json` and
  `meeting stop --json`.
- Done: environment checks via `meeting doctor`.
- Done: observable errors for already-recording, no-active-recording, missing
  output directory, and empty session history.

Nice to settle during the tray shell:

- How the tray surfaces a missing config. The current CLI falls back to defaults
  when `~\.wave-notes\config.toml` does not exist, so the tray can either expose
  `meeting init` or launch settings when first-run configuration is needed.
- Whether `meeting open latest` should be the only folder-opening path or whether
  notifications should open the completed session path captured from
  `meeting stop`/`meeting status --json`.

Decisions to make at tray implementation time:

- Tray framework: start with a small Python tray process if it can launch
  reliably from the installed environment; package later if startup is fiddly.
- Command runner: prefer invoking the installed `meeting` executable, with a
  documented fallback to `python -m wave_notes` for development.
- Polling interval: start simple, likely every 2 seconds while idle/recording,
  and revisit only if it feels sluggish or wasteful.
- Notification model: show concise success/failure notifications and keep full
  detail in command output or session logs.
- Settings launch: open a dedicated settings process/window rather than putting
  config editing logic into the tray loop.

Remaining optional dependencies:

- Typed handwritten notes can wait until the tray controls are usable.
- Start-with-Windows and packaging can wait until the basic tray is proven.
- AI title generation can wait until recording, processing, and folder-opening
  flows are boring.

### Phase 4: Settings GUI

Goal: edit the same config file used by the CLI without creating hidden app-only
settings.

Deliverables:

- Settings window that reads and writes `~\.wave-notes\config.toml`.
- Device picker populated from the existing audio device list.
- Output folder chooser.
- STT provider and model controls.
- Notes provider, model, and thinking level controls.
- After-stop processing toggles.
- Save validation that catches common mistakes before the next recording.

Notes:

- Consider adding a small config read/write helper to avoid duplicated TOML
  serialization logic between the CLI and GUI.
- The settings GUI can initially be launched from the tray as a separate process
  if that keeps the tray process simple.

### Phase 5: Startup and Packaging

Goal: make the tray utility feel installable and boring to use day to day.

Deliverables:

- Start-with-Windows support.
- Clear install/update instructions for the Python package and tray entrypoint.
- A packaged Windows executable if the Python entrypoint proves too fiddly.
- Icon assets and basic application metadata.
- `meeting doctor` guidance that includes tray-specific readiness checks where
  useful.

### Phase 6: Polish and Recovery

Goal: make common failure modes understandable and recoverable.

Deliverables:

- Processing-in-progress state after "stop and process".
- Notification when transcription or notes generation completes or fails.
- Menu action to open the active session folder while recording.
- Menu action to view the current session log.
- Clear behavior for stale state when a recorder process dies unexpectedly.

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

## Handwritten Meeting Notes

V1 should leave room for handwritten notes captured during a meeting. This can be
implemented during the tray work if it remains simple, or immediately after the
tray utility is usable.

Target behavior:

- While recording, the user can open a lightweight note pad from the tray.
- Notes are saved into the active session folder as ordinary files.
- During AI processing, the notes are sent alongside the transcript and folded
  into the final `notes.md` and `notes.json` output.
- The original handwritten notes remain preserved as source artifacts.

Possible artifact contract:

```text
handwritten-notes.md
handwritten-notes.json
```

For stylus or drawing input, a later version may also preserve image strokes or
pages:

```text
handwritten-notes/
  page-001.png
  strokes.json
```

Implementation phases:

1. Start with typed Markdown notes attached to the active session.
2. Add a `meeting notes add/open` or similar CLI surface if the tray needs a
   durable way to manage notes.
3. Update the AI notes processor to include `handwritten-notes.md` when present.
4. Add stylus/drawing capture only after the basic tray and text-note workflow
   are working.

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
- Add machine-readable CLI output where the tray needs stable integration.
- Treat the tray, settings GUI, and handwritten-notes UI as clients of the same
  file/session contract rather than separate sources of truth.
