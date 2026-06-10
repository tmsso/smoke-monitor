import numpy as np
from collections import deque


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
        detected = self._has_alarm_frequency(samples)
        if self.testing:
            return detected
        self._history.append(detected)
        if len(self._history) < self.confirm_out_of:
            return False
        return sum(self._history) >= self.confirm_windows

    def _has_alarm_frequency(self, samples: np.ndarray) -> bool:
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / self.sample_rate)

        total_energy = np.sum(spectrum**2)
        if total_energy == 0:
            return False

        band_mask = (freqs >= self.freq_low) & (freqs <= self.freq_high)
        band_energy = np.sum(spectrum[band_mask] ** 2)

        return (band_energy / total_energy) >= self.energy_threshold
