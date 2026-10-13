"""PickChannel on an RGB TIFF given as a file (issue #39): the colour samples (axis `S`) are offered and exactly one 2D image is sent.

The fixtures are written with tifffile's `photometric="rgb"` and the test asserts that their series really has an `S` axis. The check is on
the REQUEST (the pixels of the file the click would send) and on a real run. The `C` axis keeps its behaviour, and the layouts nothing can
be picked from (an alpha channel, another sample count, `C` together with `S`) are refused with a sentence, never read as one channel.
"""

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _channelhelpers import (
    WORK,
    axes_of,
    choose_channel_tool,
    expect,
    finish,
    pick,
    rgb_plane,
    run,
    sent_array,
    set_file,
    w,
)

rgb = rgb_plane()
files = {
    "contig": WORK / "rgb_contig.tif",  # YXS
    "planar": WORK / "rgb_planar.tif",  # SYX
    "ome": WORK / "rgb_ome.tif",
    "deflate": WORK / "rgb_deflate.tif",
    "u16": WORK / "rgb_u16.tif",
}
tifffile.imwrite(files["contig"], rgb, photometric="rgb")
tifffile.imwrite(files["planar"], np.moveaxis(rgb, -1, 0).copy(), photometric="rgb", planarconfig="separate")
tifffile.imwrite(files["ome"], rgb, photometric="rgb", ome=True)
tifffile.imwrite(files["deflate"], rgb, photometric="rgb", compression="zlib")
rgb16 = rgb_plane(dtype=np.uint16) * 200
tifffile.imwrite(files["u16"], rgb16, photometric="rgb")

for (
    name,
    path,
) in files.items():  # the acceptance criterion: the fixtures really have an S axis, and no C axis
    expect(
        "fixture_%s_has_an_S_axis" % name, "S" in axes_of(path) and "C" not in axes_of(path), axes_of(path)
    )

choose_channel_tool()
box = w.channel_boxes["image"]
for name, path in files.items():
    source = rgb16 if name == "u16" else rgb
    set_file(path)
    expect(
        "%s_chooser_offers_the_colours" % name,
        not box.native.isHidden() and list(box.choices) == ["Red", "Green", "Blue"],
        list(box.choices),
    )
    for index, colour in enumerate(["Red", "Green", "Blue"]):
        pick(colour)
        array, refused = sent_array()
        ok = (
            array is not None
            and array.ndim == 2
            and array.dtype == source.dtype
            and np.array_equal(array, source[..., index])
        )
        expect(
            "%s_%s_is_exactly_one_2D_image" % (name, colour),
            ok,
            (None if array is None else (array.shape, array.dtype), refused),
        )

# a real run: what the tool receives is the chosen colour
set_file(files["contig"])
for index, colour in enumerate(["Red", "Green", "Blue"]):
    pick(colour)
    task = run()
    mean = float(rgb[..., index].mean())
    expect(
        "run_%s" % colour,
        task.status == "COMPLETE"
        and "mean=%s" % round(mean, 4) in w.status.text()
        and "6 x 7" in w.status.text(),
        w.status.text(),
    )

# C (acquisition channels) behaves as before
cyx = np.stack([np.full((6, 7), 10 * (c + 1), np.uint8) for c in range(3)])
tifffile.imwrite(WORK / "cyx.tif", cyx, imagej=True, metadata={"axes": "CYX"})
set_file(WORK / "cyx.tif")
expect(
    "C_axis_lists_channels", list(box.choices) == ["Channel 1", "Channel 2", "Channel 3"], list(box.choices)
)
pick("Channel 3")
array, refused = sent_array()
expect("C_axis_channel_is_sent", array is not None and np.array_equal(array, cyx[2]), (refused,))

# layouts nothing can be picked from are refused with a sentence, nothing is sent
label = w._label_of("image")
rgba = np.concatenate([rgb, np.full((6, 7, 1), 255, np.uint8)], axis=-1)
tifffile.imwrite(WORK / "rgba.tif", rgba, photometric="rgb", extrasamples=[2])
two = rgb[..., :2].copy()
tifffile.imwrite(WORK / "two.tif", two, photometric="minisblack", planarconfig="contig")
both = np.stack([rgb, rgb + 1])  # two channels of RGB
tifffile.imwrite(WORK / "both.tif", both, photometric="rgb", metadata={"axes": "CYXS"})
for tag, name, text in [
    (
        "alpha",
        "rgba.tif",
        "the file has 4 colour samples (S); only plain RGB (3) can be picked from, and an alpha channel is not interpreted",
    ),
    (
        "two_samples",
        "two.tif",
        "the file has 2 colour samples (S); only plain RGB (3) can be picked from, and an alpha channel is not interpreted",
    ),
    (
        "C_and_S",
        "both.tif",
        "the file has both channels (C) and colour samples (S); picking one is not supported: save one of them as its own file",
    ),
]:
    expect("fixture_%s_axes" % tag, "S" in axes_of(WORK / name), axes_of(WORK / name))
    set_file(WORK / name)
    expect("%s_said_when_the_file_is_chosen" % tag, text in w.status.text(), w.status.text())
    array, refused = sent_array()
    expect("%s_refused_at_run" % tag, array is None and refused == "⚠ '%s': %s" % (label, text), (refused,))

finish()
