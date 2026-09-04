"""Event recorder: write a WAV around every confirmed detection.

Keeps a rolling pre-buffer of recent audio windows so a saved clip includes a
few seconds from *before* the alarm confirmed, then appends `post_seconds` of
live audio and writes a mono 16-bit WAV. Oldest files beyond `max_files` are
pruned.

Off by default (`[recording] enabled = false`); when off, `feed()` is a no-op
and nothing is buffered. The pre-buffer here is intentionally sized only for
recording — Batch 2's listen-in will resize/repurpose it.
"""
import logging
import math
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class Recorder:
    def __init__(self, config: dict):
        rec = config.get("recording", {}) or {}
        self.enabled = bool(rec.get("enabled", False))
        self.dir = Path(rec.get("dir", "recordings"))
        self.max_files = int(rec.get("max_files", 50))
        pre_seconds = float(rec.get("pre_seconds", 5))
        post_seconds = float(rec.get("post_seconds", 10))

        self.sample_rate = int(config["audio"]["sample_rate"])
        window_seconds = float(config["audio"]["window_seconds"])

        pre_windows = max(1, math.ceil(pre_seconds / window_seconds))
        self._pre = deque(maxlen=pre_windows)
        self._post_target = max(1, math.ceil(post_seconds / window_seconds))

        # A capture in progress is a list of windows; None means idle. `_armed`
        # gates the *leading edge*: one capture per detection event, re-armed
        # only after confirmation drops again — so a sustained alarm writes one
        # file, not one per window while the confirm history stays saturated.
        self._capturing: list[np.ndarray] | None = None
        self._capture_target = 0
        self._armed = True

        if self.enabled:
            logger.info(
                "Event recorder on → %s (pre %.0fs / post %.0fs, keep %d)",
                self.dir, pre_seconds, post_seconds, self.max_files,
            )

    def feed(self, window: np.ndarray, confirmed: bool) -> None:
        """Call once per processed audio window, with the detector's confirmed bool."""
        if not self.enabled:
            return

        if self._capturing is not None:
            self._capturing.append(window.copy())
            if len(self._capturing) >= self._capture_target:
                self._flush("hit")

        if confirmed:
            if self._armed and self._capturing is None:
                # pre-buffer holds the windows *before* this one; add this one
                # (the trigger window) explicitly, then run for post_target more.
                self._capturing = list(self._pre) + [window.copy()]
                self._capture_target = len(self._capturing) + self._post_target
                self._armed = False
        else:
            self._armed = True

        self._pre.append(window.copy())

    def _flush(self, label: str) -> None:
        windows, self._capturing = self._capturing, None
        if not windows:
            return
        audio = np.concatenate(windows)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        path = self.dir / f"{stamp}-{label}.wav"
        # Two events inside the same second would otherwise overwrite; keep the
        # documented name for the common case, disambiguate only on collision.
        n = 2
        while path.exists():
            path = self.dir / f"{stamp}-{label}-{n}.wav"
            n += 1
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._write_wav(path, audio)
            self._prune()
            logger.info("Recorded %s (%.1fs)", path, len(audio) / self.sample_rate)
        except OSError as e:
            logger.error("Failed to write recording %s: %s", path, e)

    def _write_wav(self, path: Path, audio: np.ndarray) -> None:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(pcm.tobytes())

    def _prune(self) -> None:
        files = sorted(self.dir.glob("*.wav"))
        for old in files[:-self.max_files] if self.max_files > 0 else files[:-1]:
            try:
                old.unlink()
            except OSError:
                pass
