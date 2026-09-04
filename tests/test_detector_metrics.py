"""SmokeDetector.analyze_window metrics + process_window bool parity."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector import SmokeDetector, WindowMetrics  # noqa: E402
from tone import build_t3  # noqa: E402

SR = 16000
WIN = int(SR * 0.5)


def _config(**det):
    d = {
        "freq_low_hz": 3000, "freq_high_hz": 3600, "energy_ratio_threshold": 0.35,
        "confirm_windows": 5, "confirm_out_of": 8,
    }
    d.update(det)
    return {"audio": {"sample_rate": SR, "window_seconds": 0.5}, "detection": d}


def _tone_window():
    return build_t3(3200, 0.5, SR)[:WIN].astype(np.float32)


def _noise_window(seed=0):
    return (np.random.default_rng(seed).standard_normal(WIN) * 0.1).astype(np.float32)


def test_tone_window_is_a_hit_with_dominant_in_band():
    m = SmokeDetector(_config()).analyze_window(_tone_window())
    assert isinstance(m, WindowMetrics)
    assert m.hit is True
    assert m.ratio > 0.5
    assert 3000 <= m.dominant_hz <= 3600


def test_dominant_hz_ignores_dc_and_rumble_in_a_quiet_window():
    # A near-silent window with a strong DC offset + a faint 3.2 kHz tone: the
    # reported dominant should be the audible tone, not 0 Hz.
    rng = np.random.default_rng(3)
    t = np.arange(WIN) / SR
    w = (0.4 + 0.01 * np.sin(2 * np.pi * 3200 * t)
         + rng.standard_normal(WIN) * 1e-4).astype(np.float32)
    m = SmokeDetector(_config()).analyze_window(w)
    assert m.dominant_hz > 100.0


def test_noise_window_is_a_miss():
    m = SmokeDetector(_config()).analyze_window(_noise_window())
    assert m.hit is False
    assert m.ratio < 0.35


def test_silent_window_is_safe():
    m = SmokeDetector(_config()).analyze_window(np.zeros(WIN, dtype=np.float32))
    assert m.ratio == 0.0
    assert m.dominant_hz == 0.0
    assert m.hit is False


def test_confirmation_state_progresses_and_fires():
    det = SmokeDetector(_config())
    tone = _tone_window()
    metrics = [det.analyze_window(tone) for _ in range(8)]
    # first 7 windows: history not full yet OR not enough hits -> not confirmed
    assert [m.confirmed for m in metrics[:4]] == [False, False, False, False]
    assert metrics[-1].confirm_len == 8
    assert metrics[-1].confirm_hits == 8
    assert metrics[-1].confirmed is True
    assert metrics[-1].confirm_needed == 5
    assert metrics[-1].confirm_out_of == 8


def test_process_window_bool_matches_analyze_confirmed():
    seq = [_tone_window(), _noise_window(1), _tone_window(), _tone_window(),
           _noise_window(2), _tone_window(), _tone_window(), _tone_window(),
           _tone_window(), _tone_window()]
    a = SmokeDetector(_config())
    b = SmokeDetector(_config())
    for w in seq:
        assert a.process_window(w.copy()) == b.analyze_window(w.copy()).confirmed


def test_testing_mode_fires_on_single_hit_and_keeps_no_history():
    det = SmokeDetector(_config(), testing=True)
    m = det.analyze_window(_tone_window())
    assert m.confirmed is True and m.hit is True
    assert m.confirm_len == 0 and m.confirm_hits == 0
    miss = det.analyze_window(_noise_window())
    assert miss.confirmed is False
