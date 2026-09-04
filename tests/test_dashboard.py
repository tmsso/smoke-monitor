"""Dashboard rendering — pure `render()` output, no audio device touched."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector import WindowMetrics  # noqa: E402


def _plain(renderable) -> str:
    from rich.console import Console

    console = Console(width=100, record=True, force_terminal=False)
    console.print(renderable)
    return console.export_text()


def _metrics(**kw):
    base = dict(ratio=0.12, dominant_hz=180.0, hit=False, confirm_hits=0,
                confirm_len=0, confirm_needed=5, confirm_out_of=8, confirmed=False)
    base.update(kw)
    return WindowMetrics(**base)


def test_meter_marks_threshold_and_scales_with_ratio():
    from dashboard import _meter

    lo = _meter(0.1, 0.35)
    hi = _meter(0.9, 0.35)
    assert len(lo) == len(hi)
    assert lo.count("█") < hi.count("█")
    assert ("┃" in lo or "╋" in lo)  # threshold mark always present


def test_render_shows_all_required_fields():
    from dashboard import render

    out = _plain(render(
        _metrics(ratio=0.42, dominant_hz=3210.0, hit=True, confirm_hits=3,
                 confirm_len=6),
        device="7: USB Audio", threshold=0.35, freq_low=3000, freq_high=3600,
        overflows=2,
    ))
    assert "0.420" in out            # band ratio
    assert "3210 Hz" in out          # dominant frequency
    assert "HIT" in out              # per-window verdict
    assert "3/6, need 5" in out      # rolling confirmation state
    assert "7: USB Audio" in out     # active input device
    assert "overflows" in out and "2" in out
    assert "3000-3600 Hz" in out     # band shown next to threshold


def test_render_flags_a_confirmed_alarm():
    from dashboard import render

    out = _plain(render(
        _metrics(ratio=0.8, hit=True, confirm_hits=5, confirm_len=8, confirmed=True),
        device="default", threshold=0.35, freq_low=3000, freq_high=3600, overflows=0,
    ))
    assert "SMOKE ALARM CONFIRMED" in out


def test_render_miss_state():
    from dashboard import render

    out = _plain(render(
        _metrics(), device="default", threshold=0.35, freq_low=3000,
        freq_high=3600, overflows=0,
    ))
    assert "miss" in out
