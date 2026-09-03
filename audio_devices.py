"""Input-device enumeration and priority-list selection.

Kept free of any `sounddevice` stream/state so the selection logic is a pure
function of a device list and can be unit-tested with synthetic lists.
"""
import logging

logger = logging.getLogger(__name__)


def input_devices(devices):
    """Filter a `sounddevice.query_devices()`-style list to capture-capable devices."""
    return [d for d in devices if d.get("max_input_channels", 0) > 0]


def select_input_device(devices, priority):
    """Return (index, name) of the first input device matching `priority`.

    `priority` is an ordered list whose entries are either an integer device
    index or a case-insensitive substring of a device name. The first entry that
    matches a capture-capable device wins. Returns None when nothing matches
    (caller then falls back to the plain `device` setting / system default).
    """
    candidates = input_devices(devices)
    for entry in priority:
        # bool is an int subclass — a stray `true` in TOML must not match index 1.
        if isinstance(entry, bool):
            logger.warning("Ignoring non-index/non-name device_priority entry: %r", entry)
            continue
        if isinstance(entry, int):
            match = next((d for d in candidates if d["index"] == entry), None)
        else:
            needle = str(entry).lower()
            match = next((d for d in candidates if needle in d["name"].lower()), None)
        if match is not None:
            return match["index"], match["name"]
    return None


def better_device(devices, priority, current_index):
    """Return (index, name) if the top `priority` match is a *different* device
    than the one currently in use, else None.

    Used to hot-switch to a higher-priority mic that was plugged in after start.
    `current_index` is the index of the running device, or None if it isn't one
    of the enumerated devices (e.g. running on the plain `device` fallback).
    """
    picked = select_input_device(devices, priority)
    if picked is None or picked[0] == current_index:
        return None
    return picked


def diagnose_stream(now, last_window_ts, consecutive_silent_windows,
                    stall_seconds, silence_windows_limit):
    """Verdict on a running input stream: 'ok', 'stalled', or 'silent'.

    - 'stalled': no audio window has arrived for `stall_seconds` — the stream is
      alive as an object but the device stopped delivering (typical on unplug
      when PortAudio doesn't raise).
    - 'silent': windows are arriving but all-zero for `silence_windows_limit`
      consecutive windows — a muted or half-dead device. `silence_windows_limit`
      of 0 or less disables this check.
    """
    if last_window_ts is not None and now - last_window_ts > stall_seconds:
        return "stalled"
    if silence_windows_limit > 0 and consecutive_silent_windows >= silence_windows_limit:
        return "silent"
    return "ok"


def describe_device(devices, device):
    """Human-readable 'index: name' for a resolved device setting, for logging.

    `device` is None (system default), an int index, or a name substring.
    Best-effort: returns a plain string even if the device can't be resolved.
    """
    if device is None:
        return "system default"
    if isinstance(device, bool):
        return repr(device)
    # Prefer an input-capable match, but fall back to any device so an explicitly
    # configured index/name still shows a name in the log even if sounddevice
    # exposes its capture side through a different (plug) entry.
    for pool in (input_devices(devices), list(devices)):
        if isinstance(device, int):
            match = next((d for d in pool if d["index"] == device), None)
        else:
            needle = str(device).lower()
            match = next((d for d in pool if needle in d["name"].lower()), None)
        if match is not None:
            return f"{match['index']}: {match['name']}"
    return f"{device!r} (unresolved)"
