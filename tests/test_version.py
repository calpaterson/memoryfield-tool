import importlib.util
import re
import sys
from pathlib import Path

import memoryfield_tool

_SPEC = importlib.util.spec_from_file_location(
    "_mft_version", Path(__file__).parent.parent / "version.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_mft_version = importlib.util.module_from_spec(_SPEC)
sys.modules["_mft_version"] = _mft_version
_SPEC.loader.exec_module(_mft_version)


def test_runtime_version_is_a_version():
    assert re.match(r"\d+\.\d+\.\d+", memoryfield_tool.__version__)


def test_parse_describe_exact_tag():
    assert _mft_version.parse_describe("v9.9.9-0-gabcdef1") == "9.9.9"


def test_parse_describe_prerelease_tag():
    assert _mft_version.parse_describe("v1.0.0rc1-0-gabcdef1") == "1.0.0rc1"


def test_parse_describe_with_distance():
    assert _mft_version.parse_describe("v1.2.3-4-gabcdef1") == "1.2.3.dev4+gabcdef1"


def test_parse_describe_dirty():
    version = _mft_version.parse_describe("v1.2.3-0-gabcdef1-dirty")
    assert version.startswith("1.2.3+gabcdef1.d")


def test_parse_describe_no_tags():
    assert _mft_version.parse_describe("abcdef1") == "0.0.0.dev0+gabcdef1"


def test_parse_describe_no_tags_dirty():
    version = _mft_version.parse_describe("abcdef1-dirty")
    assert version.startswith("0.0.0.dev0+gabcdef1.d")


def test_version_from_pkg_info(tmp_path):
    pkg_info = tmp_path / "PKG-INFO"
    pkg_info.write_text("Metadata-Version: 2.3\nName: memoryfield-tool\nVersion: 3.2.1\n")
    assert _mft_version.version_from_pkg_info(tmp_path) == "3.2.1"


def test_version_from_pkg_info_missing(tmp_path):
    assert _mft_version.version_from_pkg_info(tmp_path) is None
