import os
import subprocess
import sys
from pathlib import Path

from . import config, fields, index, pages

_LOG_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "memoryfield-tool"
LOG_PATH = _LOG_DIR / "reindex.log"


def spawn_background_index(name: str) -> None:
    # NOTE: the background-reindex path is not well tested yet.  It is covered
    # by a single ollama-gated integration test (tests/test_reindex.py) and is
    # best-effort: failures are logged to LOG_PATH and swallowed, and concurrent
    # runs are serialised only by the flock in index.build_index on a single
    # machine.  Re-run `memoryfield-tool index --field <name>` to force a
    # rebuild if the index looks stale.
    cfg = config.load_config()
    field = config.get_field(cfg, name)
    root = fields.field_root(field)
    if not index.index_path(root).is_file() and not pages.collect_pages(root):
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "memoryfield_tool", "index", "--field", name]
    try:
        with open(LOG_PATH, "ab") as log:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=True,
            )
    except OSError as e:
        with open(LOG_PATH, "ab") as log:
            log.write(f"failed to spawn background index for {name}: {e}\n".encode())
