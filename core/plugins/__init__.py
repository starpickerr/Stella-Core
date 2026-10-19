"""Plugin Runtime: package lifecycle, registry, and worker process control.

This is the sole implementation site for the target Plugin Runtime (D23).
The legacy ``plugins.PluginManager`` must not scan directories managed here.
"""

from core.plugins.protocol import FrameError, decode_frame, encode_frame, read_frame, write_frame
from core.plugins.registry import ContributionSnapshot, PluginRegistry

__all__ = [
    "ContributionSnapshot",
    "FrameError",
    "PluginRegistry",
    "decode_frame",
    "encode_frame",
    "read_frame",
    "write_frame",
]
