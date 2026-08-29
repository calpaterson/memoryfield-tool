import importlib
import sys

from memoryfield_tool import db


def test_selected_backend_supports_extensions():
    assert hasattr(db.sqlite3.Connection, "enable_load_extension")


def test_fallback_branch(monkeypatch):
    stdlib = importlib.import_module("sqlite3")
    monkeypatch.setitem(sys.modules, "pysqlite3", None)
    try:
        importlib.reload(db)
    except ImportError:
        assert not hasattr(stdlib.Connection, "enable_load_extension")
    else:
        assert hasattr(stdlib.Connection, "enable_load_extension")
        assert db.sqlite3 is stdlib
    finally:
        if "pysqlite3" in sys.modules:
            monkeypatch.undo()
        importlib.reload(db)
