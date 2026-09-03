"""Unit tests for priority-list device selection.

No hardware: `select_input_device` is a pure function over a synthetic device
list shaped like `sounddevice.query_devices()` output.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audio_devices import describe_device, select_input_device  # noqa: E402


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
