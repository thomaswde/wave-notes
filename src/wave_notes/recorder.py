from __future__ import annotations

import argparse
from pathlib import Path

from .audio import record_until_stopped
from .config import AudioConfig
from .session import append_log, paths_for, update_metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--device-name", default="")
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--dtype", default="int16")
    args = parser.parse_args()

    paths = paths_for(Path(args.session))
    append_log(paths, "recorder process started")
    update_metadata(paths, status="recording")
    try:
        record_until_stopped(
            paths.audio,
            AudioConfig(
                device_name=args.device_name or None,
                sample_rate=args.sample_rate,
                channels=args.channels,
                dtype=args.dtype,
            ),
            paths.stop_signal,
        )
    finally:
        append_log(paths, "recorder process stopped")


if __name__ == "__main__":
    main()
