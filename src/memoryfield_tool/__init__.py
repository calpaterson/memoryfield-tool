from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("memoryfield-tool")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0.dev0+unknown"
