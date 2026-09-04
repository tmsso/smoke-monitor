"""Offline replay (`--replay path.wav`): run the detector over a recorded WAV.

No audio stream and no notifications — just the per-window numbers and whether
the alarm would have fired. Use it to check a tuning change against a saved
event (see the event recorder) without waiting for the real alarm.
"""
import logging
import sys
import wave
from pathlib import Path

import numpy as np

from detector import SmokeDetector

logger = logging.getLogger(__name__)


def _decode(raw: bytes, sampwidth: int, n_channels: int) -> np.ndarray:
    """WAV frame bytes → mono float32 in roughly [-1, 1]."""
    if sampwidth == 1:  # WAV 8-bit is unsigned
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sampwidth * 8}-bit")
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)  # downmix to mono
    return data


def replay_file(path: str, config: dict) -> int:
    """Replay `path` through the detector. Returns a process exit code."""
    sample_rate = config["audio"]["sample_rate"]
    window_size = int(sample_rate * config["audio"]["window_seconds"])

    wav_path = Path(path)
    if not wav_path.is_file():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 2

    try:
        with wave.open(str(wav_path), "rb") as w:
            framerate = w.getframerate()
            n_channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        print(f"error: not a readable WAV file: {path} ({e})", file=sys.stderr)
        return 2

    if framerate != sample_rate:
        print(
            f"error: {path} is {framerate} Hz but [audio] sample_rate is "
            f"{sample_rate} Hz. Re-record at {sample_rate} Hz or change the "
            f"config; replay does not resample.",
            file=sys.stderr,
        )
        return 2

    try:
        samples = _decode(raw, sampwidth, n_channels)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    n_windows = len(samples) // window_size
    if n_windows == 0:
        print(f"error: {path} is shorter than one {config['audio']['window_seconds']}s window",
              file=sys.stderr)
        return 2

    detector = SmokeDetector(config, testing=False)
    fired_at = None
    print(f"# {path}: {framerate} Hz, {n_channels}ch, {len(samples) / framerate:.1f}s, "
          f"{n_windows} windows")
    for i in range(n_windows):
        window = samples[i * window_size:(i + 1) * window_size]
        m = detector.analyze_window(window)
        t = i * window_size / sample_rate
        print(
            f"t={t:6.2f}s  ratio={m.ratio:.3f}  dom={m.dominant_hz:5.0f} Hz  "
            f"{'HIT ' if m.hit else 'miss'}  confirm {m.confirm_hits}/{m.confirm_len}"
        )
        if m.confirmed and fired_at is None:
            fired_at = t

    if fired_at is not None:
        print(f"\nalarm would have fired at t={fired_at:.1f}s")
    else:
        print("\nno alarm")
    return 0
