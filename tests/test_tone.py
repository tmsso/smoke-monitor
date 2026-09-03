"""Unit tests for the synthetic T3 tone generator (no audio device touched)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tone import SAMPLE_RATE, build_t3  # noqa: E402


def dominant_hz(wave, sample_rate):
    spectrum = np.abs(np.fft.rfft(wave * np.hanning(len(wave))))
    freqs = np.fft.rfftfreq(len(wave), d=1.0 / sample_rate)
    return freqs[np.argmax(spectrum)]


def test_length_matches_requested_duration():
    wave = build_t3(3200, 15, SAMPLE_RATE)
    assert len(wave) == 15 * SAMPLE_RATE


def test_dominant_frequency_is_the_requested_tone():
    wave = build_t3(3200, 15, SAMPLE_RATE)
    assert abs(dominant_hz(wave, SAMPLE_RATE) - 3200) < 30


def test_dominant_frequency_tracks_a_different_request():
    wave = build_t3(2900, 8, SAMPLE_RATE)
    assert abs(dominant_hz(wave, SAMPLE_RATE) - 2900) < 30


def test_most_energy_lands_in_a_detector_style_band():
    # The default detector watches 3000-3600 Hz; the tone must put the bulk of
    # its energy there or --test can't fire.
    wave = build_t3(3200, 15, SAMPLE_RATE)
    spectrum = np.abs(np.fft.rfft(wave * np.hanning(len(wave)))) ** 2
    freqs = np.fft.rfftfreq(len(wave), d=1.0 / SAMPLE_RATE)
    band = (freqs >= 3000) & (freqs <= 3600)
    assert spectrum[band].sum() / spectrum.sum() > 0.5


def test_t3_cadence_three_beeps_then_long_pause():
    wave = build_t3(3200, 4, SAMPLE_RATE)  # exactly one 4.0 s cycle
    # Envelope: RMS per 10 ms frame, thresholded → on/off runs.
    frame = int(SAMPLE_RATE * 0.01)
    rms = np.sqrt(np.mean(wave[: len(wave) // frame * frame]
                          .reshape(-1, frame) ** 2, axis=1))
    on = rms > rms.max() * 0.2
    # count on-runs
    runs = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    starts = np.where(runs == 1)[0]
    ends = np.where(runs == -1)[0]
    assert len(starts) == 3, f"expected 3 beeps, got {len(starts)}"
    durations = (ends - starts) * 0.01
    assert all(0.35 < d < 0.65 for d in durations), durations
    # gap between beep 1 and 2 ~0.5 s; trailing pause ~1.5 s
    gap12 = (starts[1] - ends[0]) * 0.01
    assert 0.35 < gap12 < 0.65, gap12
    trailing = (len(on) - ends[-1]) * 0.01
    assert trailing > 1.3, trailing


def test_zero_or_tiny_duration_does_not_crash():
    assert len(build_t3(3200, 0, SAMPLE_RATE)) >= 1
