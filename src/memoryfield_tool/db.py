"""SQLite backend: pysqlite3 when importable, else extension-capable stdlib.

sqlite-vec is loaded through the C extension API; some CPython builds
(e.g. --enable-load-extension omitted) cannot load it from stdlib sqlite3.
pysqlite3-binary bundles a current SQLite with extension loading always
enabled, so it is preferred where importable.
"""

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3 as sqlite3

    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        raise ImportError(
            "no extension-capable sqlite3 available: install pysqlite3-binary "
            "or use a Python built with --enable-load-extension"
        ) from None

__all__ = ["sqlite3"]
