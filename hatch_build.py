import hashlib
import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PICO_URL = "https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css"
PICO_SHA256 = "dd5fd5591afd81ee21dcc117ad85c014dc3f1f19dc2d7b7d101ea0acc29274c2"
_DEST = Path(__file__).parent / "src" / "memoryfield_tool" / "static" / "pico.min.css"


class PicoBuildHook(BuildHookInterface):
    """Download and pin pico.min.css into the wheel at build time.

    The asset is never checked into git; it is fetched from the pinned CDN URL
    and verified against a hard-coded sha256 so wheel contents are deterministic.
    """

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel":
            return
        _DEST.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(PICO_URL, timeout=30) as resp:
                data = resp.read()
        except OSError as e:
            raise RuntimeError(f"failed to download pico.css: {e}") from None
        digest = hashlib.sha256(data).hexdigest()
        if digest != PICO_SHA256:
            raise RuntimeError(f"pico.css sha256 mismatch: got {digest}, expected {PICO_SHA256}")
        _DEST.write_bytes(data)
