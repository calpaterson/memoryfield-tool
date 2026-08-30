"""Derive the distribution version from git tags: `git tag vX.Y.Z` on a clean
commit releases X.Y.Z.

An exact tag on a clean HEAD is the only uploadable form; anything else gets a
dev or local version marker so accidental publishes are impossible.  Outside a
git checkout (e.g. building a wheel from an sdist) the version comes from
PKG-INFO.  Used by hatchling via [tool.hatch.version] source = "code".
"""

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

_TAG_RE = re.compile(
    r"^v(?P<version>.+)-(?P<distance>\d+)-g(?P<commit>[0-9a-f]+)(?P<dirty>-dirty)?$"
)
_FALLBACK_VERSION = "0.0.0"


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def parse_describe(describe: str) -> str:
    """Turn `git describe --tags --long --dirty --match "v*"` output into a version."""
    match = _TAG_RE.match(describe)
    if match is None:
        # no v* tag reachable: --always fell back to a bare commit hash,
        # with a "-dirty" suffix when the tree is unclean
        commit = describe.removesuffix("-dirty")
        if commit != describe:
            stamp = datetime.now(UTC).strftime("%Y%m%d")
            return f"{_FALLBACK_VERSION}.dev0+g{commit}.d{stamp}"
        return f"{_FALLBACK_VERSION}.dev0+g{describe}"
    base = match["version"]
    distance = int(match["distance"])
    if distance > 0:
        return f"{base}.dev{distance}+g{match['commit']}"
    if match["dirty"]:
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        return f"{base}+g{match['commit']}.d{stamp}"
    return base


def version_from_pkg_info(root: Path) -> str | None:
    pkg_info = root / "PKG-INFO"
    if not pkg_info.exists():
        return None
    for line in pkg_info.read_text().splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    return None


def derive_version() -> str:
    override = os.environ.get("MEMORYFIELD_TOOL_VERSION")
    if override:
        return override

    root = Path(__file__).parent
    describe = _git(root, "describe", "--tags", "--long", "--dirty", "--always", "--match", "v*")
    if describe is None:
        version = version_from_pkg_info(root)
        return version if version is not None else _FALLBACK_VERSION
    return parse_describe(describe)
