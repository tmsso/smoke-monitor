"""Unit tests for priority-list device selection.

No hardware: `select_input_device` is a pure function over a synthetic device
list shaped like `sounddevice.query_devices()` output.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audio_devices import (  # noqa: E402
    better_device,
    describe_device,
    diagnose_stream,
    select_input_device,
)


def dev(index, name, max_in=0, max_out=2):
    return {"index": index, "name": name, "max_input_channels": max_in,
            "max_output_channels": max_out}


# Internal analog mic + speakers only — the "USB mic unplugged" world.
INTERNAL_ONLY = [
    dev(0, "HDA Intel PCH: CX20590 Analog", max_in=2),
    dev(1, "HDA Intel PCH: HDMI 0", max_in=0, max_out=8),
    dev(2, "sysdefault", max_in=128, max_out=128),
    dev(3, "default", max_in=128, max_out=128),
]

# Same box with a USB mic plugged in at index 4.
WITH_USB = INTERNAL_ONLY + [dev(4, "Samson C01U Pro USB Microphone", max_in=1)]


def test_usb_listed_first_and_present_is_chosen():
    assert select_input_device(WITH_USB, ["USB", "default"]) == (
        4, "Samson C01U Pro USB Microphone")


def test_usb_unplugged_falls_through_to_next_entry():
    # "default" is a substring of "sysdefault" too, and index 2 comes first —
    # substring matching is greedy by list order, which is the intended contract.
    assert select_input_device(INTERNAL_ONLY, ["USB", "default"]) == (2, "sysdefault")


def test_usb_unplugged_exact_index_fallback():
    assert select_input_device(INTERNAL_ONLY, ["USB", 3]) == (3, "default")


def test_no_entry_matches_returns_none():
    assert select_input_device(INTERNAL_ONLY, ["USB", "Yeti"]) is None


def test_empty_priority_returns_none():
    assert select_input_device(WITH_USB, []) is None


def test_integer_index_entry_matches_by_index():
    assert select_input_device(WITH_USB, [4]) == (4, "Samson C01U Pro USB Microphone")


def test_integer_index_for_output_only_device_is_skipped():
    # index 1 is HDMI (no input) — must not be selected even if named explicitly.
    assert select_input_device(WITH_USB, [1, "CX20590"]) == (
        0, "HDA Intel PCH: CX20590 Analog")


def test_case_insensitive_substring():
    assert select_input_device(WITH_USB, ["samson c01u"]) == (
        4, "Samson C01U Pro USB Microphone")


def test_order_is_respected():
    # CX20590 comes first in the list; priority asks for USB first, so USB wins.
    assert select_input_device(WITH_USB, ["usb", "cx20590"])[0] == 4
    assert select_input_device(WITH_USB, ["cx20590", "usb"])[0] == 0


def test_bool_entry_does_not_match_index_one():
    # TOML `true` is an int subclass; it must be ignored, not matched to index 1.
    assert select_input_device(WITH_USB, [True]) is None


def test_describe_device_none_is_system_default():
    assert describe_device(WITH_USB, None) == "system default"


def test_describe_device_by_index():
    assert describe_device(WITH_USB, 4) == "4: Samson C01U Pro USB Microphone"


def test_describe_device_unresolved():
    assert "unresolved" in describe_device(INTERNAL_ONLY, "Yeti")


# --- better_device: hot-swap to a higher-priority mic ------------------------

def test_better_device_none_when_current_is_top_match():
    # Running on the USB mic (index 4), which is the top priority match already.
    assert better_device(WITH_USB, ["USB", "default"], current_index=4) is None


def test_better_device_switches_when_higher_priority_appears():
    # Was running on the fallback default (index 3); USB is now present and ranks
    # first — caller should switch to it.
    assert better_device(WITH_USB, ["USB", "default"], current_index=3) == (
        4, "Samson C01U Pro USB Microphone")


def test_better_device_none_when_priority_matches_nothing():
    assert better_device(INTERNAL_ONLY, ["USB"], current_index=3) is None


def test_better_device_none_for_empty_priority():
    assert better_device(WITH_USB, [], current_index=None) is None


def test_better_device_switches_when_current_index_unknown():
    # current_index None (running on the plain `device` fallback) and a priority
    # device is present ⇒ switch to it.
    assert better_device(WITH_USB, ["USB"], current_index=None) == (
        4, "Samson C01U Pro USB Microphone")


# --- diagnose_stream: device-loss verdict -----------------------------------

def test_diagnose_stream_ok_when_fresh_and_not_silent():
    assert diagnose_stream(
        now=100.0, last_window_ts=99.6, consecutive_silent_windows=0,
        stall_seconds=5.0, silence_windows_limit=120) == "ok"


def test_diagnose_stream_stalled_when_no_window_for_too_long():
    assert diagnose_stream(
        now=100.0, last_window_ts=90.0, consecutive_silent_windows=0,
        stall_seconds=5.0, silence_windows_limit=120) == "stalled"


def test_diagnose_stream_stall_takes_priority_over_silence():
    assert diagnose_stream(
        now=100.0, last_window_ts=80.0, consecutive_silent_windows=999,
        stall_seconds=5.0, silence_windows_limit=120) == "stalled"


def test_diagnose_stream_silent_when_zero_windows_pile_up():
    assert diagnose_stream(
        now=100.0, last_window_ts=99.9, consecutive_silent_windows=120,
        stall_seconds=5.0, silence_windows_limit=120) == "silent"


def test_diagnose_stream_silence_check_disabled_with_zero_limit():
    assert diagnose_stream(
        now=100.0, last_window_ts=99.9, consecutive_silent_windows=10_000,
        stall_seconds=5.0, silence_windows_limit=0) == "ok"


def test_diagnose_stream_grace_before_first_window():
    # last_window_ts None ⇒ no window yet; not stalled until stall_seconds pass
    # (the caller seeds last_window_ts at stream open, so None only occurs very
    # briefly, but the function must not crash / false-trip on it).
    assert diagnose_stream(
        now=100.0, last_window_ts=None, consecutive_silent_windows=0,
        stall_seconds=5.0, silence_windows_limit=120) == "ok"
