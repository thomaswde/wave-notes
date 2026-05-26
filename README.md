# wave-notes

AI meeting notes from Wave Link Stream or any other unified audio stream source.

V1 is a Windows-first CLI pipeline. It records one configured audio input, writes
portable session folders, transcribes the recording with OpenAI STT, and generates
Markdown meeting notes with Pi or OpenAI.

## What This Builds

The target workflow is intentionally simple:

```powershell
meeting devices
meeting start "Product sync"
meeting stop
meeting transcribe latest --provider openai
meeting notes latest --provider pi
```

The result is a normal folder of files:

```text
Meetings/
  2026-05-26_1430_product-sync/
    audio.wav
    metadata.json
    processing.log
    chunks/
      000001.wav
      000002.wav
    transcript.openai.json
    transcript.openai.md
    notes.prompt.md
    notes.md
    notes.json
```

No database is required. The audio, transcript, notes, and metadata are all
inspectable files.

## Requirements

- Windows 10 or 11 for the first real recording test
- Python 3.11 or newer
- Git
- A mixed meeting audio input, such as Elgato Wave Link's `Wave Link Stream`
- `OPENAI_API_KEY` for transcription
- Optional: `pi` CLI for notes generation with Pi subscription auth

Development from macOS is supported for the code, CLI, chunking, STT, and notes
layers. Real Wave Link capture still needs to be verified on Windows.

## Install From Zero

### Windows PowerShell

Clone the repo:

```powershell
git clone https://github.com/thomaswde/wave-notes.git
cd wave-notes
```

Create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once for the current shell:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\.venv\Scripts\Activate.ps1
```

Install the CLI and audio dependency:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[audio]"
```

### macOS Development

```bash
git clone https://github.com/thomaswde/wave-notes.git
cd wave-notes
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[audio]'
```

## Configure API Keys

OpenAI STT uses the standard `OPENAI_API_KEY` environment variable.

For the current PowerShell session:

```powershell
$env:OPENAI_API_KEY = "sk-your-service-account-key"
```

To persist it for future PowerShell sessions:

```powershell
setx OPENAI_API_KEY "sk-your-service-account-key"
```

Close and reopen PowerShell after `setx`, then confirm:

```powershell
echo $env:OPENAI_API_KEY
```

Do not put API keys in `config.toml`, commit them to Git, or paste them into
session folders.

## Configure wave-notes

Create the default config:

```powershell
meeting init
```

Edit:

```text
~\.wave-notes\config.toml
```

For Wave Link, set the audio device name to the mixed stream. Partial matching is
supported, but exact names are easier to debug:

```toml
[audio]
device_name = "Wave Link Stream"
sample_rate = 48000
channels = 2
dtype = "int16"

[output]
root_dir = "Meetings"

[stt]
default_provider = "openai"
openai_model = "gpt-4o-mini-transcribe"
chunk_seconds = 30

[notes]
provider = "pi"
pi_command = "pi"
pi_model = ""
pi_provider = ""
openai_model = "gpt-4.1-mini"

[after_stop]
transcribe = false
notes = false
```

Relative `root_dir` values are resolved from the directory where you run
`meeting`. Use an absolute path such as `D:/Meetings` if you want all sessions in
one fixed place.

## Check Readiness

Run:

```powershell
meeting doctor
```

This checks Python, the audio package, `OPENAI_API_KEY`, the Pi command, and the
current config. If Pi is not installed, notes can still be tested with OpenAI:

```powershell
meeting notes latest --provider openai
```

List audio devices:

```powershell
meeting devices
```

Look for an input device named `Wave Link Stream` or similar. If the name differs,
copy the device name into `~\.wave-notes\config.toml`.

## First Audio Test

Record a short WAV:

```powershell
meeting record --seconds 30
```

Play the generated `recording-test-*.wav`. Confirm that it contains the full
meeting mix: your microphone and the other side of Teams/Zoom/Meet.

If the file is silent or only includes your microphone, fix Wave Link routing
before testing the rest of the pipeline.

## First Full Session

Start a session:

```powershell
meeting start "Windows first test"
```

Check status:

```powershell
meeting status
```

Stop the recording:

```powershell
meeting stop
```

Transcribe it:

```powershell
meeting transcribe latest --provider openai
```

Generate notes with Pi:

```powershell
meeting notes latest --provider pi
```

Or generate notes with OpenAI directly:

```powershell
meeting notes latest --provider openai
```

Open the latest session folder under `Meetings/` and inspect `audio.wav`,
`transcript.openai.md`, `notes.md`, `metadata.json`, and `processing.log`.

## One-Command Processing

Once recording, STT, and notes work independently:

```powershell
meeting start "Product sync"
meeting stop --process
```

Or enable automatic processing in `config.toml`:

```toml
[after_stop]
transcribe = true
notes = true
```

The stages remain rerunnable. If notes fail, the audio and transcript stay on
disk. If transcription fails, the original audio stays on disk.

## Troubleshooting

`meeting devices` fails:

- Confirm the virtual environment is active.
- Reinstall with `python -m pip install -e ".[audio]"`.
- On Windows, make sure the input device is enabled in Sound settings.

The test WAV is silent:

- Confirm Wave Link is sending the meeting mix to `Wave Link Stream`.
- Check that `audio.device_name` matches the input shown by `meeting devices`.
- Try leaving `device_name = ""` to use the default input, then retest.

OpenAI transcription fails:

- Confirm `OPENAI_API_KEY` is set in the same shell.
- Confirm the key has access to the OpenAI API.
- Check `processing.log` in the session folder.

Pi notes generation fails:

- Run `pi --version`.
- Confirm the `pi` command is on `PATH`.
- Try `meeting notes latest --provider openai` to isolate whether the transcript
  and notes prompt are valid.

## Current Readiness Notes

This first cut is ready for Windows API-key testing, but these items still need
real PC validation:

- Wave Link device naming and capture behavior on Windows.
- Whether `sounddevice`/PortAudio reliably records `Wave Link Stream` for long
  meetings.
- Whether 30-second fixed WAV chunks are the right size for quality and cost.
- Whether Pi CLI invocation is the right long-term notes integration, or whether
  we should replace it with a direct Pi SDK adapter once that API is available in
  this project.
- Windows packaging is still developer CLI only; there is no installer or `.exe`
  wrapper yet.
- Only OpenAI STT is implemented. Parakeet/local STT is intentionally deferred.

The durable contract is in place: session folders, original WAV preservation,
chunked audio, normalized transcript files, notes files, metadata, and logs.
