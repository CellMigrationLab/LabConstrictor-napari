"""Shared helpers of the channel-extraction tests (import after `_paths`): TIFF fixtures of every layout, the form's request, a real run.
Not a test."""

import shutil
import tempfile
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _harness import expect, finish, pump, register, until  # noqa: F401
from _harness import widget as w

register("interactions", "labconstrictor_tools.examples.interactions")
WORK = Path(tempfile.mkdtemp(prefix="lcchan_"))


def choose_channel_tool():
    w.app_box.value = "interactions"
    pump(0.2)
    w.tool_box.value = "Mean of a channel"
    pump(0.8)


def axes_of(path):
    with tifffile.TiffFile(str(path)) as tif:
        return tif.series[0].axes


def set_file(path):
    w.file_sources["image"].value = Path(path)
    pump(0.4)


def pick(name):
    w.channel_boxes["image"].value = name
    pump(0.1)


def request():
    """(inputs, None) the form would send, or (None, status sentence) when the click refuses: the first half of a click."""
    seen = []
    w._launch = lambda form_values: seen.append(form_values)
    try:
        w.gui()
    finally:
        del w._launch
    job_dir = Path(tempfile.mkdtemp(prefix="lcin_"))
    w.status.setText("")
    prepared = w._prepare_inputs(seen[0], job_dir)
    if prepared is None:
        return None, w.status.text()
    inputs = prepared[0]
    sent = tifffile.imread(inputs["image"]) if inputs.get("image", "").endswith(".tif") else None
    shutil.rmtree(job_dir, ignore_errors=True)
    return inputs, sent if sent is not None else None


def sent_array():
    """The pixels the worker would be given for the image parameter, read from the file the request names (None when refused)."""
    seen = []
    w._launch = lambda form_values: seen.append(form_values)
    try:
        w.gui()
    finally:
        del w._launch
    job_dir = Path(tempfile.mkdtemp(prefix="lcin_"))
    w.status.setText("")
    prepared = w._prepare_inputs(seen[0], job_dir)
    if prepared is None:
        return None, w.status.text()
    array = tifffile.imread(prepared[0]["image"])
    shutil.rmtree(job_dir, ignore_errors=True)
    return array, None


def run():
    w.last_task = None
    w.gui()
    until(lambda: w.last_task is not None and w.task is w.last_task)
    pump(0.3)
    return w.last_task


def rgb_plane(height=6, width=7, dtype=np.uint8):
    """Three colours with different values everywhere, so a wrong axis or a wrong colour cannot give the right pixels."""
    yy, xx = np.mgrid[0:height, 0:width]
    return np.stack([(yy * 10 + xx) + 40 * c for c in range(3)], axis=-1).astype(dtype)
