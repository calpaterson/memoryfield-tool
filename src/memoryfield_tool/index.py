import fcntl
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pysqlite3 as sqlite3
import sqlite_vec
from tqdm import tqdm

from . import embed, frontmatter, pages

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
def _with_lock(root: Path) -> Iterator[None]:
    lock_path = index_path(root).with_suffix(".sqlite3.lock")
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


def _mtime_iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _embed_input(content: bytes) -> str:
    truncated = content[:8192].decode("utf-8", errors="ignore")
    return f"search_document: {truncated}"


def build_index(root: Path, progress: bool = True) -> tuple[int, int, bool]:
    with _with_lock(root):
        db = _open_index(index_path(root))

        disk: dict[str, tuple[str, bytes]] = {}
        for f in pages.collect_pages(root):
            raw = f.read_bytes()
            disk[f.name] = (_mtime_iso(f.stat().st_mtime), hashlib.sha256(raw).digest())

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
                raw = (root / filename).read_bytes()
                fm, _has = frontmatter.parse_frontmatter(raw.decode("utf-8", errors="ignore"))
                frontmatter_json = json.dumps(fm)

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


def reindex_page(root: Path, filename: str) -> None:
    with _with_lock(root):
        db = _open_index(index_path(root))
        path = root / filename
        raw = path.read_bytes()
        fm, _has = frontmatter.parse_frontmatter(raw.decode("utf-8", errors="ignore"))
        frontmatter_json = json.dumps(fm)

        result = embed.embed_texts([_embed_input(raw)])
        if result is None:
            db.close()
            return
        [embedding] = result
        embedding_blob = sqlite_vec.serialize_float32(embedding)
        mtime_iso = _mtime_iso(path.stat().st_mtime)
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
