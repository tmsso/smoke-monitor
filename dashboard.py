"""Live tuning dashboard (`--dashboard`).

A terminal UI, refreshed once per audio window, for tuning the detector against
`--play-tone` or a real alarm without waiting on a confirmed alert. Shows the
band-energy ratio versus the threshold, the dominant frequency, the per-window
hit/miss verdict, the rolling confirmation state, the active input device and
the PortAudio input-overflow count.

`rich` is imported lazily by `run_dashboard` so a normal `monitor.py` run (and
the systemd service) never needs it installed.
"""
import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from audio_devices import describe_device, select_input_device
from detector import WindowMetrics, SmokeDetector
from monitor import load_config, resolve_device

logger = logging.getLogger(__name__)

_METER_WIDTH = 40


def _meter(ratio: float, threshold: float, width: int = _METER_WIDTH) -> str:
    """A fixed-width bar for `ratio` in [0, 1] with a `|` at the threshold mark."""
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * width))
    mark = min(width - 1, int(round(threshold * width)))
    cells = ["█" if i < filled else "─" for i in range(width)]
    cells[mark] = "┃" if cells[mark] == "─" else "╋"
    return "".join(cells)


def render(
    metrics: WindowMetrics,
    *,
    device: str,
    threshold: float,
    freq_low: int,
    freq_high: int,
    overflows: int,
):
    """Build the rich renderable for one window's metrics (kept pure for tests)."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    verdict = Text("HIT ", style="bold red") if metrics.hit else Text("miss", style="dim")
    bar_style = "red" if metrics.hit else "green"
    meter = Text(_meter(metrics.ratio, threshold), style=bar_style)

    confirm = (
        f"{metrics.confirm_hits}/{metrics.confirm_len}, need {metrics.confirm_needed}"
        f"  (of {metrics.confirm_out_of})"
    )
    confirm_style = "bold red" if metrics.confirmed else ""

    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="cyan")
    grid.add_column()
    grid.add_row("band ratio", Text(f"{metrics.ratio:.3f}  ") + meter)
    grid.add_row("threshold", f"{threshold:.3f}  (band {freq_low}-{freq_high} Hz)")
    grid.add_row("dominant", f"{metrics.dominant_hz:.0f} Hz")
    grid.add_row("verdict", verdict)
    grid.add_row("confirmation", Text(confirm, style=confirm_style))
    grid.add_row("device", device)
    grid.add_row("overflows", str(overflows))

    title = "SMOKE ALARM CONFIRMED" if metrics.confirmed else "smoke-monitor — live tuning"
    return Panel(grid, title=title, border_style="red" if metrics.confirmed else "blue")


def run_dashboard(config_path: str = "config.toml") -> None:
    from rich.live import Live

    config = load_config(config_path)
    detector = SmokeDetector(config, testing=False)

    sample_rate = config["audio"]["sample_rate"]
    window_size = int(sample_rate * config["audio"]["window_seconds"])
    threshold = config["detection"]["energy_ratio_threshold"]
    freq_low = config["detection"]["freq_low_hz"]
    freq_high = config["detection"]["freq_high_hz"]

    devices = sd.query_devices()
    device = resolve_device(config["audio"].get("device", ""))
    priority = config["audio"].get("device_priority", []) or []
    if priority:
        picked = select_input_device(devices, priority)
        if picked is not None:
            device = picked[0]
    device_desc = describe_device(devices, device)

    audio_queue: queue.Queue = queue.Queue(maxsize=8)
    overflows = [0]

    def callback(indata, frames, time_info, status):
        if status and status.input_overflow:
            overflows[0] += 1
        try:
            audio_queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    stop = threading.Event()
    last = WindowMetrics(0.0, 0.0, False, 0, 0,
                         detector.confirm_windows, detector.confirm_out_of, False)

    logger.info("Dashboard on %s — Ctrl+C to stop", device_desc)
    with sd.InputStream(
        samplerate=sample_rate, blocksize=window_size, device=device,
        channels=1, dtype="float32", latency="high", callback=callback,
    ), Live(auto_refresh=False, screen=False) as live:
        live.update(
            render(last, device=device_desc, threshold=threshold,
                   freq_low=freq_low, freq_high=freq_high, overflows=overflows[0]),
            refresh=True,
        )
        try:
            while not stop.is_set():
                try:
                    samples = audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                last = detector.analyze_window(samples.astype(np.float32))
                live.update(
                    render(last, device=device_desc, threshold=threshold,
                           freq_low=freq_low, freq_high=freq_high,
                           overflows=overflows[0]),
                    refresh=True,
                )
        except KeyboardInterrupt:
            pass
    logger.info("Dashboard stopped")
