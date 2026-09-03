"""Self-contained synthetic smoke-alarm tone for end-to-end testing.

Plays an alarm-like beep pattern through the speakers so `--test` / a live run
can be exercised without setting off the real alarm (loud, drains its battery).

Deliberately standalone: it does NOT read `[detection]` config (`tone_hz` etc.)
— frequency and duration come from CLI options only, so the test signal stays a
fixed, known reference rather than tracking whatever the detector is tuned to.
"""
import numpy as np

DEFAULT_HZ = 3200.0
DEFAULT_SECONDS = 15.0
SAMPLE_RATE = 16000

# ANSI T3 temporal-3 pattern: 0.5 s beep / 0.5 s gap, three times, then 1.5 s
# pause — one cycle is 4.0 s.
_BEEP_S = 0.5
_GAP_S = 0.5
_PAUSE_S = 1.5
_EDGE_S = 0.005  # raised-cosine on/off ramp so beeps don't click


def _beep(freq_hz, sample_rate):
    t = np.arange(int(sample_rate * _BEEP_S)) / sample_rate
    # "square-ish": a soft-clipped sine keeps most energy on the fundamental
    # (so the band-energy detector still fires) while adding the harsh edge of
    # a real sounder. A true square at these rates would alias badly at 16 kHz.
    wave = np.tanh(1.6 * np.sin(2 * np.pi * freq_hz * t))
    edge = max(1, int(sample_rate * _EDGE_S))
    ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, edge)))
    wave[:edge] *= ramp
    wave[-edge:] *= ramp[::-1]
    return wave.astype(np.float32)


def build_t3(freq_hz=DEFAULT_HZ, duration_seconds=DEFAULT_SECONDS, sample_rate=SAMPLE_RATE):
    """Return a mono float32 waveform: T3-cadence beeps at `freq_hz`, tiled and
    trimmed to `duration_seconds`."""
    beep = _beep(freq_hz, sample_rate)
    gap = np.zeros(int(sample_rate * _GAP_S), dtype=np.float32)
    pause = np.zeros(int(sample_rate * _PAUSE_S), dtype=np.float32)
    cycle = np.concatenate([beep, gap, beep, gap, beep, pause])
    total = max(1, int(duration_seconds * sample_rate))
    reps = int(np.ceil(total / len(cycle)))
    return np.tile(cycle, reps)[:total]


def play_tone(freq_hz=DEFAULT_HZ, duration_seconds=DEFAULT_SECONDS, sample_rate=SAMPLE_RATE):
    """Play the T3 tone through the default output device and block until done."""
    import sounddevice as sd

    wave = build_t3(freq_hz, duration_seconds, sample_rate) * 0.9  # leave headroom
    sd.play(wave, samplerate=sample_rate, blocking=True)
