"""PickChannel with a large-file layout through the real form (issue #40): the request carries one channel of a TZCYX file, and the whole
series is never decoded to make it. The chooser is filled from the tags (no pixel read). The size budget is the layer export's.
"""

from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _channelhelpers import WORK, choose_channel_tool, expect, finish, pick, sent_array, set_file, w

from napari_labconstrictor import _export

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

calls = {"series": 0, "file": 0}
for cls, name, key in [
    (tifffile.TiffPageSeries, "asarray", "series"),
    (tifffile.TiffFile, "asarray", "file"),
]:
    original = getattr(cls, name)

    def wrapper(
        self: "Any",
        *args: object,
        __original: "Callable[..., object]" = original,
        __key: str = key,
        **kwargs: object,
    ) -> object:
        calls[__key] += 1
        return __original(self, *args, **kwargs)

    setattr(cls, name, wrapper)

hyper = np.random.default_rng(3).integers(0, 60000, (2, 3, 4, 12, 14), dtype=np.uint16)  # T Z C Y X
path = WORK / "hyper.tif"
tifffile.imwrite(path, hyper, imagej=True, metadata={"axes": "TZCYX"})
choose_channel_tool()
box = w.channel_boxes["image"]
calls.update(series=0, file=0)
set_file(path)
expect(
    "chooser_filled_from_the_tags",
    list(box.choices) == ["Channel 1", "Channel 2", "Channel 3", "Channel 4"]
    and calls == {"series": 0, "file": 0},
    (list(box.choices), calls),
)
for index in range(4):
    pick("Channel %d" % (index + 1))
    calls.update(series=0, file=0)
    array, refused = sent_array()
    expect(
        "channel_%d_is_what_the_request_carries" % (index + 1),
        array is not None and array.shape == (2, 3, 12, 14) and np.array_equal(array, hyper[:, :, index]),
        (None if array is None else array.shape, refused),
    )
    expect(
        "channel_%d_series_never_decoded" % (index + 1), calls["series"] == 0 and calls["file"] <= 1, calls
    )  # the one file read is the test reading the sent file back

# the budget of the layer export applies: a channel that alone does not fit is refused at the click, nothing is sent
budget = _export.MAX_EXPORT_BYTES
_export.MAX_EXPORT_BYTES = hyper.nbytes // 4 - 1
try:
    pick("Channel 2")
    array, refused = sent_array()
finally:
    _export.MAX_EXPORT_BYTES = budget
expect(
    "channel_over_the_budget_is_refused",
    array is None and refused.startswith("⚠ 'Image': extracting one channel needs "),
    refused,
)
finish()
