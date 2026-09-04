"""Event recorder — WAV output, pre-buffer contents, pruning, off-switch."""
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector import SmokeDetector  # noqa: E402
from recorder import Recorder  # noqa: E402
from tone import build_t3  # noqa: E402

SR = 16000
WIN_S = 0.5
WIN = int(SR * WIN_S)


def _config(tmp, **rec):
    r = {"enabled": True, "dir": str(tmp / "recordings"), "max_files": 50,
         "pre_seconds": 5, "post_seconds": 10}
    r.update(rec)
    return {"audio": {"sample_rate": SR, "window_seconds": WIN_S}, "recording": r}


def _win(value):
    return np.full(WIN, value, dtype=np.float32)


def _read_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == SR
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2")


def test_disabled_recorder_writes_nothing(tmp_path):
    rec = Recorder(_config(tmp_path, enabled=False))
    for _ in range(200):
        rec.feed(_win(0.5), confirmed=True)
    assert not (tmp_path / "recordings").exists()


def test_clip_contains_pre_trigger_audio_and_expected_length(tmp_path):
    rec = Recorder(_config(tmp_path, pre_seconds=2, post_seconds=3))
    # 10 quiet windows form the pre-buffer history; only the last 4 (2s / 0.5s)
    # are kept. Mark them with a distinctive value.
    for _ in range(6):
        rec.feed(_win(0.0), confirmed=False)
    for _ in range(4):
        rec.feed(_win(0.25), confirmed=False)   # the pre-buffer that should survive
    rec.feed(_win(0.9), confirmed=True)         # trigger window
    for _ in range(6):                          # 3s / 0.5s = 6 post windows
        rec.feed(_win(0.1), confirmed=True)

    files = list((tmp_path / "recordings").glob("*.wav"))
    assert len(files) == 1
    assert files[0].name.endswith("-hit.wav")

    samples = _read_wav(files[0])
    # 4 pre + 1 trigger + 6 post = 11 windows
    assert len(samples) == 11 * WIN
    pre = samples[: 4 * WIN].astype(np.float32) / 32767.0
    assert np.allclose(pre, 0.25, atol=1e-3)          # audio from *before* the trigger
    trig = samples[4 * WIN: 5 * WIN].astype(np.float32) / 32767.0
    assert np.allclose(trig, 0.9, atol=1e-3)


def test_sustained_alarm_writes_a_single_file(tmp_path):
    rec = Recorder(_config(tmp_path, pre_seconds=1, post_seconds=1))
    for _ in range(300):                        # 150s of unbroken confirmation
        rec.feed(_win(0.8), confirmed=True)
    files = list((tmp_path / "recordings").glob("*.wav"))
    assert len(files) == 1, f"sustained alarm should make one file, made {len(files)}"


def test_separate_events_each_write_a_file(tmp_path):
    rec = Recorder(_config(tmp_path, pre_seconds=1, post_seconds=1))
    for event in range(3):
        for _ in range(4):
            rec.feed(_win(0.8), confirmed=True)     # trigger + capture
        for _ in range(4):
            rec.feed(_win(0.0), confirmed=False)    # confirmation drops -> re-arm
    files = list((tmp_path / "recordings").glob("*.wav"))
    assert len(files) == 3


def test_end_to_end_detector_drives_recorder_to_a_valid_wav(tmp_path):
    """Real detector + real T3 tone: a confirmed alarm writes a playable WAV
    whose opening seconds are the ambient audio from before the trigger."""
    det_config = {
        "audio": {"sample_rate": SR, "window_seconds": WIN_S},
        "detection": {"freq_low_hz": 3000, "freq_high_hz": 3600,
                      "energy_ratio_threshold": 0.35, "confirm_windows": 5,
                      "confirm_out_of": 8},
    }
    det = SmokeDetector(det_config)
    # pre-buffer (6s) is longer than the detector's ~4s confirm delay, so the
    # clip still opens on ambient audio from before the alarm started.
    rec = Recorder(_config(tmp_path, pre_seconds=6, post_seconds=2))

    rng = np.random.default_rng(0)
    quiet = [(rng.standard_normal(WIN) * 0.02).astype(np.float32) for _ in range(12)]
    tone = build_t3(3200, WIN_S, SR)[:WIN].astype(np.float32)

    for w in quiet:
        rec.feed(w, det.process_window(w))
    for _ in range(20):                   # sustained tone -> confirms, then captures
        rec.feed(tone, det.process_window(tone))

    files = list((tmp_path / "recordings").glob("*.wav"))
    assert len(files) == 1
    samples = _read_wav(files[0])
    assert len(samples) > 8 * WIN
    opening = samples[: 2 * WIN].astype(np.float32) / 32767.0
    assert np.max(np.abs(opening)) < 0.2           # ambient from before the alarm
    later = samples[-3 * WIN:].astype(np.float32) / 32767.0
    assert np.max(np.abs(later)) > 0.5            # the alarm itself


def test_prune_keeps_only_max_files_newest(tmp_path):
    rec = Recorder(_config(tmp_path, max_files=5, pre_seconds=1, post_seconds=1))
    # Force distinct filenames by stubbing the timestamp source.
    import recorder as rec_mod

    class _Clock:
        n = 0

        def __format__(self, spec):
            _Clock.n += 1
            return f"20260101-0000{_Clock.n:02d}"

    orig = rec_mod.datetime
    try:
        rec_mod.datetime = type("D", (), {"now": staticmethod(lambda: _Clock())})
        for _ in range(8):
            for _ in range(4):
                rec.feed(_win(0.8), confirmed=True)
            for _ in range(4):
                rec.feed(_win(0.0), confirmed=False)
    finally:
        rec_mod.datetime = orig

    files = sorted((tmp_path / "recordings").glob("*.wav"))
    assert len(files) == 5
    assert files[0].name == "20260101-000004-hit.wav"   # oldest 3 pruned
    assert files[-1].name == "20260101-000008-hit.wav"
