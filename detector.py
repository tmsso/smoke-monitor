import logging
import numpy as np
from collections import deque

logger = logging.getLogger(__name__)


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
        """Feed one audio window; returns True if alarm pattern confirmed."""
        ratio = self._band_energy_ratio(samples)
        detected = ratio >= self.energy_threshold
        if self.testing:
            logger.debug(
                "band ratio=%.3f threshold=%.3f hit=%s (testing: fires on single hit)",
                ratio, self.energy_threshold, detected,
            )
            return detected
        self._history.append(detected)
        hits = sum(self._history)
        logger.debug(
            "band ratio=%.3f threshold=%.3f hit=%s | confirm %d/%d hits (need %d/%d)",
            ratio, self.energy_threshold, detected,
            hits, len(self._history), self.confirm_windows, self.confirm_out_of,
        )
        if len(self._history) < self.confirm_out_of:
            return False
        return hits >= self.confirm_windows

    def _band_energy_ratio(self, samples: np.ndarray) -> float:
        """Fraction of spectral energy falling in the alarm band (0.0-1.0)."""
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / self.sample_rate)

        total_energy = np.sum(spectrum**2)
        if total_energy == 0:
            return 0.0

        band_mask = (freqs >= self.freq_low) & (freqs <= self.freq_high)
        band_energy = np.sum(spectrum[band_mask] ** 2)

        return float(band_energy / total_energy)
