# Windows Meeting Recorder: Mid-Level Build Plan

**Goal:** Build a simple Windows-first meeting recording pipeline that consumes one mixed audio stream, records it to disk, transcribes it, and produces portable meeting notes in a directory of files.

**Guiding principle:** At every step, ask: **“What is the simplest way to do this?”** Prefer boring, inspectable pieces over a polished app or clever abstraction. No plan survives contact with the code; this plan defines direction, expectations, and outcomes, not every implementation detail.

---

## 1. Product Shape

This should start as a mostly CLI-based service/pipeline, not a full desktop product.

The user expectation is:

1. Meetings happen normally on Windows.
2. Audio is already routed into one mixed stream/channel.
3. The recorder captures that stream.
4. After the meeting, a directory appears with audio, transcript, notes, and metadata.
5. The system is easy to inspect, modify, and connect to agents.

Example user flow:

```powershell
meeting start "Product sync"
meeting stop
```

Or eventually:

```powershell
meetingd run
```

With automatic processing after stop.

---

## 2. Operating Assumptions

### Platform

- Initial target: **Windows**.
- Design should not depend on one specific high-end PC.
- Local acceleration may be available, but the system should degrade gracefully to slower local models or cloud STT.

### Audio

- Expect **one input audio stream/channel** representing the full meeting mix.
- In the target setup, this may come from something like **Wave Link Stream**, containing microphone plus meeting/chat output.
- The application should not try to solve complex audio routing in v1.
- Device selection should be explicit and easy to debug.

### Output

- Output should be a plain directory tree on disk.
- Files should be portable and useful without the app.
- The system should favor durable artifacts over hidden app state.

---

## 3. Non-Goals for v1

Do not start with:

- a polished GUI
- calendar automation
- per-speaker diarization
- multi-device audio mixing
- real-time meeting coaching
- cloud database sync
- complex plugin marketplace
- trying to replace commercial products feature-for-feature

Those may come later. v1 should prove the basic pipeline.

---

## 4. Proposed Architecture

```text
Single Windows audio input device
        ↓
Recorder CLI/service
        ↓
Session directory
        ↓
Audio chunking / normalization
        ↓
STT provider
  - local Parakeet English
  - local Whisper/whisper.cpp optional
  - OpenAI STT optional benchmark/fallback
        ↓
Transcript artifacts
        ↓
Agent/LLM notes processor
        ↓
Portable notes + metadata files
```

The architecture should keep each stage replaceable. The recorder should not know much about summarization. The summarizer should not care how audio was captured.

---

## 5. Session Directory Contract

A successful meeting should produce something like:

```text
Meetings/
  2026-05-26_1430_product-sync/
    audio.wav
    metadata.json
    chunks/
      000001.wav
      000002.wav
      000003.wav
    transcript.parakeet.json
    transcript.parakeet.md
    transcript.openai.json        # optional comparison
    transcript.openai.md          # optional comparison
    notes.md
    notes.json
    processing.log
```

The exact filenames can change, but the principle should not: **the meeting output is a normal folder of normal files.**

---

## 6. Core Components

### 6.1 Recorder

Responsible for:

- listing Windows audio devices
- selecting the configured meeting input device
- starting and stopping recording
- writing the raw meeting audio to disk
- recording basic metadata

Simplest acceptable v1:

- record one selected input device
- write one WAV file per session
- no live transcription
- no complex mixing

Potential implementation options:

- **Python prototype** using `sounddevice` or similar for rapid validation
- **Rust implementation** using CPAL/WASAPI for a more durable Windows service
- **ffmpeg-based implementation** if it proves simpler and reliable enough

The engineer should choose based on what works most reliably with Windows audio devices.

### 6.2 Audio Preparation

Responsible for preparing captured audio for STT.

Likely tasks:

- normalize format as needed
- split into chunks
- optionally detect silence boundaries
- preserve timestamps

Simplest acceptable v1:

- split into fixed-length chunks, such as 20–30 seconds
- improve later with silence-aware splitting if needed

### 6.3 STT Provider Layer

Responsible for converting audio chunks into timestamped transcript segments.

Initial providers:

- **Parakeet English** as the preferred local v1 option
- **OpenAI STT** as an easy benchmark/fallback

Optional later providers:

- whisper.cpp
- faster-whisper
- Deepgram
- Superwhisper adapter, if practical

Provider abstraction should be simple:

```text
input: audio file or chunk
output: transcript text plus timing metadata
```

Avoid over-designing this. Add capability metadata only when the implementation needs it.

### 6.4 Transcript Normalization

Responsible for turning provider output into a common internal format.

Desired transcript segment shape:

```json
{
  "index": 1,
  "start_seconds": 0.0,
  "end_seconds": 27.4,
  "text": "...",
  "provider": "parakeet"
}
```

This normalized transcript should be saved as JSON and rendered to Markdown.

### 6.5 Notes Processor

Responsible for transforming transcript into useful meeting notes.

This can call:

- Pi SDK / existing agent pipeline
- Codex/LLM API
- local OpenAI-compatible endpoint
- other BYO LLM mechanism

Expected outputs:

- `notes.md` for humans
- `notes.json` for automation

The notes processor should be prompt/template driven, but v1 can start with one strong default meeting-notes prompt.

---

## 7. Suggested Build Phases

### Phase 0: Spike and Verify Audio Capture

Outcome goal:

- Confirm Windows can record the intended single audio stream reliably.

Deliverables:

- command to list devices
- command to record 30 seconds from selected device
- saved WAV file
- basic playback verification

Key question:

> What is the simplest reliable way to capture the Wave Link Stream device on Windows?

Do not proceed until this is boring and repeatable.

---

### Phase 1: Manual Session Recorder

Outcome goal:

- Manually start and stop a meeting recording.

Example commands:

```powershell
meeting devices
meeting start "Test meeting"
meeting stop
meeting status
```

Deliverables:

- session folder creation
- `audio.wav`
- `metadata.json`
- `processing.log`

Keep it simple: one recording at a time, one selected input device, one output directory.

---

### Phase 2: Batch Transcription

Outcome goal:

- Convert a recorded meeting into transcript files.

Example command:

```powershell
meeting transcribe latest --provider parakeet
```

Deliverables:

- `chunks/*.wav`
- `transcript.parakeet.json`
- `transcript.parakeet.md`

Optional comparison:

```powershell
meeting transcribe latest --provider openai
```

Deliverables:

- `transcript.openai.json`
- `transcript.openai.md`

Key question:

> What is the simplest chunking strategy that produces good enough transcripts?

Start fixed-length. Add silence-aware splitting only if fixed chunks cause problems.

---

### Phase 3: Meeting Notes Generation

Outcome goal:

- Automatically produce usable meeting notes from the transcript.

Example command:

```powershell
meeting notes latest
```

Deliverables:

- `notes.md`
- `notes.json`

The first notes template should likely include:

- short summary
- key decisions
- action items
- open questions
- important context
- follow-ups

The engineer should decide the exact schema after seeing real transcripts.

---

### Phase 4: End-to-End Processing

Outcome goal:

- Stop recording and automatically process the meeting.

Example:

```powershell
meeting stop --process
```

Or config-driven behavior:

```yaml
after_stop:
  transcribe: true
  notes: true
```

Deliverables:

- one command creates the complete meeting folder
- failures are visible and resumable
- each stage can be rerun independently

Important expectation:

- If notes generation fails, the audio and transcript should still be preserved.
- If transcription fails, the audio should still be preserved.
- Never lose the original recording because a later processing step failed.

---

### Phase 5: Service Mode

Outcome goal:

- Run a background service that can be controlled by CLI commands.

Possible commands:

```powershell
meetingd install
meetingd start
meetingd stop
meeting status
```

This phase can wait until the manual CLI is useful. Avoid service complexity until the core workflow is proven.

---

### Phase 6: Calendar Integration

Outcome goal:

- Add meeting metadata automatically.

Possible behavior:

- detect current calendar event
- name session folder from event title
- include participants in `metadata.json`
- optionally auto-start/stop recording

This should remain a later phase. Calendar automation should enrich a working recorder, not become a prerequisite for it.

---

## 8. Configuration

Use a simple config file, probably YAML or TOML.

Example:

```yaml
audio:
  device_name: "Wave Link Stream"
  sample_rate: 48000
  channels: 2

output:
  root_dir: "D:/Meetings"

stt:
  default_provider: "parakeet"
  compare_provider: null

notes:
  provider: "pi-sdk"
  template: "standard_meeting"

after_stop:
  transcribe: true
  notes: true
```

The engineer should keep config minimal. Add settings only when the user actually needs them.

---

## 9. Reliability Expectations

The system should be boring and recoverable.

Minimum expectations:

- original audio is preserved
- session metadata is written early
- logs are written to the session folder
- processing stages are idempotent where practical
- rerunning transcription should not require rerecording
- rerunning notes should not require retranscription
- errors should be understandable from the terminal and log file

Avoid hidden state. Prefer files that can be inspected and manually repaired.

---

## 10. Design Biases

Prefer:

- CLI first
- file-first storage
- local-first processing
- explicit commands
- small modules
- swappable providers
- simple defaults
- resumable stages

Avoid:

- premature GUI work
- database-first design
- complex plugin systems
- solving audio routing inside the app
- requiring a specific GPU or high-end PC
- building abstractions before two implementations need them

---

## 11. Success Criteria for v1

v1 is successful if:

1. A Windows user can configure one audio device as the meeting source.
2. They can start and stop recording from the CLI.
3. The system writes a session directory with raw audio.
4. The system transcribes the recording with at least one provider.
5. The system generates useful Markdown meeting notes.
6. All important outputs are normal files.
7. The system is understandable enough for another engineer or agent to modify.

A polished UI, automation, and perfect transcript quality are not required for v1.

---

## 12. Open Engineering Decisions

These should be decided during implementation, based on what proves simplest and most reliable:

- Python vs Rust vs ffmpeg for recording
- exact Parakeet runtime/package choice
- WAV vs FLAC for archival audio
- fixed chunking vs silence-aware chunking
- whether transcript timestamps are chunk-level or finer-grained
- notes JSON schema
- whether to use a lightweight DB later
- how service mode should work on Windows
- how much OpenAI STT comparison belongs in the main workflow

The plan should not force these decisions prematurely. Build the smallest working version, then adjust based on real recordings.

---

## 13. North Star

The desired end state is not “a meeting SaaS clone.”

The desired end state is:

> A simple, local, agent-friendly Windows meeting pipeline that records one known audio stream and leaves behind a complete, portable directory of useful meeting artifacts.

If a feature does not make that outcome simpler, more reliable, or more useful, defer it.
