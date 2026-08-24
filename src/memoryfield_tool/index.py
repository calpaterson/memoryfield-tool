import fcntl
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pysqlite3 as sqlite3
import sqlite_vec
from tqdm import tqdm

from . import embed, frontmatter, pages
from .transport import Transport

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    filename      TEXT PRIMARY KEY,
    frontmatter   JSON NOT NULL,
    last_modified DATETIME NOT NULL,
    sha256_hash   BLOB NOT NULL,
    embedding     BLOB NOT NULL
);
"""


def index_filename() -> str:
    return f"{embed.MODEL_CODE}.sqlite3"


def index_path(root: Path) -> Path:
    return root / index_filename()


@contextmanager
def _with_lock(index_loc: Path) -> Iterator[None]:
    lock_path = index_loc.with_suffix(".sqlite3.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = lock_path.open("w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _open_index(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(SCHEMA)
    return db


def _dt_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _embed_input(content: bytes) -> str:
    truncated = content[:8192].decode("utf-8", errors="ignore")
    return f"search_document: {truncated}"


def build_index(t: Transport, index_loc: Path, progress: bool = True) -> tuple[int, int, bool]:
    with _with_lock(index_loc):
        db = _open_index(index_loc)

        disk: dict[str, tuple[str, bytes]] = {}
        for info in pages.page_infos(t):
            raw = t.read_object(info.key)
            disk[info.key] = (_dt_iso(info.last_modified), hashlib.sha256(raw).digest())

        cur = db.execute("SELECT filename, sha256_hash FROM pages")
        indexed: dict[str, bytes] = {row[0]: row[1] for row in cur.fetchall()}

        removed = 0
        for filename in list(indexed):
            if filename not in disk:
                db.execute("DELETE FROM pages WHERE filename = ?", (filename,))
                removed += 1

        to_index = [
            filename for filename, (_mtime, sha) in disk.items() if indexed.get(filename) != sha
        ]

        indexed_count = 0
        if to_index:
            already_done = len(disk) - len(to_index)
            for filename in tqdm(
                to_index,
                desc="Indexing",
                unit="files",
                initial=already_done,
                total=len(disk),
                disable=not progress,
            ):
                raw = t.read_object(filename)
                fm, _has = frontmatter.parse_frontmatter(raw.decode("utf-8", errors="ignore"))
                frontmatter_json = json.dumps(fm, default=str)

                result = embed.embed_texts([_embed_input(raw)])
                if result is None:
                    return indexed_count, removed, False
                [embedding] = result
                embedding_blob = sqlite_vec.serialize_float32(embedding)
                mtime_iso, sha = disk[filename]

                db.execute(
                    "INSERT INTO pages "
                    "(filename, frontmatter, last_modified, sha256_hash, embedding) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(filename) DO UPDATE SET "
                    "frontmatter=excluded.frontmatter, last_modified=excluded.last_modified, "
                    "sha256_hash=excluded.sha256_hash, embedding=excluded.embedding",
                    (filename, frontmatter_json, mtime_iso, sha, embedding_blob),
                )
                indexed_count += 1

        db.commit()
        db.close()
        return indexed_count, removed, True


def delete_page(index_loc: Path, filename: str) -> None:
    """Remove a page's row from the vector index. No-op when the index is absent."""
    if not index_loc.is_file():
        return
    with _with_lock(index_loc):
        db = _open_index(index_loc)
        db.execute("DELETE FROM pages WHERE filename = ?", (filename,))
        db.commit()
        db.close()


def reindex_page(t: Transport, index_loc: Path, filename: str) -> None:
    with _with_lock(index_loc):
        db = _open_index(index_loc)
        info = t.stat_object(filename)
        if info is None:
            db.close()
            return
        raw = t.read_object(filename)
        fm, _has = frontmatter.parse_frontmatter(raw.decode("utf-8", errors="ignore"))
        frontmatter_json = json.dumps(fm, default=str)

        result = embed.embed_texts([_embed_input(raw)])
        if result is None:
            db.close()
            return
        [embedding] = result
        embedding_blob = sqlite_vec.serialize_float32(embedding)
        mtime_iso = _dt_iso(info.last_modified)
        sha = hashlib.sha256(raw).digest()

        db.execute(
            "INSERT INTO pages (filename, frontmatter, last_modified, sha256_hash, embedding) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(filename) DO UPDATE SET "
            "frontmatter=excluded.frontmatter, last_modified=excluded.last_modified, "
            "sha256_hash=excluded.sha256_hash, embedding=excluded.embedding",
            (filename, frontmatter_json, mtime_iso, sha, embedding_blob),
        )
        db.commit()
        db.close()
