"""Offline replay — verdict, sample-rate rejection, threshold sensitivity."""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from replay import replay_file  # noqa: E402
from tone import build_t3  # noqa: E402


def _sustained_tone(seconds, hz=3200.0):
    """A continuous in-band tone — unlike T3's gapped cadence it fills the
    confirmation window, so a full (non-testing) run confirms on it."""
    t = np.arange(int(SR * seconds)) / SR
    return np.tanh(1.6 * np.sin(2 * np.pi * hz * t)).astype(np.float32) * 0.9

SR = 16000


def _config(**det):
    d = {"freq_low_hz": 3000, "freq_high_hz": 3600, "energy_ratio_threshold": 0.35,
         "confirm_windows": 5, "confirm_out_of": 8}
    d.update(det)
    return {"audio": {"sample_rate": SR, "window_seconds": 0.5}, "detection": d}


def _write_wav(path, samples, framerate=SR):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(pcm.tobytes())


def test_alarm_recording_reproduces_the_detection(tmp_path, capsys):
    wav = tmp_path / "alarm.wav"
    _write_wav(wav, _sustained_tone(10))
    rc = replay_file(str(wav), _config())
    out = capsys.readouterr().out
    assert rc == 0
    assert "alarm would have fired at t=" in out
    assert "HIT" in out


def test_t3_cadence_shows_hits_but_does_not_confirm(tmp_path, capsys):
    # Documents a known gotcha: T3's 3-beeps-then-pause never fills 5 of 8
    # confirmation windows, so --replay reports per-window HITs but "no alarm".
    wav = tmp_path / "t3.wav"
    _write_wav(wav, build_t3(3200, 12, SR))
    rc = replay_file(str(wav), _config())
    out = capsys.readouterr().out
    assert rc == 0
    assert "HIT" in out
    assert out.strip().endswith("no alarm")


def test_ambient_noise_does_not_fire(tmp_path, capsys):
    wav = tmp_path / "ambient.wav"
    rng = np.random.default_rng(0)
    _write_wav(wav, rng.standard_normal(SR * 8) * 0.05)
    rc = replay_file(str(wav), _config())
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip().endswith("no alarm")


def test_sample_rate_mismatch_is_rejected(tmp_path, capsys):
    wav = tmp_path / "wrong_rate.wav"
    _write_wav(wav, build_t3(3200, 4, 8000), framerate=8000)
    rc = replay_file(str(wav), _config())
    err = capsys.readouterr().err
    assert rc == 2
    assert "8000 Hz" in err and "sample_rate" in err


def test_threshold_change_flips_the_verdict(tmp_path, capsys):
    wav = tmp_path / "alarm.wav"
    _write_wav(wav, _sustained_tone(10))

    assert replay_file(str(wav), _config(energy_ratio_threshold=0.35)) == 0
    fired = capsys.readouterr().out
    assert "would have fired" in fired

    assert replay_file(str(wav), _config(energy_ratio_threshold=0.99)) == 0
    not_fired = capsys.readouterr().out
    assert not_fired.strip().endswith("no alarm")


def test_missing_file_is_rejected(tmp_path, capsys):
    rc = replay_file(str(tmp_path / "nope.wav"), _config())
    assert rc == 2
    assert "no such file" in capsys.readouterr().err


def test_cli_entrypoint_runs(tmp_path):
    wav = tmp_path / "alarm.wav"
    _write_wav(wav, _sustained_tone(6))
    r = subprocess.run(
        [sys.executable, "monitor.py", "--replay", str(wav)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "alarm would have fired" in r.stdout


def test_cli_sample_rate_mismatch_exit_code(tmp_path):
    wav = tmp_path / "bad.wav"
    _write_wav(wav, build_t3(3200, 4, 8000), framerate=8000)
    r = subprocess.run(
        [sys.executable, "monitor.py", "--replay", str(wav)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 2
