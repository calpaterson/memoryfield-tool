import contextlib
import hashlib
import json
from datetime import datetime
from pathlib import Path

import sqlite_vec
from tqdm import tqdm

from . import embed, frontmatter, pages
from .db import sqlite3
from .transport import ObjectInfo, Transport

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


def _open_index(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=5.0)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(SCHEMA)
    return db


def _embed_input(content: bytes) -> str:
    truncated = content[:8192].decode("utf-8", errors="ignore")
    return f"search_document: {truncated}"


def build_index(t: Transport, index_loc: Path, progress: bool = True) -> tuple[int, int, bool]:
    # This function is specifically designed to avoid holding the database open
    # while embedding.  That's because embedding may well take >5s and causes
    # other instances to timeout (5s is the default timeout - a sensible
    # threshold).

    current: dict[str, ObjectInfo] = {info.key: info for info in pages.page_infos(t)}

    removed = 0
    # 1. clear pages in the index that are absent
    with contextlib.closing(_open_index(index_loc)) as db:
        cur = db.execute("SELECT filename FROM pages")
        for (filename,) in cur.fetchall():
            if filename not in current:
                db.execute("DELETE FROM pages where filename = ?", (filename,))
                removed += 1
        db.commit()

    # 2. pull the list of pages
    with contextlib.closing(_open_index(index_loc)) as db:
        cur = db.execute("""
        SELECT filename, last_modified, sha256_hash from pages
        """)
        pages_in_index: dict[str, tuple[datetime, bytes]] = {
            row[0]: (datetime.fromisoformat(row[1]), row[2]) for row in cur.fetchall()
        }

    # 3. for each, embed (if necessary) and then write back
    indexed_count = 0
    for object_info in tqdm(current.values(), desc="Indexing", unit="pages", disable=not progress):
        in_index = pages_in_index.get(object_info.key)

        if in_index is not None and in_index[0] == object_info.last_modified:
            # mtime unchanged: trust the index entry, avoid the transport read
            continue

        page_bytes = t.read_object(object_info.key)
        page_hash = hashlib.sha256(page_bytes).digest()

        if in_index is not None and in_index[1] == page_hash:
            # content unchanged, only the mtime moved: cheap UPDATE, no embedding
            with contextlib.closing(_open_index(index_loc)) as db:
                db.execute(
                    "UPDATE pages SET last_modified = ? WHERE filename = ?",
                    (object_info.last_modified.isoformat(), object_info.key),
                )
                db.commit()
            continue

        fm, _has = frontmatter.parse_frontmatter(page_bytes.decode("utf-8", errors="ignore"))
        frontmatter_json = json.dumps(fm, default=str)

        result = embed.embed_texts([_embed_input(page_bytes)])
        if result is None:
            return indexed_count, removed, False

        [embedding] = result
        embedding_blob = sqlite_vec.serialize_float32(embedding)

        with contextlib.closing(_open_index(index_loc)) as db:
            db.execute(
                "INSERT INTO pages "
                "(filename, frontmatter, last_modified, sha256_hash, embedding) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(filename) DO UPDATE SET "
                "frontmatter=excluded.frontmatter, last_modified=excluded.last_modified, "
                "sha256_hash=excluded.sha256_hash, embedding=excluded.embedding",
                (
                    object_info.key,
                    frontmatter_json,
                    object_info.last_modified.isoformat(),
                    page_hash,
                    embedding_blob,
                ),
            )
            db.commit()
            indexed_count += 1

    return indexed_count, removed, True


def delete_page(index_loc: Path, filename: str) -> None:
    """Remove a page's row from the vector index. No-op when the index is absent."""
    if not index_loc.is_file():
        return
    with contextlib.closing(_open_index(index_loc)) as db:
        db.execute("DELETE FROM pages WHERE filename = ?", (filename,))
        db.commit()


def reindex_page(t: Transport, index_loc: Path, filename: str) -> None:
    info = t.stat_object(filename)
    if info is None:
        return
    raw = t.read_object(filename)
    fm, _has = frontmatter.parse_frontmatter(raw.decode("utf-8", errors="ignore"))
    frontmatter_json = json.dumps(fm, default=str)

    result = embed.embed_texts([_embed_input(raw)])
    if result is None:
        return
    [embedding] = result
    embedding_blob = sqlite_vec.serialize_float32(embedding)
    mtime_iso = info.last_modified.isoformat()
    sha = hashlib.sha256(raw).digest()

    with contextlib.closing(_open_index(index_loc)) as db:
        db.execute(
            "INSERT INTO pages (filename, frontmatter, last_modified, sha256_hash, embedding) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(filename) DO UPDATE SET "
            "frontmatter=excluded.frontmatter, last_modified=excluded.last_modified, "
            "sha256_hash=excluded.sha256_hash, embedding=excluded.embedding",
            (filename, frontmatter_json, mtime_iso, sha, embedding_blob),
        )
        db.commit()
