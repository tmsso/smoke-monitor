"""The shipped confirmation rule catches a T3 alarm at any beep phase (H-8).

Uses the real config.toml, so it guards the defaults that actually run.
Under the old 5-of-8 rule a T3 cadence whose beeps line up with the 0.5 s
windows only ever scores 3/8 and never fires; 5-of-16 has a floor of 6/16.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detector import SmokeDetector  # noqa: E402
from monitor import load_config  # noqa: E402
from tone import build_t3, _beep  # noqa: E402

CONFIG = load_config(str(ROOT / "config.toml"))
SR = CONFIG["audio"]["sample_rate"]
WIN = int(SR * CONFIG["audio"]["window_seconds"])
LEAD_S = 8.0  # quiet lead-in: fills the history so start-up isn't what's tested


def _first_confirm_s(signal):
    """Seconds into `signal` of the first confirmed window, or None."""
    det = SmokeDetector(CONFIG)
    for i in range(len(signal) // WIN):
        if det.process_window(signal[i * WIN:(i + 1) * WIN]):
            return (i + 1) * WIN / SR
    return None


def _with_noise(x, sigma, seed):
    rng = np.random.default_rng(seed)
    return (x + rng.normal(0, sigma, len(x))).astype(np.float32)


@pytest.mark.parametrize("sigma", [0.0, 0.2, 0.5])
def test_t3_confirms_within_20s_at_every_phase(sigma):
    misses = []
    for step in range(41):  # phase offsets 0.0 … 4.0 s, 0.1 s apart
        offset = step / 10
        lead = np.zeros(int(SR * (LEAD_S + offset)), dtype=np.float32)
        sig = _with_noise(np.concatenate([lead, build_t3(duration_seconds=20.0)]), sigma, step)
        t = _first_confirm_s(sig)
        if t is None or t - (LEAD_S + offset) > 20.0:
            misses.append(offset)
    assert not misses, f"T3 missed at phase offsets {misses} (noise σ {sigma})"


@pytest.mark.parametrize("sigma", [0.0, 0.2])
def test_short_three_beep_burst_does_not_confirm(sigma):
    # 3 × 0.2 s chirps (e.g. a test-button tap or an appliance beep).
    chirp = _beep(3200.0, SR)[: int(SR * 0.2)]
    gap = np.zeros(int(SR * 0.3), dtype=np.float32)
    burst = np.concatenate([chirp, gap, chirp, gap, chirp])
    for step in range(10):
        lead = np.zeros(int(SR * (LEAD_S + step / 20)), dtype=np.float32)
        tail = np.zeros(SR * 10, dtype=np.float32)
        sig = _with_noise(np.concatenate([lead, burst, tail]), sigma, step)
        assert _first_confirm_s(sig) is None, f"burst confirmed at offset {step / 20}s"


@pytest.mark.parametrize("sigma", [0.2, 0.5])
def test_sixty_seconds_of_noise_does_not_confirm(sigma):
    sig = _with_noise(np.zeros(SR * 60, dtype=np.float32), sigma, 42)
    assert _first_confirm_s(sig) is None
