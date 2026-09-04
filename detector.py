import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WindowMetrics:
    """Per-window detector output, for the live dashboard and offline replay.

    `confirmed` is exactly what `process_window` returns for the same window, so
    callers that only need the bool can keep using the wrapper.
    """

    ratio: float          # fraction of spectral energy in the alarm band (0-1)
    dominant_hz: float     # peak-energy frequency in the whole window
    hit: bool              # this window alone is over threshold
    confirm_hits: int      # hits currently in the confirmation history
    confirm_len: int       # windows currently in the history (<= confirm_out_of)
    confirm_needed: int    # confirm_windows (hits needed to fire)
    confirm_out_of: int    # confirm_out_of (history size)
    confirmed: bool        # alarm pattern confirmed this window


class SmokeDetector:
    def __init__(self, config, testing: bool = False):
        det = config["detection"]
        aud = config["audio"]

        self.sample_rate = aud["sample_rate"]
        self.freq_low = det["freq_low_hz"]
        self.freq_high = det["freq_high_hz"]
        self.energy_threshold = det["energy_ratio_threshold"]
        self.confirm_windows = det["confirm_windows"]
        self.confirm_out_of = det["confirm_out_of"]
        self.testing = testing

        self._history = deque(maxlen=self.confirm_out_of)

    def process_window(self, samples: np.ndarray) -> bool:
        """Feed one audio window; returns True if alarm pattern confirmed.

        Thin wrapper over `analyze_window` — kept so callers that only need the
        bool (the live monitor loop) are unaffected by the richer return type.
        """
        return self.analyze_window(samples).confirmed

    def analyze_window(self, samples: np.ndarray) -> WindowMetrics:
        """Feed one audio window; return the full per-window metrics.

        Stateful: like `process_window` this advances the confirmation history,
        so call it exactly once per window (never alongside `process_window`).
        """
        freqs, power = self._spectrum(samples)
        total_energy = float(np.sum(power))
        if total_energy == 0.0:
            ratio = 0.0
            dominant_hz = 0.0
        else:
            band_mask = (freqs >= self.freq_low) & (freqs <= self.freq_high)
            ratio = float(np.sum(power[band_mask]) / total_energy)
            # Ignore DC / sub-audible rumble when picking the dominant tone —
            # otherwise a quiet room reports 0 Hz, which is useless for tuning.
            audible = power.copy()
            audible[freqs < 100.0] = 0.0
            dominant_hz = float(freqs[int(np.argmax(audible))]) if np.any(audible) else 0.0

        hit = ratio >= self.energy_threshold

        if self.testing:
            logger.debug(
                "band ratio=%.3f threshold=%.3f hit=%s (testing: fires on single hit)",
                ratio, self.energy_threshold, hit,
            )
            # Testing mode fires on a single hit and keeps no history.
            return WindowMetrics(
                ratio=ratio, dominant_hz=dominant_hz, hit=hit,
                confirm_hits=0, confirm_len=0,
                confirm_needed=self.confirm_windows, confirm_out_of=self.confirm_out_of,
                confirmed=hit,
            )

        self._history.append(hit)
        hits = sum(self._history)
        confirmed = len(self._history) >= self.confirm_out_of and hits >= self.confirm_windows
        logger.debug(
            "band ratio=%.3f threshold=%.3f hit=%s | confirm %d/%d hits (need %d/%d)",
            ratio, self.energy_threshold, hit,
            hits, len(self._history), self.confirm_windows, self.confirm_out_of,
        )
        return WindowMetrics(
            ratio=ratio, dominant_hz=dominant_hz, hit=hit,
            confirm_hits=hits, confirm_len=len(self._history),
            confirm_needed=self.confirm_windows, confirm_out_of=self.confirm_out_of,
            confirmed=confirmed,
        )

    def _spectrum(self, samples: np.ndarray):
        """Return (freqs, power spectrum) for one Hann-windowed audio window."""
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / self.sample_rate)
        return freqs, spectrum**2
